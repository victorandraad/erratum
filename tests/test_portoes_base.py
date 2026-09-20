"""As pecas comuns dos portoes: `DiffDoDev`, `Resultado`, e o contrato de `Portao.rodar`
(veredito enumerado, flag por repo, telemetria por `ao_decidir`, nada levanta pro chamador).

Rodar: python3 -m unittest tests.test_portoes_base
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from erratum import portoes


class FakeRes:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def diff_fake(saida="app/Money.php\ntests/MoneyTest.php\n", rc_teste=0):
    chamadas = []

    def sh(cmd, **kw):
        chamadas.append(cmd)
        if cmd[0] != "git":
            return FakeRes(rc=rc_teste)
        return FakeRes(out=saida)
    return portoes.DiffDoDev("/tmp/wt", "origin/main", sh=sh), chamadas


class DiffDoDev(unittest.TestCase):
    def test_separa_teste_de_producao(self):
        d, _ = diff_fake()
        self.assertEqual(["tests/MoneyTest.php"], d.testes())
        self.assertEqual(["app/Money.php"], d.producao())

    def test_reconhece_teste_python_fora_de_tests(self):
        d, _ = diff_fake("acme/calc.py\nacme/test_calc.py\nacme/calc_test.py\n")
        self.assertEqual(["acme/calc.py"], d.producao())

    def test_pergunta_o_diff_uma_vez_so(self):
        d, chamadas = diff_fake()
        d.arquivos(), d.testes(), d.producao()
        self.assertEqual(1, len(chamadas))

    def test_novos_ou_modificados_usa_as_flags_de_rename(self):
        d, chamadas = diff_fake()
        d.arquivos(novos_ou_modificados=True)
        self.assertIn("--diff-filter=AM", chamadas[0])
        self.assertIn("-M", chamadas[0])

    def test_sh_padrao_quando_ninguem_injeta(self):
        self.assertIs(portoes.executar, portoes.DiffDoDev("/tmp/wt", "ref").sh)


class ComandoDeTesteInjetado(unittest.TestCase):
    def test_marcador_vira_os_testes_do_escopo(self):
        d, chamadas = diff_fake()
        d.rodar_testes(["acme-test --filtro {testes}"], ["tests/MoneyTest.php"])
        self.assertEqual(["acme-test", "--filtro", "tests/MoneyTest.php"], chamadas[-1])

    def test_sem_marcador_roda_como_veio(self):
        d, chamadas = diff_fake()
        d.rodar_testes([["make", "test"]], ["tests/MoneyTest.php"])
        self.assertEqual(["make", "test"], chamadas[-1])

    def test_para_no_primeiro_vermelho(self):
        d, chamadas = diff_fake(rc_teste=1)
        r = d.rodar_testes(["lint", "suite"])
        self.assertEqual(1, r.returncode)
        self.assertEqual([["lint"]], chamadas)

    def test_construtor_ganha_de_settings_e_string_vira_lista(self):
        p = portoes.PortaoFixNoop(None, {"test_cmds": ["a"]}, comandos_de_teste="b")
        self.assertEqual(["b"], p.comandos_de_teste)
        self.assertEqual(["a"], portoes.PortaoFixNoop(None, {"test_cmds": ["a"]}).comandos_de_teste)


class VereditoEnumerado(unittest.TestCase):
    def test_pulou_quando_a_flag_do_repo_esta_off(self):
        r = portoes.PortaoStubNeutro(None, {"stub_neutro_gate": False}).rodar()
        self.assertEqual(portoes.PULOU, r.veredito)
        self.assertFalse(r.rodou)

    def test_reprovou_carrega_motivo(self):
        r = portoes.Resultado(portoes.REPROVOU, "o fix nao prova nada")
        self.assertTrue(r.reprovou)
        self.assertIn("nao prova nada", r.motivo)
        self.assertEqual(r.motivo, r.detalhe)

    def test_registro_de_portoes_pela_cli(self):
        self.assertEqual({"em-dash", "stub-neutro", "fix-noop"}, set(portoes.PORTOES))

    def test_excecao_em_julgar_vira_pulou_com_log(self):
        class Quebrado(portoes.Portao):
            nome = "quebrado"

            def _julgar(self):
                raise RuntimeError("boom")
        logs = []
        r = Quebrado(None, log=logs.append).rodar()
        self.assertTrue(r.pulou)
        self.assertIn("boom", r.detalhe)
        self.assertIn("quebrado", logs[0])


class Telemetria(unittest.TestCase):
    """`ao_decidir(nome, veredito, detalhe)` dispara em TODO veredito: e o que permite contar."""

    def _portao(self, veredito, ao_decidir, log=None):
        class Fixo(portoes.Portao):
            nome = "fixo"

            def _julgar(self):
                return portoes.Resultado(veredito, detalhe="porque sim")
        return Fixo(None, ao_decidir=ao_decidir, log=log)

    def test_chamado_em_aprovou_reprovou_e_pulou(self):
        for veredito in (portoes.APROVOU, portoes.REPROVOU, portoes.PULOU):
            visto = []
            self._portao(veredito, lambda *a: visto.append(a)).rodar()
            self.assertEqual([("fixo", veredito, "porque sim")], visto)

    def test_chamado_quando_a_flag_desligada_pula(self):
        visto = []
        portoes.PortaoStubNeutro(None, {"stub_neutro_gate": False},
                                 ao_decidir=lambda *a: visto.append(a)).rodar()
        self.assertEqual([("stub-neutro", portoes.PULOU, "flag desligada no repo")], visto)

    def test_callback_que_lanca_nao_derruba_nem_muda_o_veredito(self):
        def quebra(*a):
            raise ValueError("ledger fora do ar")
        logs = []
        r = self._portao(portoes.REPROVOU, quebra, log=logs.append).rodar()
        self.assertTrue(r.reprovou)
        self.assertIn("ledger fora do ar", logs[0])

    def test_sem_callback_nao_faz_nada(self):
        self.assertEqual(portoes.APROVOU, self._portao(portoes.APROVOU, None).rodar().veredito)


if __name__ == "__main__":
    unittest.main()
