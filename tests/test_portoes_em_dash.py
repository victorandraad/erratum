"""Portao de travessao (regex + fix, zero modelo): corrige o travessao de prosa nos arquivos de
codigo tocados pelo diff, roda o comando de teste pra confirmar que a troca nao quebrou nada, e
commita. Se quebrar, reverte e reprova. O caractere e montado por `chr(0x2014)`: este arquivo
obedece a regra que testa.

Rodar: python3 -m unittest tests.test_portoes_em_dash
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from erratum import portoes

T = chr(0x2014)
_OFENSOR = re.compile(r"[^\W_]%s|%s[^\W_]|%s\x20|\x20%s" % (T, T, T, T), re.UNICODE)


class CorrigirTravessao(unittest.TestCase):
    def test_troca_prosa_colada_e_espacada_por_virgula(self):
        self.assertEqual(portoes.corrigir_travessao(f"palavra{T}palavra"), "palavra, palavra")
        self.assertEqual(portoes.corrigir_travessao(f"palavra {T} palavra"), "palavra, palavra")

    def test_nunca_usa_hifen(self):
        self.assertNotIn("-", portoes.corrigir_travessao(f"a {T} b"))

    def test_preserva_placeholder_isolado(self):
        self.assertEqual(portoes.corrigir_travessao(f"'{T}'"), f"'{T}'")
        self.assertEqual(portoes.corrigir_travessao(f"value ?? '{T}'"), f"value ?? '{T}'")

    def test_resultado_nao_tem_mais_ofensor(self):
        for src in [f"// isto {T} aquilo", f"$a = 1;{T}fim", f"linha {T}", f"{T} linha"]:
            self.assertFalse(_OFENSOR.search(portoes.corrigir_travessao(src)), src)

    def test_sem_travessao_e_no_op(self):
        self.assertEqual(portoes.corrigir_travessao("nada aqui"), "nada aqui")

    def test_o_modulo_nao_tem_o_caractere_literal(self):
        self.assertNotIn(T, Path(portoes.__file__).read_text(encoding="utf-8"))


class FakeRes:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def sh_com_runner(runner_rc, rodadas=None):
    """Deixa o git rodar de verdade, mas intercepta a rodada de testes (`acme-test`)."""
    def fake(cmd, **kw):
        if cmd and cmd[0] == "acme-test":
            if rodadas is not None:
                rodadas.append(cmd)
            return FakeRes(rc=runner_rc, out="" if runner_rc == 0 else "FAIL")
        return portoes.executar(cmd, **kw)
    return fake


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


TESTE = "<?php\nclass MoneyTest { public function test_ok() { return true; } }\n"
COM_PROSA = f"<?php\n// preco {T} em centavos\nclass Money {{}}\n"


class PortaoEmDash(unittest.TestCase):
    def _repo(self, tmp, prod_do_dev, toca_teste=False):
        run(["git", "init", "-q"], tmp)
        run(["git", "config", "user.email", "dev@acme.test"], tmp)
        run(["git", "config", "user.name", "dev"], tmp)
        os.makedirs(os.path.join(tmp, "app"))
        os.makedirs(os.path.join(tmp, "tests"))
        with open(os.path.join(tmp, "app", "Money.php"), "w", encoding="utf-8") as f:
            f.write("<?php\nclass Money {}\n")
        with open(os.path.join(tmp, "tests", "MoneyTest.php"), "w", encoding="utf-8") as f:
            f.write(TESTE)
        run(["git", "add", "-A"], tmp)
        run(["git", "commit", "-q", "-m", "base"], tmp)
        base = run(["git", "rev-parse", "HEAD"], tmp).strip()
        with open(os.path.join(tmp, "app", "Money.php"), "w", encoding="utf-8") as f:
            f.write(prod_do_dev)
        if toca_teste:
            with open(os.path.join(tmp, "tests", "MoneyTest.php"), "a", encoding="utf-8") as f:
                f.write("// toca o escopo\n")
        run(["git", "commit", "-aq", "-m", "dev"], tmp)
        return base

    def _ler(self, tmp):
        return Path(tmp, "app", "Money.php").read_text(encoding="utf-8")

    def _roda(self, tmp, base, runner_rc=0, cmds=("acme-test {testes}",), rodadas=None, **kw):
        diff = portoes.DiffDoDev(tmp, base, sh=sh_com_runner(runner_rc, rodadas))
        return portoes.PortaoEmDash(diff, comandos_de_teste=list(cmds), **kw).rodar()

    def test_corrige_travessao_de_prosa_e_commita(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._repo(tmp, COM_PROSA, toca_teste=True)
            rodadas, visto = [], []
            r = self._roda(tmp, base, rodadas=rodadas, ao_decidir=lambda *a: visto.append(a))
            self.assertEqual(portoes.APROVOU, r.veredito)
            self.assertTrue(r.extra["corrigiu"])
            self.assertNotIn(T, self._ler(tmp))
            self.assertIn("preco, em centavos", self._ler(tmp))
            self.assertEqual("", run(["git", "status", "--porcelain"], tmp).strip())
            self.assertEqual([["acme-test", "tests/MoneyTest.php"]], rodadas)
            self.assertEqual(("em-dash", portoes.APROVOU), visto[0][:2])

    def test_reverte_quando_correcao_quebra_teste_do_escopo(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._repo(tmp, COM_PROSA, toca_teste=True)
            r = self._roda(tmp, base, runner_rc=1)
            self.assertTrue(r.reprovou)
            self.assertTrue(r.extra["corrigiu"])
            self.assertEqual(COM_PROSA, self._ler(tmp))
            self.assertEqual("", run(["git", "status", "--porcelain"], tmp).strip())

    def test_placeholder_isolado_nao_mexe(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = f"<?php\n$x = $v ?? '{T}';\nclass Money {{}}\n"
            base = self._repo(tmp, src)
            r = self._roda(tmp, base)
            self.assertEqual(portoes.APROVOU, r.veredito)
            self.assertFalse(r.extra["corrigiu"])
            self.assertEqual(src, self._ler(tmp))

    def test_diff_com_teste_mas_sem_comando_pula_sem_tocar(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._repo(tmp, COM_PROSA, toca_teste=True)
            r = self._roda(tmp, base, cmds=())
            self.assertTrue(r.pulou)
            self.assertIn("sem comando de teste", r.detalhe)
            self.assertEqual(COM_PROSA, self._ler(tmp))

    def test_diff_sem_teste_corrige_direto_mesmo_sem_comando(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._repo(tmp, COM_PROSA)
            r = self._roda(tmp, base, cmds=())
            self.assertEqual(portoes.APROVOU, r.veredito)
            self.assertTrue(r.extra["corrigiu"])
            self.assertNotIn(T, self._ler(tmp))


if __name__ == "__main__":
    unittest.main()
