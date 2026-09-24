"""Saída humana em inglês por padrão; ERRATUM_LANG=pt devolve o português. As chaves do --json
não mudam com o idioma."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from tests.apoio import CasoComLedger

ERRO = "Exit code 127 /tmp/w-1/bin/runner: No such file"


def _git(wt, *args):
    subprocess.run(["git", *args], cwd=wt, check=True, capture_output=True, text=True)


class _Idioma(CasoComLedger):
    lang = ""

    def setUp(self):
        super().setUp()
        env = {k: v for k, v in os.environ.items() if k != "ERRATUM_LANG"}
        if self.lang:
            env["ERRATUM_LANG"] = self.lang
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def _repo_limpo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wt = Path(tmp.name)
        _git(wt, "init", "-q")
        _git(wt, "config", "user.email", "dev@acme.test")
        _git(wt, "config", "user.name", "dev")
        (wt / "a.py").write_text("x = 1\n")
        _git(wt, "add", "a.py")
        _git(wt, "commit", "-q", "-m", "base")
        (wt / "a.py").write_text("x = 2\n")
        _git(wt, "commit", "-q", "-am", "muda")
        return wt


class TestInglesPorPadrao(_Idioma):
    def test_err_e_fix(self):
        _, saida = self.cli("err", ERRO)
        self.assertIn("error #1 recorded [acme] signature: exit code N /PATH: no such file", saida)
        self.assertIn("no confident match in the ledger", saida)
        _, saida = self.cli("fix", "1", "run worktree prep before the runner", "--ref", "abc123",
                            "--test", "test_prep")
        self.assertIn("fix #1 recorded [acme] for: exit code N /PATH: no such file", saida)
        _, saida = self.cli("err", "Exit code 1 /tmp/w-2/bin/runner: No such file")
        self.assertIn("  known fix: run worktree prep before the runner "
                      "[ref: abc123, test: test_prep]\n", saida)
        self.assertNotIn("correção", saida)

    def test_find(self):
        self.assertEqual(self.cli("find", "nada disso")[1].strip(), "no confident match in the ledger")
        self.cli("err", ERRO)
        self.cli("fix", "1", "run worktree prep", "--test", "test_prep")
        _, saida = self.cli("find", ERRO)
        self.assertIn("   fix: run worktree prep [test: test_prep]", saida)
        _, saida = self.cli("find", "bin/runner no such file")
        self.assertIn("1. [fts] maybe (", saida)

    def test_top(self):
        self.assertEqual(self.cli("top")[1].strip(), "nothing repeating")
        self.ledger.registrar_portao("em-dash", "aprovou", "", "acme")
        self.ledger.registrar_portao("em-dash", "pulou", "", "acme")
        _, saida = self.cli("top")
        self.assertIn("gate em-dash: 0/1 failed (0%), 1 skipped", saida)

    def test_gate(self):
        naorepo = tempfile.TemporaryDirectory()
        self.addCleanup(naorepo.cleanup)
        codigo, saida = self.cli("gate", "em-dash", "--base", "HEAD", "--worktree", naorepo.name)
        self.assertEqual((codigo, saida.strip()), (2, "worktree is not a git repository"))
        wt = self._repo_limpo()
        codigo, saida = self.cli("gate", "em-dash", "--base", "HEAD~1", "--worktree", str(wt))
        self.assertEqual(codigo, 0, saida)
        self.assertTrue(saida.startswith("em-dash: passed "), saida)
        self.assertNotIn("travessão", saida)

    def test_json_mantem_chaves_e_valores_de_dado(self):
        _, saida = self.cli("err", ERRO, "--json")
        self.assertEqual(set(json.loads(saida)), {"erro", "pistas", "veredito", "confianca"})
        wt = self._repo_limpo()
        _, saida = self.cli("gate", "em-dash", "--base", "HEAD~1", "--worktree", str(wt), "--json")
        dado = json.loads(saida)
        self.assertEqual(set(dado), {"portoes", "reprovou"})
        self.assertEqual(dado["portoes"][0]["veredito"], "aprovou")


class TestPortuguesComErratumLang(_Idioma):
    lang = "pt"

    def test_err_fix_find_top_gate(self):
        _, saida = self.cli("err", ERRO)
        self.assertIn("erro #1 registrado [acme] assinatura: exit code N /PATH: no such file", saida)
        self.assertIn("nada parecido com confiança no ledger", saida)
        _, saida = self.cli("fix", "1", "prep", "--test", "test_prep")
        self.assertIn("correção #1 registrada [acme]", saida)
        _, saida = self.cli("err", ERRO)
        self.assertIn("  correção conhecida: prep [teste: test_prep]", saida)
        _, saida = self.cli("find", ERRO)
        self.assertIn("   correção: prep [teste: test_prep]", saida)
        self.ledger.registrar_portao("em-dash", "pulou", "", "acme")
        self.assertIn("portão em-dash: 0/0 reprovou (0%), 1 pulou", self.cli("top")[1])
        wt = self._repo_limpo()
        _, saida = self.cli("gate", "em-dash", "--base", "HEAD~1", "--worktree", str(wt))
        self.assertTrue(saida.startswith("em-dash: aprovou nenhum travessão de prosa"), saida)


class TestHookCheckCmd(_Idioma):
    def _aviso(self):
        import runpy
        hook = runpy.run_path(str(Path(__file__).parent.parent / "hooks" / "pretooluse-check-cmd.py"))
        return hook["_aviso_de"]({"receita": "esperar-ci", "comando": "bin/ci-espera", "perigo": "bg"})

    def test_ingles_por_padrao(self):
        self.assertEqual(self._aviso(), "use recipe esperar-ci: bin/ci-espera\ndanger: bg\n")

    def test_pt(self):
        os.environ["ERRATUM_LANG"] = "pt"
        self.assertEqual(self._aviso(), "use a receita esperar-ci: bin/ci-espera\nperigo: bg\n")
