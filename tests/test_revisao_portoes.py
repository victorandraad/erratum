"""Achados da revisao cruzada nos portoes: git que falha nao vira aprovacao, edicao pendente nao e
atropelada, a taxa por portao sai em ordem fixa e portao quebrado aparece como `pulou` no `top`.

Rodar: python3 -m unittest tests.test_revisao_portoes
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from erratum import portoes
from erratum.portoes import PORTOES, DiffDoDev
from tests.apoio import CasoComLedger

T = chr(0x2014)
COM_PROSA = "<?php\n// preco %s em centavos\nclass Money {}\n" % T
CALC_BUGADO = "def soma(a, b):\n    return a - b\n"
CALC_CERTO = "def soma(a, b):\n    return a + b\n"
TESTE = ("import unittest\nfrom acme import calc\n\nclass T(unittest.TestCase):\n"
         "    def test_soma(self):\n        self.assertEqual(5, calc.soma(2, 3))\n")
CMD_UNITTEST = ["python3 -B -m unittest {testes}"]


class FakeRes:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def git(wt, *args):
    return subprocess.run(["git", *args], cwd=str(wt), check=True, capture_output=True,
                          text=True).stdout.strip()


def repo(tmp, arquivos_base, arquivos_do_dev):
    wt = Path(tmp)
    git(wt, "init", "-q")
    git(wt, "config", "user.email", "dev@acme.test")
    git(wt, "config", "user.name", "dev")
    for etapa, arquivos in (("base", arquivos_base), ("dev", arquivos_do_dev)):
        for rel, texto in arquivos.items():
            (wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (wt / rel).write_text(texto, encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", etapa)
        if etapa == "base":
            base = git(wt, "rev-parse", "HEAD")
    return wt, base


def sh_que_falha_em(subcomando, rodadas=None):
    """git de verdade, menos o `git <subcomando>`, que falha sem rodar."""
    def fake(cmd, **kw):
        if cmd[:2] == ["git", subcomando]:
            return FakeRes(rc=1, err="fatal: nao deu")
        if rodadas is not None and cmd[0] != "git":
            rodadas.append(cmd)
        return portoes.executar(cmd, **kw)
    return fake


class EmDashComGitQuebrado(unittest.TestCase):
    def _roda(self, subcomando):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = repo(tmp, {"app/Money.php": "<?php\nclass Money {}\n"},
                            {"app/Money.php": COM_PROSA})
            head = git(wt, "rev-parse", "HEAD")
            visto = []
            r = portoes.PortaoEmDash(DiffDoDev(wt, base, sh=sh_que_falha_em(subcomando)),
                                     ao_decidir=lambda *a: visto.append(a)).rodar()
            self.assertNotEqual(portoes.APROVOU, r.veredito)
            self.assertTrue(r.pulou)
            self.assertFalse(r.extra["corrigiu"])
            self.assertIn("git %s" % subcomando, r.detalhe)
            self.assertEqual(("em-dash", portoes.PULOU), visto[0][:2])
            self.assertIn("git %s" % subcomando, visto[0][2])
            # nada fica pela metade: arquivo como o dev deixou, indice limpo, HEAD no lugar
            self.assertEqual(COM_PROSA, (wt / "app/Money.php").read_text(encoding="utf-8"))
            self.assertEqual("", git(wt, "status", "--porcelain"))
            self.assertEqual(head, git(wt, "rev-parse", "HEAD"))

    def test_commit_que_falha_nao_aprova(self):
        self._roda("commit")

    def test_add_que_falha_nao_aprova(self):
        self._roda("add")


class EdicaoPendenteNaoEAtropelada(unittest.TestCase):
    def _repo(self, tmp):
        return repo(tmp, {"acme/__init__.py": "", "acme/calc.py": CALC_BUGADO},
                    {"acme/calc.py": CALC_CERTO, "tests/test_calc.py": TESTE})

    def test_fix_noop_pula_com_alteracao_rastreada_pendente(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = self._repo(tmp)
            pendente = CALC_CERTO + "# ainda nao commitei\n"
            (wt / "acme/calc.py").write_text(pendente)
            rodadas, visto = [], []
            r = portoes.PortaoFixNoop(DiffDoDev(wt, base, sh=sh_que_falha_em("nada", rodadas)),
                                      comandos_de_teste=CMD_UNITTEST,
                                      ao_decidir=lambda *a: visto.append(a)).rodar()
            self.assertTrue(r.pulou, r.detalhe)
            self.assertIn("pendente", r.detalhe)
            self.assertEqual(pendente, (wt / "acme/calc.py").read_text())
            self.assertEqual([], rodadas)
            self.assertEqual(("fix-noop", portoes.PULOU), visto[0][:2])

    def test_fix_noop_pula_com_alteracao_so_no_indice(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = self._repo(tmp)
            (wt / "acme/__init__.py").write_text("# staged\n")
            git(wt, "add", "acme/__init__.py")
            r = portoes.PortaoFixNoop(DiffDoDev(wt, base), comandos_de_teste=CMD_UNITTEST).rodar()
            self.assertTrue(r.pulou, r.detalhe)
            self.assertEqual("M  acme/__init__.py", git(wt, "status", "--porcelain").strip())

    def test_arquivo_nao_rastreado_continua_passando(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = self._repo(tmp)
            (wt / "rascunho.txt").write_text("nota solta\n")
            r = portoes.PortaoFixNoop(DiffDoDev(wt, base), comandos_de_teste=CMD_UNITTEST).rodar()
            self.assertEqual(portoes.APROVOU, r.veredito, r.detalhe)
            self.assertEqual("nota solta\n", (wt / "rascunho.txt").read_text())

    def test_em_dash_tambem_nao_atropela_edicao_pendente(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = repo(tmp, {"app/Money.php": "<?php\nclass Money {}\n"},
                            {"app/Money.php": COM_PROSA})
            pendente = COM_PROSA + "// ainda nao commitei\n"
            (wt / "app/Money.php").write_text(pendente, encoding="utf-8")
            head = git(wt, "rev-parse", "HEAD")
            r = portoes.PortaoEmDash(DiffDoDev(wt, base)).rodar()
            self.assertTrue(r.pulou, r.detalhe)
            self.assertEqual(pendente, (wt / "app/Money.php").read_text(encoding="utf-8"))
            self.assertEqual(head, git(wt, "rev-parse", "HEAD"))


class PortaoQuebrado(portoes.Portao):
    nome = "quebrado"

    def _julgar(self):
        raise RuntimeError("regex explodiu na linha 7")


class TopNaoEscondePortaoQuebrado(CasoComLedger):
    def test_ordem_mais_reprovacoes_primeiro_e_nome_desempata(self):
        # inseridos fora da ordem esperada, de proposito
        for nome, vereditos in (("zeta", ["reprovou"]), ("beta", ["aprovou"]),
                                ("alfa", ["reprovou"]), ("gama", ["reprovou"] * 3)):
            for v in vereditos:
                self.ledger.registrar_portao(nome, v, "", "acme")
        _, saida = self.cli("top", "--json")
        self.assertEqual(["gama", "alfa", "zeta", "beta"],
                         [p["portao"] for p in json.loads(saida)["portoes"]])
        _, texto = self.cli("top")
        posicoes = [texto.index("portão %s:" % n) for n in ("gama", "alfa", "zeta", "beta")]
        self.assertEqual(sorted(posicoes), posicoes)

    def test_excecao_interna_grava_o_detalhe_e_conta_como_pulou_no_top(self):
        def ao_decidir(nome, veredito, detalhe):
            self.ledger.registrar_portao(nome, veredito, detalhe, "acme")

        for _ in range(2):
            r = PortaoQuebrado(DiffDoDev("/tmp", "main"), ao_decidir=ao_decidir).rodar()
            self.assertTrue(r.pulou)
        linhas = self.banco.consultar("SELECT verdict, detail FROM gate_runs ORDER BY id")
        self.assertEqual(["pulou", "pulou"], [l["verdict"] for l in linhas])
        self.assertIn("regex explodiu na linha 7", linhas[0]["detail"])
        _, saida = self.cli("top", "--json")
        quebrado = [p for p in json.loads(saida)["portoes"] if p["portao"] == "quebrado"][0]
        self.assertEqual((2, 2, 0), (quebrado["rodadas"], quebrado["pulou"], quebrado["reprovou"]))
        _, texto = self.cli("top")
        self.assertIn("portão quebrado: 0/0 reprovou (0%), 2 pulou", texto)

    def test_gate_da_cli_continua_registrando_os_portoes_conhecidos(self):
        self.assertEqual({"em-dash", "stub-neutro", "fix-noop"}, set(PORTOES))


if __name__ == "__main__":
    unittest.main()
