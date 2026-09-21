"""A assinatura não pode rachar o mesmo erro em vários textos (um por branch, com e sem o prefixo
de quem reportou) nem juntar erros de causa diferente. Regras derivadas das 60 assinaturas de
maior volume de um ledger real; os casos aqui são genéricos."""
from __future__ import annotations

import unittest

from erratum.dominio import Assinatura


def sig(texto):
    return Assinatura(texto).valor


class TestBranchViraMarcador(unittest.TestCase):
    def test_prefixos_convencionais_de_branch(self):
        self.assertEqual(sig("push rejeitado em origin/main"), "push rejeitado em <branch>")
        self.assertEqual(sig("push rejeitado em feat/login-novo"), "push rejeitado em <branch>")
        self.assertEqual(sig("push rejeitado em fix/typo"), sig("push rejeitado em origin/hotfix/x-9"))

    def test_nome_entre_aspas_depois_de_palavra_de_git(self):
        self.assertEqual(sig("branch 'develop' divergiu"), sig('branch "principal" divergiu'))
        self.assertEqual(sig("rebase 'develop' parou"), "rebase '<branch>' parou")
        self.assertEqual(sig("checkout 'x' falhou; base \"y\" sumiu"),
                         "checkout '<branch>' falhou; base '<branch>' sumiu")

    def test_par_que_divergiu_entre_aspas(self):
        self.assertEqual(sig("'develop' divergiu e conflita com 'main'"),
                         sig("'principal' divergiu e conflita com 'develop'"))
        self.assertEqual(sig("'a' diverged and conflicts with 'b'"),
                         "'<branch>' diverged and conflicts with '<branch>'")
        self.assertNotEqual(sig("'develop' divergiu"), sig("'develop' sumiu"))

    def test_destino_do_merge_sem_aspas(self):
        a = sig("conflito ao mergear feat/tela-1 em develop; resolva à mão")
        b = sig("conflito ao mergear feat/outra no principal local; resolva à mão")
        self.assertEqual(a, "conflito ao mergear <branch> em <branch>; resolva à mão")
        self.assertEqual(sig("conflito ao mergear feat/tela-1 no develop local"),
                         sig("conflito ao mergear feat/outra no principal local"))
        self.assertIn("<branch> no <branch> local", b)
        self.assertEqual(sig("merge feat/a into develop failed"), sig("merge fix/b into main failed"))

    def test_verbo_de_integracao_com_artigo(self):
        self.assertEqual(sig("conflito ao integrar o develop atual na branch"),
                         sig("conflito ao integrar o feat/x atual na branch"))
        self.assertEqual(sig("não consegui mergear em develop: x"), sig("não consegui mergear em principal: x"))

    def test_between_x_and_branch(self):
        self.assertEqual(sig("no commits between develop and feat/a"),
                         sig("no commits between main and fix/b"))

    def test_base_depois_de_preposicao_conhecida(self):
        self.assertEqual(sig("dev não gerou commits à frente do develop"),
                         sig("dev não gerou commits à frente da principal"))
        self.assertEqual(sig("branch sem commits novos sobre o develop; nada pra mergear"),
                         sig("branch sem commits novos sobre a base; nada pra mergear"))
        self.assertEqual(sig("pr com conflito de merge com a develop"),
                         sig("pr com conflito de merge com o main"))


class TestPrefixoDeRelator(unittest.TestCase):
    def test_relator_some(self):
        puro = sig("orçamento do card estourado")
        self.assertEqual(sig("agente reportou falhou: falhou: orçamento do card estourado"), puro)
        self.assertEqual(sig("dev reportou: orçamento do card estourado"), puro)
        self.assertEqual(sig("qa reported failed: orçamento do card estourado"), puro)

    def test_falhou_no_meio_fica(self):
        self.assertEqual(sig("git push falhou: rejeitado"), "git push falhou: rejeitado")


class TestSlugShaValor(unittest.TestCase):
    def test_slug_entre_aspas(self):
        self.assertEqual(sig("parecida com a task já concluída 'erro-no-envio-de-email', se voltou"),
                         sig("parecida com a task já concluída 'webhook-que-nao-chegou', se voltou"))
        self.assertIn("'<slug>'", sig("parecida com a task 'a-b-c'"))

    def test_hash_de_commit(self):
        self.assertEqual(sig("cannot lock ref: is at 3d1a9f2a7e but expected 9a0acbbd1a"),
                         "cannot lock ref: is at <sha> but expected <sha>")
        self.assertEqual(sig("bad object 0123abc"), sig("bad object deadbeef0123deadbeef0123deadbeef01234567"))

    def test_palavra_hexadecimal_sem_digito_nao_e_hash(self):
        self.assertEqual(sig("decade defaced"), "decade defaced")

    def test_valor_monetario(self):
        self.assertEqual(sig("custo $12 passou do teto $1.50"), "custo <valor> passou do teto <valor>")
        self.assertEqual(sig("custo R$ 1.234,56 acima"), sig("custo US$3 acima"))


class TestNaoColide(unittest.TestCase):
    """Pares que DEVEM continuar distintos: causa diferente, texto parecido."""

    PARES = [
        ("conflito ao mergear feat/a em develop", "conflito ao integrar o develop atual na branch"),
        ("branch 'x' not found", "branch 'x' already exists"),
        ("merge conflict in a.py", "merge failed: not something we can merge"),
        ("bad object 0123abc", "cannot lock ref 0123abc"),
        ("dev reportou: timeout", "dev reportou: sem saída"),
        ("custo $12 passou do teto", "custo $12 abaixo do piso"),
        ("task 'a-b-c' duplicada", "task 'a-b-c' não encontrada"),
        ("dev não gerou commits à frente do develop", "branch sem commits novos sobre o develop"),
        ("push rejeitado em origin/main", "fetch falhou em origin/main"),
    ]

    def test_pares_distintos(self):
        for a, b in self.PARES:
            self.assertNotEqual(sig(a), sig(b), (a, b))

    def test_merge_conflict_nao_vira_branch(self):
        self.assertEqual(sig("merge conflict in a.py"), "merge conflict in a.py")

    def test_versao_da_regra_e_publica(self):
        self.assertGreaterEqual(Assinatura.VERSAO, 2)

    def test_renormalizar_assinatura_nova_e_estavel(self):
        for a, _ in self.PARES:
            self.assertEqual(sig(sig(a)), sig(a))


if __name__ == "__main__":
    unittest.main()
