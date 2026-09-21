from __future__ import annotations

from tests.apoio import CasoComLedger


class TestCompactar(CasoComLedger):
    """Historico ja inflado colapsa em linha unica com contador.

    3.017 linhas da mesma quarentena distorcem o idf do FTS e portanto o limiar
    da busca; compactar e pre-requisito de recalibrar.
    """

    def _importar(self, texto, task, n, projeto="acme"):
        for i in range(n):
            self.ledger.registrar_erro_importado(
                texto, projeto, contexto={"task": task},
                chave_importacao="%s-%s-%d" % (texto[:8], task, i),
                ts="2026-09-0%dT10:00:0%d" % (1 + i % 9, i % 10),
            )

    def test_colapsa_repeticao_da_mesma_task_somando_repeticoes(self):
        self._importar("quarentena: sem pronto", "t1", 5)
        resumo = self.ledger.compactar("acme")
        linhas = self.ledger._erros.por_assinatura("quarentena: sem pronto")
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0].repeticoes, 5)
        self.assertEqual((resumo.linhas_antes, resumo.linhas_depois), (5, 1))

    def test_preserva_uma_linha_por_task(self):
        self._importar("quarentena: sem pronto", "t1", 3)
        self._importar("quarentena: sem pronto", "t2", 2)
        self.ledger.compactar("acme")
        linhas = self.ledger._erros.por_assinatura("quarentena: sem pronto")
        self.assertEqual(len(linhas), 2)
        self.assertEqual(sorted(l.repeticoes for l in linhas), [2, 3])

    def test_mantem_o_ts_mais_antigo_da_task(self):
        self._importar("quarentena: sem pronto", "t1", 4)
        antes = min(l.ts for l in self.ledger._erros.por_assinatura("quarentena: sem pronto"))
        self.ledger.compactar("acme")
        self.assertEqual(self.ledger._erros.por_assinatura("quarentena: sem pronto")[0].ts, antes)

    def test_top_ve_o_mesmo_numero_antes_e_depois(self):
        # compactar nao pode mudar o que o top reporta: so a forma de guardar muda
        self._importar("quarentena: sem pronto", "t1", 4)
        self._importar("conflito de merge", "t2", 2)
        antes = [(p.assinatura, p.ocorrencias, p.tasks) for p in self.ledger.o_que_repete("acme")]
        self.ledger.compactar("acme")
        self.assertEqual([(p.assinatura, p.ocorrencias, p.tasks) for p in self.ledger.o_que_repete("acme")], antes)

    def test_dry_run_nao_escreve(self):
        self._importar("quarentena: sem pronto", "t1", 3)
        resumo = self.ledger.compactar("acme", dry_run=True)
        self.assertEqual((resumo.linhas_antes, resumo.linhas_depois), (3, 1))
        self.assertEqual(len(self.ledger._erros.por_assinatura("quarentena: sem pronto")), 3)

    def test_fts_fica_com_uma_entrada_por_linha_sobrevivente(self):
        self._importar("quarentena: sem pronto", "t1", 4)
        self.ledger.compactar("acme")
        viva = self.ledger._erros.por_assinatura("quarentena: sem pronto")[0]
        linhas = self.ledger._erros._banco.consultar(
            "SELECT count(*) AS n FROM ledger_fts WHERE signature = ?", ("quarentena: sem pronto",))
        self.assertEqual(linhas[0]["n"], 1)
        self.assertEqual(self.ledger._erros.por_id(viva.id).repeticoes, 4)

    def test_correcao_continua_achavel_depois_de_compactar(self):
        self._importar("quarentena: sem pronto", "t1", 3)
        self.ledger.registrar_correcao("quarentena: sem pronto", "ajustar o card", "acme")
        self.ledger.compactar("acme")
        achados = self.ledger.buscar("quarentena: sem pronto", so_resolvidos=True)
        self.assertEqual(achados[0].correcoes[0].nota, "ajustar o card")
