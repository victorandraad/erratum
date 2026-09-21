from __future__ import annotations

from tests.apoio import CasoComLedger


class TestRepeticoes(CasoComLedger):
    """Repeticao consecutiva vira contador, nao linha nova.

    A esteira reemite o evento de falha a cada tick com o card parado: 16.046 linhas
    para 642 tasks. Dropar a linha destruiria `ocorrencias` do top, entao a linha
    unica passa a carregar quantas vezes o estado se repetiu.
    """

    def _erro(self, texto, task=None, projeto="acme"):
        ctx = {"task": task} if task else None
        return self.ledger.registrar_erro(texto, projeto, contexto=ctx)[0]

    def test_repeticao_consecutiva_incrementa_em_vez_de_inserir(self):
        a = self._erro("ci vermelho: gate de migrations", task="t1")
        b = self._erro("ci vermelho: gate de migrations", task="t1")
        self.assertEqual(b.id, a.id)
        self.assertEqual(b.repeticoes, 2)
        self.assertEqual(len(self.ledger._erros.por_assinatura(a.assinatura)), 1)

    def test_erro_novo_nasce_com_uma_repeticao(self):
        self.assertEqual(self._erro("disco cheio", task="t1").repeticoes, 1)

    def test_task_diferente_abre_linha_propria(self):
        a = self._erro("ci vermelho: gate de migrations", task="t1")
        b = self._erro("ci vermelho: gate de migrations", task="t2")
        self.assertNotEqual(b.id, a.id)
        self.assertEqual(b.repeticoes, 1)

    def test_projeto_diferente_abre_linha_propria(self):
        a = self._erro("ci vermelho", task="t1", projeto="acme")
        b = self._erro("ci vermelho", task="t1", projeto="outro")
        self.assertNotEqual(b.id, a.id)

    def test_outro_erro_no_meio_reabre_a_contagem(self):
        # falha, conserta, falha de novo sao dois eventos: nao pode virar um contador
        a = self._erro("ci vermelho", task="t1")
        self._erro("worktree sumiu", task="t1")
        c = self._erro("ci vermelho", task="t1")
        self.assertNotEqual(c.id, a.id)
        self.assertEqual(c.repeticoes, 1)

    def test_sem_task_usa_o_projeto_como_escopo(self):
        a = self._erro("worktree sumiu")
        b = self._erro("worktree sumiu")
        self.assertEqual(b.id, a.id)
        self.assertEqual(b.repeticoes, 2)

    def test_ts_da_linha_acompanha_a_ultima_repeticao(self):
        a = self._erro("ci vermelho", task="t1")
        b = self._erro("ci vermelho", task="t1")
        self.assertGreaterEqual(b.ts, a.ts)

    def test_fts_indexa_a_linha_uma_vez_so(self):
        a = self._erro("gate de migrations reprovou", task="t1")
        for _ in range(4):
            self._erro("gate de migrations reprovou", task="t1")
        linhas = self.ledger._erros._banco.consultar(
            "SELECT count(*) AS n FROM ledger_fts WHERE src = ?", ("error:%d" % a.id,)
        )
        self.assertEqual(linhas[0]["n"], 1)

    def test_top_soma_repeticoes_em_ocorrencias(self):
        for _ in range(5):
            self._erro("falha de rede", task="t1")
        self._erro("falha de rede", task="t2")
        padrao = self.ledger.o_que_repete("acme")[0]
        self.assertEqual((padrao.ocorrencias, padrao.tasks), (6, 2))

    def test_importacao_nao_passa_pelo_contador(self):
        # reindex/import reconstroi historico: preserva as linhas como estao
        ctx = {"task": "t1"}
        a = self.ledger.registrar_erro_importado("ci vermelho", "acme", contexto=ctx, chave_importacao="k1")[0]
        b = self.ledger.registrar_erro_importado("ci vermelho", "acme", contexto=ctx, chave_importacao="k2")[0]
        self.assertNotEqual(b.id, a.id)
