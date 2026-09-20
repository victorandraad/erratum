from __future__ import annotations

import unittest

from erratum.dominio import Assinatura


class TestAssinatura(unittest.TestCase):
    def test_colapsa_numeros_e_caminhos_volateis(self):
        a = Assinatura("Exit code 127\n/tmp/work/x-47062/vendor/bin/runner: No such file")
        b = Assinatura("Exit code 1\n/tmp/work/y-99/vendor/bin/runner: No such file")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.valor, "exit code N /PATH: no such file")

    def test_texto_vazio_tem_assinatura_fixa(self):
        self.assertEqual(Assinatura("").valor, "(sem texto)")
        self.assertEqual(Assinatura(None).valor, "(sem texto)")

    def test_contador_de_rodada_nao_racha_o_padrao(self):
        self.assertEqual(Assinatura("QA reprovou (rodada 1/2) o diff"),
                         Assinatura("QA reprovou (rodada 2) o diff"))
        self.assertNotIn("rodada", Assinatura("QA reprovou (rodada 1/2)").valor)

    def test_corta_em_120(self):
        self.assertEqual(len(Assinatura("palavra " * 100).valor), 120)

    def test_ja_normalizada_nao_renormaliza(self):
        # renormalizar um valor cortado no meio de "/PATH" mudaria a chave de agrupamento
        self.assertEqual(Assinatura.ja_normalizada("erro em /PAT").valor, "erro em /PAT")
        self.assertEqual(str(Assinatura("Erro 5")), "erro N")

    def test_difere_de_outro_tipo(self):
        self.assertNotEqual(Assinatura("x"), "x")


if __name__ == "__main__":
    unittest.main()
