"""`erratum gate`: roda os portões num repo git de verdade e grava o veredito em `gate_runs`."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.apoio import CasoComLedger

CALC_BUGADO = "def soma(a, b):\n    return a - b\n"
CALC_CERTO = "def soma(a, b):\n    return a + b\n"
TESTE_QUE_PROVA = ("import unittest\nfrom acme import calc\n\n\nclass T(unittest.TestCase):\n"
                   "    def test_soma(self):\n        self.assertEqual(5, calc.soma(2, 3))\n")
TESTE_QUE_SEMPRE_PASSA = ("import unittest\nfrom acme import calc\n\n\nclass T(unittest.TestCase):\n"
                          "    def test_soma(self):\n        self.assertTrue(callable(calc.soma))\n")
CMD = "%s -B -m unittest {testes}" % sys.executable


def git(wt, *args):
    return subprocess.run(["git", *args], cwd=wt, check=True, capture_output=True,
                          text=True).stdout.strip()


class TestGate(CasoComLedger):
    def _repo(self, teste_do_dev):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wt = Path(tmp.name)
        git(wt, "init", "-q")
        git(wt, "config", "user.email", "dev@acme.test")
        git(wt, "config", "user.name", "dev")
        (wt / "acme").mkdir()
        (wt / "tests").mkdir()
        (wt / "acme" / "__init__.py").write_text("")
        (wt / "acme" / "calc.py").write_text(CALC_BUGADO)
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "base")
        base = git(wt, "rev-parse", "HEAD")
        (wt / "acme" / "calc.py").write_text(CALC_CERTO)
        (wt / "tests" / "test_calc.py").write_text(teste_do_dev)
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "fix")
        return wt, base

    def _gate_runs(self):
        return [(l["project"], l["gate"], l["verdict"]) for l in self.banco.consultar(
            "SELECT project, gate, verdict FROM gate_runs ORDER BY id")]

    def test_aprovou_grava_e_sai_zero(self):
        wt, base = self._repo(TESTE_QUE_PROVA)
        codigo, saida = self.cli("gate", "em-dash,fix-noop", "--base", base,
                                 "--worktree", str(wt), "--test-cmd", CMD)
        self.assertEqual(codigo, 0, saida)
        self.assertEqual(self._gate_runs(), [("acme", "em-dash", "aprovou"),
                                             ("acme", "fix-noop", "aprovou")])
        linhas = saida.strip().splitlines()
        self.assertEqual(len(linhas), 2)
        self.assertIn("em-dash", linhas[0])
        self.assertIn("aprovou", linhas[1])

    def test_reprovou_grava_e_sai_um(self):
        wt, base = self._repo(TESTE_QUE_SEMPRE_PASSA)
        codigo, saida = self.cli("gate", "fix-noop,stub-neutro", "--base", base,
                                 "--worktree", str(wt), "--test-cmd", CMD, "--json")
        self.assertEqual(codigo, 1, saida)
        # um reprovado nao impede os demais de rodar: todo veredito vai pro ledger
        self.assertEqual(self._gate_runs(), [("acme", "fix-noop", "reprovou"),
                                             ("acme", "stub-neutro", "aprovou")])
        dado = json.loads(saida)
        self.assertEqual([(p["portao"], p["veredito"]) for p in dado["portoes"]],
                         [("fix-noop", "reprovou"), ("stub-neutro", "aprovou")])
        self.assertTrue(dado["reprovou"])

    def test_sem_test_cmd_fix_noop_pula_e_sai_zero(self):
        wt, base = self._repo(TESTE_QUE_PROVA)
        codigo, _ = self.cli("gate", "fix-noop", "--base", base, "--worktree", str(wt))
        self.assertEqual(codigo, 0)
        self.assertEqual(self._gate_runs(), [("acme", "fix-noop", "pulou")])

    def test_portao_invalido_e_uso_errado_e_nao_roda_nada(self):
        wt, base = self._repo(TESTE_QUE_PROVA)
        codigo, _ = self.cli("gate", "em-dash,inventado", "--base", base, "--worktree", str(wt))
        self.assertEqual(codigo, 2)
        self.assertEqual(self._gate_runs(), [])

    def test_sem_base_e_uso_errado(self):
        self.assertEqual(self.cli("gate", "em-dash")[0], 2)


class TestTopMostraPortoes(CasoComLedger):
    def test_taxa_de_reprovacao_por_portao(self):
        for veredito in ("reprovou", "aprovou", "aprovou", "pulou"):
            self.ledger.registrar_portao("fix-noop", veredito, "", "acme")
        self.ledger.registrar_portao("em-dash", "aprovou", "", "acme")
        self.ledger.registrar_portao("em-dash", "reprovou", "", "outro")
        _, saida = self.cli("top", "--json")
        portoes = {p["portao"]: p for p in json.loads(saida)["portoes"]}
        # pulou nao entra no denominador: a taxa e sobre quem julgou de verdade
        self.assertEqual((portoes["fix-noop"]["rodadas"], portoes["fix-noop"]["reprovou"],
                          portoes["fix-noop"]["pulou"]), (4, 1, 1))
        self.assertAlmostEqual(portoes["fix-noop"]["taxa"], 1 / 3)
        self.assertEqual(portoes["em-dash"]["reprovou"], 0)
        _, texto = self.cli("top")
        self.assertIn("fix-noop", texto)
        self.assertIn("33%", texto)
        _, todos = self.cli("top", "--all-projects", "--json")
        em_dash = [p for p in json.loads(todos)["portoes"] if p["portao"] == "em-dash"][0]
        self.assertEqual((em_dash["rodadas"], em_dash["reprovou"]), (2, 1))

    def test_sem_portao_rodado_nao_inventa_linha(self):
        _, saida = self.cli("top", "--json")
        self.assertEqual(json.loads(saida)["portoes"], [])
