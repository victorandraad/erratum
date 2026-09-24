"""Assinatura v3: dígito colado a letra é identidade (TS2322, E404) e log bruto (pytest,
traceback, tsc, npm) é focado na linha do erro antes do corte de 120. Prosa de agente segue v2."""
from __future__ import annotations

import unittest

from erratum.dominio import Assinatura

CABECALHO = (
    "============================= test session starts ==============================\n"
    "platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0\n"
    "rootdir: /home/dev/loja\n"
    "collected 1 item\n\n"
    "tests/test_calc.py F                                                     [100%]\n\n"
    "=================================== FAILURES ===================================\n"
    "__________________________________ test_soma ___________________________________\n\n"
    "    def test_soma():\n"
)


class TestDigitosColadosALetra(unittest.TestCase):
    def test_versao_3(self):
        self.assertEqual(Assinatura.VERSAO, 3)

    def test_codigos_ts_distintos_nao_colidem(self):
        a = Assinatura("index.ts(1,7): error TS2322: Type 'string' is not assignable")
        b = Assinatura("index.ts(1,7): error TS2339: Type 'string' is not assignable")
        self.assertNotEqual(a, b)
        self.assertIn("ts2322", a.valor)

    def test_e404_preservado_e_numero_solto_vira_n(self):
        self.assertEqual(Assinatura("npm error code E404").valor, "npm error code e404")
        self.assertEqual(Assinatura("timeout 30s na rodada 12").valor, "timeout Ns na rodada N")
        self.assertEqual(Assinatura("index.ts(1,7)").valor, "index.ts(N,N)")


class TestFocoEmLogBruto(unittest.TestCase):
    def test_pytest_foca_na_linha_E(self):
        a = Assinatura(CABECALHO + ">       assert soma(2, 3) == 5\nE       assert -1 == 5\n")
        b = Assinatura(CABECALHO + ">       json.loads(x)\nE       json.decoder.JSONDecodeError: x\n")
        self.assertNotEqual(a, b)
        self.assertTrue(a.valor.startswith("e assert -N == N"), a.valor)

    def test_traceback_foca_na_excecao(self):
        texto = (
            "rodando a suite inteira do projeto com muita saida antes do erro de verdade " * 3
            + "\nTraceback (most recent call last):\n"
            '  File "/x/a.py", line 1, in <module>\n'
            "    d['chave']\n"
            "KeyError: 'chave'\n"
        )
        self.assertTrue(Assinatura(texto).valor.startswith("keyerror: 'chave'"))

    def test_traceback_encadeado_foca_na_ultima_excecao(self):
        texto = (
            "Traceback (most recent call last):\n  File \"a.py\", line 1\nKeyError: 'x'\n\n"
            "During handling of the above exception, another exception occurred:\n\n"
            "Traceback (most recent call last):\n  File \"a.py\", line 3\nValueError: final\n"
        )
        self.assertTrue(Assinatura(texto).valor.startswith("valueerror: final"))

    def test_tsc_enterrado_depois_do_npm_run(self):
        texto = "> app@1.0.0 build\n> tsc -p . --pretty false\n" * 3 + "src/a.ts(3,1): error TS2304: Cannot find name 'x'.\n"
        self.assertTrue(Assinatura(texto).valor.startswith("src/PATH: error ts2304"))


class TestProsaDeAgenteSegueV2(unittest.TestCase):
    PROSA = (
        "worker reportou falhou: o teste de integracao do checkout quebrou porque o mock do "
        "gateway nao devolve o campo status e o agente tentou de novo sem mudar nada no codigo"
    )

    def test_prosa_nao_colapsa_no_sufixo_falhou(self):
        # medido no ledger real: heuristica sem limite jogou 480 prosas em "falhou"
        a = Assinatura(self.PROSA + "\n\nFALHOU")
        b = Assinatura(self.PROSA.replace("checkout", "carrinho") + "\n\nFALHOU")
        self.assertNotEqual(a, b)
        self.assertTrue(a.valor.startswith("o teste de integracao do checkout"))
        self.assertEqual(len(a.valor), 120)

    def test_prosa_que_cita_erro_nao_e_reordenada(self):
        texto = "agente reportou: build falhou\n\ncomo sempre, erro de tipo no front"
        self.assertEqual(Assinatura(texto).valor, "build falhou como sempre, erro de tipo no front")


if __name__ == "__main__":
    unittest.main()
