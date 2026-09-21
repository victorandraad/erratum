"""Registro de decisão auditável: cada pista mostrada (ou o silêncio) vira linha em `pistas`,
o desfecho fecha as linhas da task e `efeito` compara quem recebeu match com quem ficou sem pista."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from erratum.banco import Banco
from erratum.ledger import Ledger
from erratum.sementes import Semeador
from tests.apoio import CasoComLedger, Relogio
from tests.test_sementes import VARIACOES

ALHEIO = "kernel panic - not syncing: VFS unable to mount root fs"


class CasoComSementes(CasoComLedger):
    def setUp(self):
        super().setUp()
        Semeador(self.ledger).semear()

    def pistas(self):
        return [dict(l) for l in self.banco.consultar("SELECT * FROM pistas ORDER BY id")]


class TestErrGravaPista(CasoComSementes):
    def test_match_grava_uma_linha_por_pista_mostrada(self):
        _, saida = self.cli("err", VARIACOES[0][0], "--task", "T-1", "--json")
        dado = json.loads(saida)
        linhas = self.pistas()
        self.assertEqual(len(linhas), len(dado["pistas"]))
        p = linhas[0]
        self.assertEqual((p["project"], p["task"], p["erro_id"]), ("acme", "T-1", dado["erro"]["id"]))
        self.assertEqual((p["origem"], p["veredito"]), ("semente", "match"))
        self.assertEqual(p["correcao_id"], dado["pistas"][0]["correcoes"][0]["id"])
        self.assertTrue(0 < p["confianca"] <= 1)
        self.assertIsNone(p["desfecho"])
        self.assertIsNone(p["desfecho_ts"])
        self.assertTrue(p["ts"])

    def test_silencio_tambem_e_registrado(self):
        self.cli("err", ALHEIO, "--task", "T-2")
        (p,) = self.pistas()
        self.assertEqual((p["veredito"], p["correcao_id"], p["task"]), ("abstain", None, "T-2"))

    def test_origem_assinatura_quando_a_correcao_nao_e_semente(self):
        self.cli("err", "Timeout 30s em /srv/fila")
        self.cli("fix", "1", "aumentar o teto")
        self.cli("err", "Timeout 31s em /srv/fila", "--task", "T-3")
        p = self.pistas()[-1]
        self.assertEqual((p["origem"], p["veredito"], p["confianca"]), ("assinatura", "match", 1.0))

    def test_task_continua_no_contexto_e_o_top_nao_quebra(self):
        self.cli("err", ALHEIO, "--task", "T-4")
        self.assertEqual(self.ledger.erro(1).contexto["task"], "T-4")
        self.assertEqual(self.cli("top")[0], 0)

    def test_com_pistas_false_nao_grava(self):
        self.ledger.registrar_erro(ALHEIO, "acme", com_pistas=False)
        self.assertEqual(self.pistas(), [])

    def test_find_so_grava_com_registrar(self):
        self.cli("find", VARIACOES[0][0], "--resolved")
        self.assertEqual(self.pistas(), [])
        self.cli("find", VARIACOES[0][0], "--resolved", "--registrar", "--task", "T-5")
        (p, *_resto) = self.pistas()
        self.assertEqual((p["task"], p["erro_id"], p["veredito"]), ("T-5", None, "match"))


class TestDesfecho(CasoComSementes):
    def test_desfecho_fecha_so_as_abertas_da_task(self):
        self.cli("err", VARIACOES[0][0], "--task", "T-1")
        self.cli("err", VARIACOES[1][0], "--task", "T-9")
        codigo, saida = self.cli("desfecho", "T-1", "nao_resolveu")
        self.assertEqual(codigo, 0)
        abertas = [p for p in self.pistas() if p["desfecho"] is None]
        self.assertTrue(all(p["task"] == "T-9" for p in abertas))
        self.assertTrue(abertas)
        fechadas = [p for p in self.pistas() if p["task"] == "T-1"]
        self.assertTrue(all(p["desfecho"] == "nao_resolveu" and p["desfecho_ts"] for p in fechadas))
        self.assertIn(str(len(fechadas)), saida)
        # segunda chamada nao reescreve o que ja fechou
        self.assertEqual(self.ledger.registrar_desfecho("T-1", "resolveu", projeto="acme"), 0)

    def test_desfecho_respeita_o_projeto(self):
        self.cli("err", VARIACOES[0][0], "--task", "T-1", "--project", "loja")
        self.assertEqual(self.ledger.registrar_desfecho("T-1", "resolveu", projeto="outro"), 0)
        self.assertEqual(self.ledger.registrar_desfecho("T-1", "resolveu", projeto="loja"), 1)

    def test_desfecho_invalido_e_task_vazia_sao_uso_errado(self):
        self.assertEqual(self.cli("desfecho", "T-1", "talvez")[0], 2)
        with self.assertRaises(ValueError):
            self.ledger.registrar_desfecho("T-1", "sei la", projeto="acme")
        with self.assertRaises(ValueError):
            self.ledger.registrar_desfecho("", "resolveu", projeto="acme")

    def test_fix_e_win_com_task_fecham_como_resolveu(self):
        self.cli("err", VARIACOES[0][0], "--task", "T-1")
        self.cli("err", VARIACOES[1][0], "--task", "T-2")
        self.cli("fix", "1", "rebase resolveu", "--task", "T-1")
        self.cli("win", "passou de primeira", "--task", "T-2")
        self.assertEqual({p["desfecho"] for p in self.pistas()}, {"resolveu"})

    def test_fix_sem_task_nao_fecha_nada(self):
        self.cli("err", VARIACOES[0][0], "--task", "T-1")
        self.cli("fix", "1", "rebase resolveu")
        self.assertEqual({p["desfecho"] for p in self.pistas()}, {None})


class TestEfeito(CasoComSementes):
    def _cenario(self):
        # 3 tasks com match (2 resolveram, 1 nao), 2 tasks no silencio (1 resolveu, 1 aberta)
        for i, desfecho in enumerate(["resolveu", "resolveu", "nao_resolveu"]):
            self.cli("err", VARIACOES[i][0], "--task", "M-%d" % i)
            self.cli("desfecho", "M-%d" % i, desfecho)
        self.cli("err", ALHEIO, "--task", "S-0")
        self.cli("desfecho", "S-0", "resolveu")
        self.cli("err", ALHEIO, "--task", "S-1")
        self.cli("err", ALHEIO)  # sem task: conta como pista, nao entra na comparacao por task

    def test_comparacao_por_task_com_n_ao_lado(self):
        self._cenario()
        dado = json.loads(self.cli("efeito", "--json")[1])
        g = {x["grupo"]: x for x in dado["tasks"]}
        self.assertEqual((g["match"]["n"], g["match"]["com_desfecho"], g["match"]["resolveu"]), (3, 3, 2))
        self.assertEqual((g["abstain"]["n"], g["abstain"]["com_desfecho"], g["abstain"]["resolveu"]), (2, 1, 1))
        self.assertEqual((g["geral"]["n"], g["geral"]["com_desfecho"], g["geral"]["resolveu"]), (5, 4, 3))
        self.assertAlmostEqual(g["match"]["taxa"], 2 / 3, places=3)
        self.assertTrue(all(x["amostra_pequena"] for x in dado["tasks"]))
        self.assertNotIn("p_valor", json.dumps(dado))

    def test_quebra_por_origem_e_por_veredito(self):
        self._cenario()
        dado = json.loads(self.cli("efeito", "--json")[1])
        v = {x["veredito"]: x for x in dado["por_veredito"]}
        self.assertEqual((v["abstain"]["pistas"], v["abstain"]["com_desfecho"]), (3, 1))
        self.assertGreaterEqual(v["match"]["pistas"], 3)
        o = {x["origem"]: x for x in dado["por_origem"]}
        self.assertIn("semente", o)
        self.assertEqual(o["semente"]["resolveu"] + 0, o["semente"]["resolveu"])

    def test_task_sem_desfecho_nao_tem_taxa(self):
        self.cli("err", ALHEIO, "--task", "S-1")
        dado = json.loads(self.cli("efeito", "--json")[1])
        g = {x["grupo"]: x for x in dado["tasks"]}
        self.assertIsNone(g["abstain"]["taxa"])
        self.assertEqual(g["match"]["n"], 0)

    def test_texto_avisa_amostra_pequena(self):
        self._cenario()
        codigo, saida = self.cli("efeito")
        self.assertEqual(codigo, 0)
        self.assertIn("amostra pequena, não conclua", saida)
        self.assertIn("N=3", saida)
        self.assertIn("N=2", saida)

    def test_days_corta_o_passado(self):
        self._cenario()
        self.relogio.avancar(days=10)
        self.cli("err", ALHEIO, "--task", "S-9")
        dado = json.loads(self.cli("efeito", "--days", "5", "--json")[1])
        g = {x["grupo"]: x for x in dado["tasks"]}
        self.assertEqual((g["geral"]["n"], g["match"]["n"]), (1, 0))

    def test_sem_aviso_quando_n_chega_a_30(self):
        for i in range(30):
            self.cli("err", ALHEIO, "--task", "S-%d" % i)
            self.cli("desfecho", "S-%d" % i, "resolveu")
        dado = json.loads(self.cli("efeito", "--json")[1])
        g = {x["grupo"]: x for x in dado["tasks"]}
        self.assertFalse(g["abstain"]["amostra_pequena"])
        self.assertTrue(g["match"]["amostra_pequena"])


class TestBancoAntigoSemPistas(unittest.TestCase):
    def test_abre_e_cria_a_tabela_sem_perder_dado(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "velho.db"
            with Banco(caminho) as banco:
                Ledger.sobre(banco, relogio=Relogio(), ambiente={}).registrar_erro("falha 1", "acme", com_pistas=False)
            con = sqlite3.connect(str(caminho))
            con.execute("DROP TABLE pistas")
            con.commit()
            con.close()
            with Banco(caminho) as banco:
                ledger = Ledger.sobre(banco, relogio=Relogio(), ambiente={})
                self.assertEqual(ledger.erro(1).texto, "falha 1")
                ledger.registrar_erro("falha 2", "acme", task="T-1")
                self.assertEqual(len(banco.consultar("SELECT * FROM pistas")), 1)


if __name__ == "__main__":
    unittest.main()
