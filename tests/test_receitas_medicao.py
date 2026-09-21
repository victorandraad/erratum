"""Medição das receitas: o `scan` conta desvio e uso nos comandos Bash do transcript, o `top` mostra
os improvisos por receita e o `efeito` compara uso com desvio.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.apoio import CasoComLedger


def _bash(id_uso, comando):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": id_uso, "name": "Bash", "input": {"command": comando}}
            ]
        },
    }


class CasoComReceita(CasoComLedger):
    def setUp(self):
        super().setUp()
        self.cli(
            "recipe", "add", "esperar-ci", "--project", "geral",
            "--quando", "esperar o CI", "--cmd", "bin/ci-espera <pr>",
            "--em-vez-de", r"\bgh\s+(pr\s+checks|run\s+watch)\b",
        )
        self.cli(
            "recipe", "add", "suite", "--quando", "rodar a suíte",
            "--cmd", "bin/suite", "--em-vez-de", r"\bpython3 -m unittest\b",
        )

    def _stream(self, nome, eventos):
        caminho = Path(self._tmp.name) / nome
        caminho.write_text(
            "\n".join(json.dumps(e) for e in eventos) + "\n", encoding="utf-8"
        )
        return str(caminho)


class TesteScan(CasoComReceita):
    def _eventos(self):
        return [
            _bash("a", "gh pr checks 12 --watch"),
            _bash("b", "bin/ci-espera 12"),
            _bash("c", "ls -la"),
            _bash("d", "gh run watch 7"),
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "e", "name": "Read", "input": {"file_path": "gh pr checks"}},
                {"type": "tool_use", "id": "f", "name": "Bash", "input": {"command": 7}},
                {"type": "tool_use", "id": "g", "name": "Bash", "input": None},
            ]}},
        ]

    def test_conta_desvio_e_uso_dos_comandos_bash(self):
        caminho = self._stream("exec-1.jsonl", self._eventos())
        codigo, saida = self.cli("scan", caminho, "--json")
        self.assertEqual(codigo, 0)
        dado = json.loads(saida)
        self.assertEqual(dado["receitas"], {"desvios": 2, "usos": 1})
        linhas = self.banco.consultar(
            "SELECT tipo, task, comando FROM usos_de_receita ORDER BY id"
        )
        self.assertEqual([l["tipo"] for l in linhas], ["desvio", "uso", "desvio"])
        self.assertEqual({l["task"] for l in linhas}, {"exec-1"})
        _c, saida = self.cli("scan", caminho)
        self.assertIn("receitas: 2 desvios, 1 usos", saida)

    def test_rescan_do_mesmo_arquivo_nao_duplica(self):
        caminho = self._stream("exec-1.jsonl", self._eventos())
        self.cli("scan", caminho)
        self.cli("scan", caminho)
        n = self.banco.consultar("SELECT COUNT(*) AS n FROM usos_de_receita")[0]["n"]
        self.assertEqual(n, 3)

    def test_rescan_nao_apaga_o_que_veio_do_check_cmd(self):
        self.cli("check-cmd", "gh run watch 1")
        self.cli("check-cmd", "gh run watch 1", "--task", "exec-1")
        caminho = self._stream("exec-1.jsonl", self._eventos())
        self.cli("scan", caminho)
        self.cli("scan", caminho)
        n = self.banco.consultar("SELECT COUNT(*) AS n FROM usos_de_receita")[0]["n"]
        self.assertEqual(n, 5)

    def test_scan_sem_receita_nenhuma_continua_minerando_erro(self):
        self.cli("recipe", "rm", "esperar-ci", "--project", "geral")
        self.cli("recipe", "rm", "suite")
        caminho = self._stream("exec-2.jsonl", self._eventos())
        codigo, saida = self.cli("scan", caminho, "--json")
        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(saida)["receitas"], {"desvios": 0, "usos": 0})


class TesteTopEEfeito(CasoComReceita):
    def setUp(self):
        super().setUp()
        for _ in range(3):
            self.cli("check-cmd", "gh pr checks 12 --watch")
        self.cli("check-cmd", "bin/ci-espera 12")
        self.cli("check-cmd", "python3 -m unittest discover")

    def test_top_mostra_improvisos_por_receita(self):
        _c, saida = self.cli("top")
        self.assertIn("improvisos", saida)
        self.assertLess(saida.index("esperar-ci"), saida.index("suite"))
        _c, saida = self.cli("top", "--json")
        improvisos = json.loads(saida)["improvisos"]
        self.assertEqual(
            [(i["receita"], i["desvios"]) for i in improvisos],
            [("esperar-ci", 3), ("suite", 1)],
        )

    def test_top_respeita_days(self):
        self.relogio.avancar(days=10)
        self.cli("check-cmd", "python3 -m unittest discover")
        _c, saida = self.cli("top", "--days", "5", "--json")
        improvisos = json.loads(saida)["improvisos"]
        self.assertEqual([(i["receita"], i["desvios"]) for i in improvisos], [("suite", 1)])

    def test_top_sem_desvio_nao_mostra_a_secao(self):
        with self.banco.transacao() as con:
            con.execute("DELETE FROM usos_de_receita")
        _c, saida = self.cli("top")
        self.assertNotIn("improvisos", saida)

    def test_top_de_outro_projeto_nao_conta(self):
        _c, saida = self.cli("top", "--json", "--project", "vizinho")
        self.assertEqual(json.loads(saida)["improvisos"], [])
        _c, saida = self.cli("top", "--json", "--project", "vizinho", "--all-projects")
        self.assertEqual(len(json.loads(saida)["improvisos"]), 2)

    def test_efeito_compara_uso_com_desvio(self):
        _c, saida = self.cli("efeito", "--json")
        receitas = {r["receita"]: r for r in json.loads(saida)["receitas"]}
        self.assertEqual(
            (receitas["esperar-ci"]["usos"], receitas["esperar-ci"]["desvios"]), (1, 3)
        )
        self.assertAlmostEqual(receitas["esperar-ci"]["taxa_de_uso"], 0.25)
        self.assertEqual((receitas["suite"]["usos"], receitas["suite"]["desvios"]), (0, 1))
        _c, saida = self.cli("efeito")
        self.assertIn("receita esperar-ci: 1 uso, 3 desvios (25% pela receita)", saida)

    def test_efeito_sem_receita_mantem_o_formato_antigo(self):
        with self.banco.transacao() as con:
            con.execute("DELETE FROM usos_de_receita")
        _c, saida = self.cli("efeito", "--json")
        dado = json.loads(saida)
        self.assertEqual(dado["receitas"], [])
        self.assertIn("tasks", dado)
