from __future__ import annotations

import json

from tests.apoio import CasoComLedger


class TestFind(CasoComLedger):
    def test_erro_cru_de_runner_casa_com_assinatura_normalizada(self):
        antigo, _ = self.ledger.registrar_erro(
            "Exit code 127\n/tmp/work/x-47062/vendor/bin/runner: No such file or directory", "acme")
        self.ledger.registrar_correcao(antigo.id, "instalar dependencias no worktree", "acme")
        # texto cru diferente (sem exit code, com sufixo): assinatura NAO bate, quem acha e o FTS
        achados = self.ledger.buscar("sh: 1: vendor/bin/runner: not found, no such file")
        self.assertEqual(achados[0].origem, "fts")
        self.assertEqual(achados[0].assinatura, antigo.assinatura)
        self.assertEqual(achados[0].correcoes[0].nota, "instalar dependencias no worktree")

    def test_push_rejeitado_casa_com_motivo_em_portugues(self):
        self.ledger.registrar_erro(
            "push da resolução falhou: ! [rejected] main -> main (fetch first), use git pull", "acme")
        achados = self.ledger.buscar("error: push rejected, updates were rejected; use git pull first")
        self.assertTrue(achados[0].assinatura.startswith("push da resolução falhou"))

    def test_sem_acento_casa_com_acentuado(self):
        self.ledger.registrar_erro("orçamento do card estourado ($40.25 ≥ teto $40.00)", "acme")
        achados = self.ledger.buscar("orcamento estourou teto")
        self.assertEqual(len(achados), 1)
        self.assertIn("orçamento do card estourado", achados[0].assinatura)

    def test_match_exato_tem_prioridade(self):
        self.ledger.registrar_erro("timeout ao compilar assets do painel em 30s", "acme")
        # vizinho com MAIS tokens em comum com a consulta do que o exato tem de raro
        self.ledger.registrar_erro("timeout timeout compilar compilar assets assets painel painel", "acme")
        achados = self.ledger.buscar("Timeout ao compilar assets do painel em 45s")
        self.assertEqual(achados[0].origem, "assinatura")
        self.assertEqual(achados[0].assinatura, "timeout ao compilar assets do painel em Ns")
        # a mesma assinatura nao volta duas vezes (uma pelo exato, outra pelo FTS)
        assinaturas = [a.assinatura for a in achados]
        self.assertEqual(len(assinaturas), len(set(assinaturas)))
        self.assertEqual(len(achados), 2)

    def test_ocorrencias_repetidas_viram_um_achado_so(self):
        for n in (1, 2, 3):
            self.ledger.registrar_erro("falha de rede ao baixar pacote %d" % n, "acme")
        self.assertEqual(len(self.ledger.buscar("rede pacote")), 1)

    def test_respeita_o_limite(self):
        for nome in ("alfa", "beta", "gama", "delta"):
            self.ledger.registrar_erro("falha comum no modulo %s" % nome, "acme")
        self.assertEqual(len(self.ledger.buscar("falha comum", n=2)), 2)

    def test_sem_achado_devolve_vazio(self):
        self.ledger.registrar_erro("falha de rede", "acme")
        self.assertEqual(self.ledger.buscar("segmentation fault"), [])
        self.assertEqual(self.ledger.buscar(""), [])
        self.assertEqual(self.ledger.buscar('" OR ( * ) --'), [])

    def test_consulta_usa_no_maximo_12_tokens_de_3_letras(self):
        from erratum.busca import BuscaFTS
        consulta = BuscaFTS.consulta("ab cd " + " ".join("tok%02d" % i for i in range(20)) + " tok00")
        self.assertEqual(consulta.count(" OR "), 11)
        self.assertTrue(consulta.startswith('"tok00" OR "tok01"'))
        self.assertNotIn('"ab"', consulta)

    def test_err_traz_pista_automatica_pelo_fts(self):
        self.ledger.registrar_correcao("orçamento do card estourado ($40.25 ≥ teto $40.00)",
                                       "quebrar o card em dois", "acme")
        _, pistas = self.ledger.registrar_erro("orcamento estourou o teto de novo", "acme")
        self.assertEqual(pistas[0].correcoes[0].nota, "quebrar o card em dois")


class TestCliFind(CasoComLedger):
    def test_find_nao_registra_e_mostra_correcao(self):
        self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file")
        self.cli("fix", "1", "prep do worktree", "--ref", "abc123")
        codigo, saida = self.cli("find", "bin/runner no such file")
        self.assertEqual(codigo, 0)
        self.assertIn("1. [fts]", saida)
        self.assertIn("exit code N /PATH: no such file", saida)
        self.assertIn("correção: prep do worktree [ref: abc123]", saida)
        self.assertEqual(self.banco.consultar("SELECT COUNT(*) FROM errors")[0][0], 1)

    def test_find_sem_achado(self):
        codigo, saida = self.cli("find", "segmentation fault")
        self.assertEqual((codigo, saida.strip()), (0, "nada parecido com confiança no ledger"))

    def test_find_json_stdin_e_limite(self):
        for nome in ("alfa", "beta", "gama"):
            self.cli("err", "falha comum no modulo %s" % nome)
        codigo, saida = self.cli("find", "-", "-n", "2", "--json", entrada="falha comum")
        achados = json.loads(saida)["achados"]
        self.assertEqual((codigo, len(achados)), (0, 2))
        self.assertEqual(achados[0]["origem"], "fts")
