"""Receitas: comando executável + quando usar + o que ela substitui.

Cobre o schema novo (com banco antigo abrindo sem perder dado), o CRUD por `erratum recipe` e o
`check-cmd`, que é determinístico: regex do `em_vez_de` contra o comando, sem FTS no caminho.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.apoio import CasoComLedger

_SCHEMA_ANTIGO = """
CREATE TABLE fixes (
    id INTEGER PRIMARY KEY, ts TEXT, project TEXT, signature TEXT, note TEXT,
    ref TEXT, test TEXT, source TEXT, import_key TEXT UNIQUE
);
CREATE TABLE errors (
    id INTEGER PRIMARY KEY, ts TEXT, project TEXT, kind TEXT, stage TEXT, tool TEXT,
    signature TEXT, text TEXT, context_json TEXT, import_key TEXT UNIQUE
);
CREATE TABLE pistas (
    id INTEGER PRIMARY KEY, ts TEXT, project TEXT, task TEXT, erro_id INTEGER,
    correcao_id INTEGER, origem TEXT, veredito TEXT, confianca REAL, desfecho TEXT,
    desfecho_ts TEXT
);
INSERT INTO fixes(ts, project, signature, note, ref, test, source)
    VALUES ('2026-01-01', 'acme', 'exit code N', 'rodar o prep', 'abc', 't', 'manual');
INSERT INTO errors(ts, project, kind, signature, text)
    VALUES ('2026-01-01', 'acme', 'error', 'exit code N', 'exit code 1');
"""


class TesteMigracao(unittest.TestCase):
    def test_banco_antigo_abre_sem_perder_dado_e_ganha_as_tabelas(self):
        from erratum.banco import Banco

        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "ledger.db"
            con = sqlite3.connect(str(caminho))
            con.executescript(_SCHEMA_ANTIGO)
            con.commit()
            con.close()
            with Banco(caminho) as banco:
                fixes = banco.consultar("SELECT note, receita FROM fixes")
                self.assertEqual(len(fixes), 1)
                self.assertEqual(fixes[0]["note"], "rodar o prep")
                self.assertIn(fixes[0]["receita"], (None, ""))
                self.assertEqual(
                    banco.consultar("SELECT COUNT(*) AS n FROM errors")[0]["n"], 1
                )
                colunas = {
                    l["name"] for l in banco.consultar("PRAGMA table_info(receitas)")
                }
                self.assertTrue(
                    {
                        "id", "ts", "project", "nome", "quando", "comando", "notas",
                        "perigo", "em_vez_de_json", "origem", "import_key",
                    }
                    <= colunas
                )
                usos = {
                    l["name"]
                    for l in banco.consultar("PRAGMA table_info(usos_de_receita)")
                }
                self.assertTrue(
                    {"id", "ts", "project", "task", "receita_id", "comando", "tipo"}
                    <= usos
                )
            # abrir de novo não quebra (migração idempotente)
            with Banco(caminho) as banco:
                self.assertEqual(
                    banco.consultar("SELECT COUNT(*) AS n FROM fixes")[0]["n"], 1
                )


class TesteRecipeCrud(CasoComLedger):
    def _add(self, nome="esperar-ci", *extra, projeto=None):
        argv = [
            "recipe", "add", nome,
            "--quando", "esperar o CI de um PR terminar",
            "--cmd", "gh pr checks <pr> --watch --fail-fast",
            "--em-vez-de", r"\bsleep\s+\d+.*\bgh\s+pr\s+checks\b",
        ]
        if projeto:
            argv += ["--project", projeto]
        return self.cli(*argv, *extra)

    def test_add_show_ls_rm(self):
        codigo, saida = self._add()
        self.assertEqual(codigo, 0)
        self.assertIn("esperar-ci", saida)
        codigo, saida = self.cli("recipe", "show", "esperar-ci", "--json")
        self.assertEqual(codigo, 0)
        dado = json.loads(saida)["receita"]
        self.assertEqual(dado["comando"], "gh pr checks <pr> --watch --fail-fast")
        self.assertEqual(dado["projeto"], "acme")
        self.assertEqual(dado["origem"], "manual")
        self.assertEqual(len(dado["em_vez_de"]), 1)
        codigo, saida = self.cli("recipe", "ls")
        self.assertIn("esperar-ci", saida)
        self.assertIn("gh pr checks", saida)
        self.assertEqual(self.cli("recipe", "rm", "esperar-ci")[0], 0)
        self.assertEqual(self.cli("recipe", "show", "esperar-ci")[0], 2)
        self.assertEqual(self.cli("recipe", "rm", "esperar-ci")[0], 2)

    def test_add_de_novo_atualiza_em_vez_de_duplicar(self):
        self._add()
        self._add("esperar-ci", "--notas", "sai 1 no vermelho")
        n = self.banco.consultar("SELECT COUNT(*) AS n FROM receitas")[0]["n"]
        self.assertEqual(n, 1)
        _c, saida = self.cli("recipe", "show", "esperar-ci", "--json")
        self.assertEqual(json.loads(saida)["receita"]["notas"], "sai 1 no vermelho")

    def test_regex_invalida_e_uso_errado(self):
        codigo, _s = self.cli(
            "recipe", "add", "x", "--quando", "q", "--cmd", "c", "--em-vez-de", "gh (pr"
        )
        self.assertEqual(codigo, 2)
        n = self.banco.consultar("SELECT COUNT(*) AS n FROM receitas")[0]["n"]
        self.assertEqual(n, 0)

    def test_regex_longa_demais_ou_com_quantificador_aninhado_e_recusada(self):
        for ruim in ("a" * 301, r"(a+)+$", r"(\w*)*x"):
            codigo, _s = self.cli(
                "recipe", "add", "x", "--quando", "q", "--cmd", "c",
                "--em-vez-de", ruim,
            )
            self.assertEqual(codigo, 2, ruim[:20])

    def test_sem_quando_ou_sem_cmd_e_uso_errado(self):
        self.assertEqual(self.cli("recipe", "add", "x", "--cmd", "c")[0], 2)
        self.assertEqual(self.cli("recipe", "add", "x", "--quando", "q")[0], 2)

    def test_projeto_tem_prioridade_sobre_a_geral_de_mesmo_nome(self):
        self._add(projeto="geral")
        self.cli(
            "recipe", "add", "esperar-ci", "--quando", "esperar CI aqui",
            "--cmd", "bin/espera <pr>",
        )
        _c, saida = self.cli("recipe", "show", "esperar-ci", "--json")
        self.assertEqual(json.loads(saida)["receita"]["comando"], "bin/espera <pr>")
        _c, saida = self.cli("recipe", "ls", "--json")
        nomes = [r["nome"] for r in json.loads(saida)["receitas"]]
        self.assertEqual(nomes.count("esperar-ci"), 1)
        # de outro projeto a geral continua valendo
        _c, saida = self.cli("recipe", "show", "esperar-ci", "--json", "--project", "outro")
        self.assertIn("gh pr checks", json.loads(saida)["receita"]["comando"])

    def test_receita_de_outro_projeto_nao_aparece(self):
        self._add(projeto="vizinho")
        self.assertEqual(self.cli("recipe", "show", "esperar-ci")[0], 2)


class TesteCheckCmd(CasoComLedger):
    def setUp(self):
        super().setUp()
        self.cli(
            "recipe", "add", "esperar-ci", "--project", "geral",
            "--quando", "esperar o CI de um PR terminar",
            "--cmd", "bin/ci-espera <pr> [--repo dono/nome]",
            "--em-vez-de", r"\bgh\s+(pr\s+checks|run\s+watch)\b",
            "--em-vez-de", r"\bsleep\s+\d+.*\bgh\s",
            "--perigo", "rode em background",
        )

    def _usos(self):
        return [
            (l["tipo"], l["receita_id"] is not None)
            for l in self.banco.consultar("SELECT * FROM usos_de_receita ORDER BY id")
        ]

    def test_improviso_sai_1_aponta_a_receita_e_grava_desvio(self):
        codigo, saida = self.cli("check-cmd", "cd /w && gh pr checks 12 --watch")
        self.assertEqual(codigo, 1)
        self.assertIn("use a receita esperar-ci: bin/ci-espera <pr>", saida)
        self.assertIn("rode em background", saida)
        self.assertEqual(self._usos(), [("desvio", True)])

    def test_comando_sem_receita_e_silencio_e_nao_grava(self):
        codigo, saida = self.cli("check-cmd", "gh pr view 12 --json state")
        self.assertEqual((codigo, saida), (0, ""))
        self.assertEqual(self._usos(), [])

    def test_comando_que_ja_e_a_receita_grava_uso(self):
        codigo, saida = self.cli("check-cmd", "cd /w && bin/ci-espera 12 --repo a/b")
        self.assertEqual((codigo, saida), (0, ""))
        self.assertEqual(self._usos(), [("uso", True)])

    def test_canonico_vence_o_em_vez_de(self):
        self.cli(
            "recipe", "add", "suite", "--quando", "rodar a suíte",
            "--cmd", 'ESTADO="$(mktemp -d)" python3 -m unittest discover tests',
            "--em-vez-de", r"python3 -m unittest discover",
        )
        codigo, _s = self.cli(
            "check-cmd", 'ESTADO="$(mktemp -d)" python3 -m unittest discover tests'
        )
        self.assertEqual(codigo, 0)
        self.assertEqual(self.cli("check-cmd", "python3 -m unittest discover tests")[0], 1)

    def test_canonico_exige_o_comando_inteiro_nao_so_o_prefixo(self):
        self.cli(
            "recipe", "add", "consulta", "--quando", "consultar o banco",
            "--cmd", 'bin/sql "[leitura]" <banco> "<sql>" --so-leitura [--formato <f>]',
        )
        _c, saida = self.cli("check-cmd", 'bin/sql "[leitura]" a.db', "--json")
        self.assertIsNone(json.loads(saida)["tipo"])
        _c, saida = self.cli(
            "check-cmd", 'bin/sql "[leitura]" a.db "select 1 from t" --so-leitura', "--json"
        )
        self.assertEqual(json.loads(saida)["tipo"], "uso")

    def test_indice_do_how_e_nome_quando_e_notas(self):
        linha = self.banco.consultar("SELECT * FROM receitas_fts")[0]
        self.assertNotIn("ci-espera", linha["note"] or "")

    def test_canonico_de_uma_receita_nao_esconde_o_desvio_de_outra(self):
        # a receita do projeto manda usar o script; o comando cru é canônico só da geral
        self.cli(
            "recipe", "add", "espera-crua", "--project", "geral",
            "--quando", "esperar o CI", "--cmd", "gh run watch <run>",
        )
        codigo, saida = self.cli("check-cmd", "gh run watch 99", "--json")
        self.assertEqual(codigo, 1)
        self.assertEqual(json.loads(saida)["receita"], "esperar-ci")

    def test_json(self):
        codigo, saida = self.cli("check-cmd", "gh run watch 99", "--json")
        self.assertEqual(codigo, 1)
        dado = json.loads(saida)
        self.assertEqual(dado["tipo"], "desvio")
        self.assertEqual(dado["receita"], "esperar-ci")
        self.assertEqual(dado["perigo"], "rode em background")
        _c, saida = self.cli("check-cmd", "ls", "--json")
        self.assertIsNone(json.loads(saida)["tipo"])

    def test_receita_de_outro_projeto_nao_barra(self):
        self.cli(
            "recipe", "add", "so-la", "--project", "vizinho", "--quando", "q",
            "--cmd", "bin/x", "--em-vez-de", r"\bmake\s+deploy\b",
        )
        self.assertEqual(self.cli("check-cmd", "make deploy")[0], 0)
        self.assertEqual(self.cli("check-cmd", "make deploy", "--project", "vizinho")[0], 1)

    def test_so_os_primeiros_4_kb_do_comando_sao_avaliados(self):
        longo = "echo " + "x" * 5000 + " ; gh run watch 1"
        self.assertEqual(self.cli("check-cmd", longo)[0], 0)

    def test_regex_podre_gravada_direto_no_banco_nao_derruba(self):
        with self.banco.transacao() as con:
            con.execute(
                "UPDATE receitas SET em_vez_de_json = ?", (json.dumps(["gh (pr", 7]),)
            )
        self.assertEqual(self.cli("check-cmd", "gh pr checks 1")[0], 0)
        with self.banco.transacao() as con:
            con.execute("UPDATE receitas SET em_vez_de_json = 'nao e json'")
        self.assertEqual(self.cli("check-cmd", "gh pr checks 1")[0], 0)

    def test_comando_do_stdin(self):
        codigo, _s = self.cli("check-cmd", "-", entrada="gh run watch 5\n")
        self.assertEqual(codigo, 1)

    def test_check_cmd_nao_toca_no_fts(self):
        vistos = []
        self.banco._con.set_trace_callback(vistos.append)
        self.cli("check-cmd", "gh pr checks 12 --watch")
        self.banco._con.set_trace_callback(None)
        self.assertFalse([s for s in vistos if "fts" in s.lower()], vistos)


class TesteCaminhoRapido(unittest.TestCase):
    def test_check_cmd_nao_carrega_portoes_mineracao_nem_sementes(self):
        import os
        import subprocess
        import sys

        codigo = (
            "import sys\n"
            "from erratum import cli\n"
            "try:\n"
            "    cli.main(['check-cmd', 'ls', '--project', 'acme'])\n"
            "except SystemExit:\n"
            "    pass\n"
            "pesados = ('erratum.portoes', 'erratum.mineracao', 'erratum.sementes')\n"
            "print(sorted(m for m in sys.modules if m in pesados))\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            ambiente = dict(os.environ)
            ambiente["ERRATUM_DB"] = str(Path(tmp) / "ledger.db")
            ambiente["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            proc = subprocess.run(
                [sys.executable, "-B", "-c", codigo],
                env=ambiente, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(proc.stdout.strip(), "[]", proc.stderr)


if __name__ == "__main__":
    unittest.main()
