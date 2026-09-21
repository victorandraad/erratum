"""`erratum gate --staged` e o hooks/pre-commit: o diff julgado é o índice (`git diff --cached`),
só com portões que não fazem checkout nem commit. O hook barra stub neutro, deixa passar commit
normal e cada rodada vai pra `gate_runs`."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from erratum.banco import Banco
from tests.apoio import CasoComLedger
from tests.test_portoes_stub_neutro import PY_STUB

RAIZ = Path(__file__).resolve().parent.parent
LIMPO = "def soma(a, b):\n    return a + b\n"
COM_TRAVESSAO = "# soma dois numeros %s com cuidado\ndef soma(a, b):\n    return a + b\n" % chr(0x2014)


def git(wt, *args, check=True, env=None):
    return subprocess.run(["git", *args], cwd=wt, check=check, capture_output=True, text=True, env=env)


class CasoComRepo(CasoComLedger):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wt = Path(tmp.name)
        git(self.wt, "init", "-q")
        git(self.wt, "config", "user.email", "dev@acme.test")
        git(self.wt, "config", "user.name", "dev")
        (self.wt / "acme").mkdir()
        (self.wt / "acme" / "__init__.py").write_text("")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "base")

    def _stage(self, rel, corpo):
        (self.wt / rel).write_text(corpo, encoding="utf-8")
        git(self.wt, "add", rel)

    def _gate_runs(self, banco=None):
        return [(l["gate"], l["verdict"]) for l in (banco or self.banco).consultar(
            "SELECT gate, verdict FROM gate_runs ORDER BY id")]


class TestGateStaged(CasoComRepo):
    def test_stub_neutro_em_stage_reprova_sem_exigir_base_nem_worktree_limpo(self):
        self._stage("acme/provider.py", PY_STUB)
        (self.wt / "acme" / "__init__.py").write_text("# edicao pendente fora do stage\n")
        codigo, saida = self.cli("gate", "em-dash,stub-neutro", "--staged", "--worktree", str(self.wt))
        self.assertEqual(codigo, 1, saida)
        self.assertEqual(self._gate_runs(), [("em-dash", "aprovou"), ("stub-neutro", "reprovou")])

    def test_so_julga_o_que_esta_em_stage(self):
        (self.wt / "acme" / "provider.py").write_text(PY_STUB)  # nao rastreado, fora do stage
        self._stage("acme/calc.py", LIMPO)
        codigo, saida = self.cli("gate", "em-dash,stub-neutro", "--staged", "--worktree", str(self.wt))
        self.assertEqual(codigo, 0, saida)

    def test_le_o_conteudo_do_indice_e_nao_o_do_disco(self):
        self._stage("acme/provider.py", PY_STUB)
        (self.wt / "acme" / "provider.py").write_text(LIMPO)  # disco limpo, indice com o stub
        self.assertEqual(self.cli("gate", "stub-neutro", "--staged", "--worktree", str(self.wt))[0], 1)

    def test_em_dash_em_stage_so_detecta_nao_corrige_nem_commita(self):
        self._stage("acme/calc.py", COM_TRAVESSAO)
        head = git(self.wt, "rev-parse", "HEAD").stdout
        codigo, saida = self.cli("gate", "em-dash", "--staged", "--worktree", str(self.wt))
        self.assertEqual(codigo, 1, saida)
        self.assertIn("acme/calc.py", saida)
        self.assertEqual((self.wt / "acme" / "calc.py").read_text(encoding="utf-8"), COM_TRAVESSAO)
        self.assertEqual(git(self.wt, "rev-parse", "HEAD").stdout, head)
        self.assertEqual(git(self.wt, "diff", "--cached", "--name-only").stdout.strip(), "acme/calc.py")

    def test_fix_noop_com_staged_e_uso_errado(self):
        self._stage("acme/calc.py", LIMPO)
        self.assertEqual(self.cli("gate", "fix-noop", "--staged", "--worktree", str(self.wt))[0], 2)
        self.assertEqual(self._gate_runs(), [])

    def test_sem_staged_continua_exigindo_base(self):
        self.assertEqual(self.cli("gate", "em-dash", "--worktree", str(self.wt))[0], 2)

    def test_stage_vazio_aprova(self):
        self.assertEqual(self.cli("gate", "em-dash,stub-neutro", "--staged", "--worktree", str(self.wt))[0], 0)


class TestHookPreCommit(CasoComRepo):
    def setUp(self):
        super().setUp()
        hook = self.wt / ".git" / "hooks" / "pre-commit"
        hook.write_text((RAIZ / "hooks" / "pre-commit").read_text(encoding="utf-8"), encoding="utf-8")
        hook.chmod(0o755)
        self.db = Path(self._tmp.name) / "hook.db"
        self.env = dict(os.environ, ERRATUM_DB=str(self.db), PYTHONPATH=str(RAIZ),
                        ERRATUM_PYTHON=sys.executable)
        self.env.pop("ERRATUM_SEARCH_CMD", None)

    def test_hook_e_posix_sh(self):
        self.assertTrue((RAIZ / "hooks" / "pre-commit").read_text().startswith("#!/bin/sh\n"))

    def test_commit_com_stub_e_barrado_e_commit_normal_passa(self):
        self._stage("acme/provider.py", PY_STUB)
        barrado = git(self.wt, "commit", "-q", "-m", "stub", check=False, env=self.env)
        self.assertNotEqual(barrado.returncode, 0)
        self.assertIn("stub-neutro", barrado.stdout + barrado.stderr)
        git(self.wt, "reset", "-q", "HEAD", "--", "acme/provider.py")
        (self.wt / "acme" / "provider.py").unlink()
        self._stage("acme/calc.py", LIMPO)
        ok = git(self.wt, "commit", "-q", "-m", "normal", check=False, env=self.env)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        with Banco(self.db) as banco:
            self.assertEqual(self._gate_runs(banco), [
                ("em-dash", "aprovou"), ("stub-neutro", "reprovou"),
                ("em-dash", "aprovou"), ("stub-neutro", "aprovou")])

    def test_sem_erratum_instalado_o_hook_nao_bloqueia(self):
        self._stage("acme/calc.py", LIMPO)
        env = dict(self.env, ERRATUM_PYTHON="/nao/existe/python")
        ok = git(self.wt, "commit", "-q", "-m", "normal", check=False, env=env)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
