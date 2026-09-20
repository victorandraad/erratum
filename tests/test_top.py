from __future__ import annotations

import json

from tests.apoio import CasoComLedger


class TestTop(CasoComLedger):
    def _erro(self, texto, task=None, projeto="acme"):
        contexto = {"task": task} if task else None
        return self.ledger.registrar_erro(texto, projeto, contexto=contexto)[0]

    def test_agrupa_por_assinatura_e_ordena_por_tasks_distintas(self):
        # 5 ocorrencias do MESMO card valem menos que 2 cards distintos: contagem bruta infla
        # quando o mesmo trabalho e revarrido, task distinta nao
        for n in range(5):
            self._erro("conflito de merge no arquivo %d" % n, task="a1")
        self._erro("dev terminou sem commit 1", task="b1")
        self._erro("dev terminou sem commit 2", task="b2")
        padroes = self.ledger.o_que_repete("acme")
        self.assertEqual([p.assinatura for p in padroes],
                         ["dev terminou sem commit N", "conflito de merge no arquivo N"])
        self.assertEqual((padroes[0].ocorrencias, padroes[0].tasks), (2, 2))
        self.assertEqual((padroes[1].ocorrencias, padroes[1].tasks), (5, 1))

    def test_sem_task_conta_ocorrencias(self):
        for n in range(3):
            self._erro("falha de rede %d" % n)
        self._erro("disco cheio em /var/dados", task="c1")
        padroes = self.ledger.o_que_repete("acme")
        self.assertEqual(padroes[0].assinatura, "falha de rede N")
        self.assertEqual((padroes[0].ocorrencias, padroes[0].tasks), (3, 0))

    def test_esconde_resolvidos_salvo_pedido(self):
        self._erro("falha de rede 1")
        for n in range(4):
            self._erro("disco cheio %d" % n)
        self.ledger.registrar_correcao("disco cheio 9", "rotacionar log", "acme")
        self.assertEqual([p.assinatura for p in self.ledger.o_que_repete("acme")], ["falha de rede N"])
        todos = self.ledger.o_que_repete("acme", resolvidos=True)
        # sem correcao primeiro, mesmo repetindo menos
        self.assertEqual([(p.assinatura, p.resolvido) for p in todos],
                         [("falha de rede N", False), ("disco cheio N", True)])

    def test_janela_de_dias(self):
        self._erro("falha antiga 1")
        self.relogio.avancar(days=10)
        self._erro("falha recente 1")
        self.assertEqual([p.assinatura for p in self.ledger.o_que_repete("acme", dias=7)],
                         ["falha recente N"])
        self.assertEqual(len(self.ledger.o_que_repete("acme")), 2)

    def test_filtra_por_projeto_ou_junta_todos(self):
        self._erro("falha de rede 1", projeto="acme")
        self._erro("falha de rede 2", projeto="outro")
        self.assertEqual(self.ledger.o_que_repete("acme")[0].ocorrencias, 1)
        juntos = self.ledger.o_que_repete(None)
        self.assertEqual(juntos[0].ocorrencias, 2)
        self.assertEqual(sorted(juntos[0].projetos), ["acme", "outro"])


class TestStreak(CasoComLedger):
    def test_streak(self):
        acerto, streak = self.ledger.registrar_acerto("card fechou de primeira", "acme",
                                                      task="a1", custo_usd=1.5)
        self.assertEqual((acerto.o_que, acerto.task, acerto.custo_usd, streak),
                         ("card fechou de primeira", "a1", 1.5, 1))
        self.assertEqual(self.ledger.registrar_acerto("outro", "acme")[1], 2)
        # acerto de outro projeto nao entra na conta, erro de outro projeto nao zera
        self.ledger.registrar_acerto("la", "outro")
        self.ledger.registrar_erro("falha la", "outro")
        self.assertEqual(self.ledger.streak("acme"), 2)
        # erro no projeto zera; o proximo acerto recomeca do 1
        self.ledger.registrar_erro("falha aqui", "acme")
        self.assertEqual(self.ledger.streak("acme"), 0)
        self.assertEqual(self.ledger.registrar_acerto("voltou", "acme")[1], 1)


class TestCliTop(CasoComLedger):
    def test_top_humano(self):
        self.cli("err", "dev terminou sem commit 1", "--task", "b1")
        self.cli("err", "dev terminou sem commit 2", "--task", "b2")
        self.cli("err", "disco cheio 1")
        self.cli("fix", "disco cheio 1", "rotacionar log")
        codigo, saida = self.cli("top")
        self.assertEqual(codigo, 0)
        self.assertIn("2x  2 tasks  sem correção  dev terminou sem commit N", saida)
        self.assertNotIn("disco cheio", saida)
        _, saida = self.cli("top", "--resolved")
        self.assertIn("1x  0 tasks  resolvido     disco cheio N", saida)

    def test_top_vazio(self):
        self.assertEqual(self.cli("top")[1].strip(), "nada se repetindo")

    def test_top_json_dias_e_todos_os_projetos(self):
        self.cli("err", "falha de rede 1", "--project", "outro")
        self.relogio.avancar(days=10)
        self.cli("err", "falha de rede 2")
        _, saida = self.cli("top", "--json")
        self.assertEqual(json.loads(saida)["padroes"][0]["ocorrencias"], 1)
        _, saida = self.cli("top", "--json", "--all-projects")
        self.assertEqual(json.loads(saida)["padroes"][0]["ocorrencias"], 2)
        _, saida = self.cli("top", "--json", "--all-projects", "--days", "7")
        self.assertEqual(json.loads(saida)["padroes"][0]["ocorrencias"], 1)


class TestCliWin(CasoComLedger):
    def test_win_grava_e_mostra_streak(self):
        codigo, saida = self.cli("win", "card fechou de primeira", "--task", "a1", "--cost", "1.5")
        self.assertEqual(codigo, 0)
        self.assertIn("acerto #1 registrado [acme] streak: 1", saida)
        _, saida = self.cli("win", "-", "--json", entrada="de novo\n")
        dado = json.loads(saida)
        self.assertEqual((dado["acerto"]["o_que"], dado["streak"]), ("de novo", 2))
        self.assertEqual(self.banco.consultar("SELECT task, cost_usd FROM wins WHERE id=1")[0][1], 1.5)
