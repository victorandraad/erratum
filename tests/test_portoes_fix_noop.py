"""Portao anti-fix-no-op: reverte so o codigo de producao da branch e roda o comando de teste.
Continua verde = o fix nao prova nada (reprova); falha = regressao real (aprova). Restaura sempre.

Duas camadas: `sh` falso (ordem dos comandos git, restauracao em excecao) e repo git de verdade
com `python -m unittest` como comando de teste generico (o portao dispara de fato).

Rodar: python3 -m unittest tests.test_portoes_fix_noop
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from erratum import portoes


class FakeRes:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


DIFF_PROD_TEST = "app/Money.php\ntests/Feature/MoneyTest.php\n"
ORIG_SHA = "origsha123"
CMDS = ["acme-test {testes}"]


def make_fake(*, runner=None, cat_file_rc=0, rec=None, diff=DIFF_PROD_TEST):
    """`sh` falso: responde por conteudo do cmd e grava tudo em `rec`. `runner` = FakeRes/excecao
    da rodada de testes."""
    def fake(cmd, **kw):
        if rec is not None:
            rec.append(cmd)
        if cmd[:2] == ["git", "diff"]:
            return FakeRes(out=diff)
        if cmd[:2] == ["git", "rev-parse"]:
            return FakeRes(out=ORIG_SHA + "\n")
        if cmd[:2] == ["git", "cat-file"]:
            return FakeRes(rc=cat_file_rc)
        if cmd[0] == "git":
            return FakeRes(rc=0)
        if isinstance(runner, Exception):
            raise runner
        return runner if runner is not None else FakeRes(rc=0)
    return fake


def roda(fake, settings=None, **kw):
    diff = portoes.DiffDoDev("/tmp/wt", "origin/main", sh=fake)
    return portoes.PortaoFixNoop(diff, {"test_cmds": CMDS} if settings is None else settings,
                                 **kw).rodar()


class ComShFalso(unittest.TestCase):
    def test_fix_real_aprova_e_restaura(self):
        rec = []
        r = roda(make_fake(runner=FakeRes(rc=1, out="FAIL"), rec=rec))
        self.assertEqual(portoes.APROVOU, r.veredito)
        self.assertTrue(any(c[:3] == ["git", "checkout", ORIG_SHA] for c in rec))
        self.assertIn(["acme-test", "tests/Feature/MoneyTest.php"], rec)

    def test_fix_noop_reprova(self):
        r = roda(make_fake(runner=FakeRes(rc=0, out="OK")))
        self.assertTrue(r.reprovou)
        self.assertIn("continuam verdes", r.motivo)

    def test_producao_nova_e_removida_em_vez_de_revertida(self):
        rec = []
        roda(make_fake(runner=FakeRes(rc=1), cat_file_rc=1, rec=rec))
        self.assertTrue(any(c[:2] == ["git", "rm"] for c in rec))

    def test_restaura_em_excecao(self):
        rec = []
        r = roda(make_fake(runner=RuntimeError("boom"), rec=rec))  # nao propaga
        self.assertTrue(r.pulou)
        self.assertIn("boom", r.detalhe)
        self.assertTrue(any(c[:3] == ["git", "checkout", ORIG_SHA] for c in rec))

    def test_pula_sem_teste_ou_sem_prod(self):
        for diff in ("tests/Feature/MoneyTest.php\n", "app/Money.php\n"):
            rec = []
            r = roda(make_fake(diff=diff, rec=rec))
            self.assertTrue(r.pulou, diff)
            self.assertEqual(1, len(rec), "so o git diff rodou; nada foi revertido")

    def test_sem_comando_de_teste_pula_com_motivo_e_nao_toca_em_nada(self):
        rec, visto = [], []
        r = roda(make_fake(rec=rec), settings={}, ao_decidir=lambda *a: visto.append(a))
        self.assertTrue(r.pulou)
        self.assertIn("sem comando de teste", r.detalhe)
        self.assertEqual([], rec)
        self.assertEqual("fix-noop", visto[0][0])
        self.assertEqual(portoes.PULOU, visto[0][1])

    def test_repo_com_test_cmds_proprio_nao_e_mais_recusado(self):
        r = roda(make_fake(runner=FakeRes(rc=1)), settings={"test_cmds": ["pnpm test"]})
        self.assertEqual(portoes.APROVOU, r.veredito)

    def test_flag_desligada(self):
        rec = []
        r = roda(make_fake(rec=rec), settings={"fix_noop_gate": False, "test_cmds": CMDS})
        self.assertTrue(r.pulou)
        self.assertEqual([], rec)


CALC_BUGADO = "def soma(a, b):\n    return a - b\n"
CALC_CERTO = "def soma(a, b):\n    return a + b\n"
TESTE_QUE_PROVA = ("import unittest\nfrom acme import calc\n\n\nclass T(unittest.TestCase):\n"
                   "    def test_soma(self):\n        self.assertEqual(5, calc.soma(2, 3))\n")
TESTE_QUE_SEMPRE_PASSA = ("import unittest\nfrom acme import calc\n\n\nclass T(unittest.TestCase):\n"
                          "    def test_soma(self):\n        self.assertTrue(callable(calc.soma))\n")
# -B: sem .pyc, senao o fonte revertido e o restaurado podem dividir o mesmo cache.
CMD_UNITTEST = [[sys.executable, "-B", "-m", "unittest", "{testes}"]]


def git(wt, *args):
    return subprocess.run(["git", *args], cwd=wt, check=True, capture_output=True,
                          text=True).stdout.strip()


class ComRepoDeVerdade(unittest.TestCase):
    """O portao dispara de verdade: git real, `python -m unittest` real, zero mock."""

    def _repo(self, tmp, calc_do_dev, teste_do_dev):
        wt = Path(tmp)
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
        (wt / "acme" / "calc.py").write_text(calc_do_dev)
        (wt / "tests" / "test_calc.py").write_text(teste_do_dev)
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "fix")
        return wt, base

    def _roda(self, wt, base, visto):
        return portoes.PortaoFixNoop(portoes.DiffDoDev(wt, base), comandos_de_teste=CMD_UNITTEST,
                                     ao_decidir=lambda *a: visto.append(a)).rodar()

    def test_fix_real_aprova_e_deixa_o_repo_como_estava(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = self._repo(tmp, CALC_CERTO, TESTE_QUE_PROVA)
            visto = []
            r = self._roda(wt, base, visto)
            self.assertEqual(portoes.APROVOU, r.veredito, r.detalhe)
            self.assertEqual(CALC_CERTO, (wt / "acme" / "calc.py").read_text())
            self.assertEqual("", git(wt, "status", "--porcelain"))
            self.assertEqual(("fix-noop", portoes.APROVOU), visto[0][:2])

    def test_fix_noop_reprova(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = self._repo(tmp, CALC_BUGADO + "# agora vai\n", TESTE_QUE_SEMPRE_PASSA)
            visto = []
            r = self._roda(wt, base, visto)
            self.assertTrue(r.reprovou, r.detalhe)
            self.assertEqual("", git(wt, "status", "--porcelain"))
            self.assertEqual(("fix-noop", portoes.REPROVOU), visto[0][:2])

    def test_producao_nova_some_durante_o_teste_e_volta_depois(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt, base = self._repo(tmp, CALC_BUGADO, "import unittest\nfrom acme import novo\n\n\n"
                                  "class T(unittest.TestCase):\n    def test_x(self):\n"
                                  "        self.assertEqual(1, novo.um())\n")
            (wt / "acme" / "novo.py").write_text("def um():\n    return 1\n")
            git(wt, "add", "-A")
            git(wt, "commit", "-q", "-m", "novo")
            r = self._roda(wt, base, [])
            self.assertEqual(portoes.APROVOU, r.veredito, r.detalhe)
            self.assertTrue((wt / "acme" / "novo.py").exists())
            self.assertEqual("", git(wt, "status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
