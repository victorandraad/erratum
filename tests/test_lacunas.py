"""Lacunas fechadas depois do primeiro uso real: pipe fechado, peso do top, correção importada
com data real, busca só de resolvidos e portão que só pula."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.apoio import CasoComLedger

RAIZ = Path(__file__).resolve().parent.parent


class TestPipeFechado(unittest.TestCase):
    def test_top_com_leitor_que_fecha_cedo_sai_em_silencio(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "ledger.db")
            from erratum.banco import Banco
            from erratum.ledger import Ledger
            with Banco(caminho) as banco:
                ledger = Ledger.sobre(banco)
                # saída bem maior que o buffer do pipe (64k), senão o write nunca falha
                for n in range(1500):
                    ledger.registrar_erro(
                        "falha %s no modulo %s" % ("x" * 60, _letras(n)), "acme",
                        com_pistas=False)
            ambiente = dict(os.environ, ERRATUM_DB=caminho, PYTHONPATH=str(RAIZ))
            proc = subprocess.Popen(
                [sys.executable, "-m", "erratum", "top", "--all-projects"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ambiente, cwd=tmp)
            proc.stdout.readline()
            proc.stdout.close()
            erro = proc.stderr.read().decode("utf-8", "replace")
            proc.stderr.close()
            codigo = proc.wait(timeout=60)
        self.assertEqual(erro, "")
        self.assertEqual(codigo, 0)


def _letras(n):
    # a assinatura troca dígito por N: o que distingue um padrão do outro tem que ser letra
    return "".join(chr(ord("a") + int(d)) for d in str(n))


class TestPesoDoTop(CasoComLedger):
    def test_sem_task_nao_passa_na_frente_de_muitas_tasks(self):
        for n in range(50):
            self.ledger.registrar_erro("falha de rede %d" % n, "acme")
        for n in range(3):
            self.ledger.registrar_erro("dev terminou sem commit %d" % n, "acme",
                                       contexto={"task": "t%d" % n})
        padroes = self.ledger.o_que_repete("acme")
        self.assertEqual([p.assinatura for p in padroes],
                         ["dev terminou sem commit N", "falha de rede N"])

    def test_empate_de_peso_desempata_por_ocorrencias(self):
        self.ledger.registrar_erro("disco cheio 1", "acme", contexto={"task": "a"})
        for n in range(4):
            self.ledger.registrar_erro("falha de rede %d" % n, "acme")
        padroes = self.ledger.o_que_repete("acme")
        self.assertEqual([p.assinatura for p in padroes], ["falha de rede N", "disco cheio N"])

    def test_sem_correcao_continua_antes_de_resolvido(self):
        for n in range(9):
            self.ledger.registrar_erro("disco cheio %d" % n, "acme", contexto={"task": "t%d" % n})
        self.ledger.registrar_correcao("disco cheio 1", "rotacionar log", "acme")
        self.ledger.registrar_erro("falha de rede 1", "acme")
        padroes = self.ledger.o_que_repete("acme", resolvidos=True)
        self.assertEqual([p.assinatura for p in padroes], ["falha de rede N", "disco cheio N"])


class TestCorrecaoImportada(CasoComLedger):
    def test_ts_opcional_em_registrar_correcao(self):
        c = self.ledger.registrar_correcao("disco cheio 1", "rotacionar", "acme",
                                           ts="2025-03-04T00:00:00.000000+00:00")
        self.assertEqual(c.ts, "2025-03-04T00:00:00.000000+00:00")
        lidas = self.ledger.correcoes_de(c.assinatura)
        self.assertEqual(lidas[0].ts, "2025-03-04T00:00:00.000000+00:00")

    def test_sem_ts_usa_o_relogio(self):
        c = self.ledger.registrar_correcao("disco cheio 1", "rotacionar", "acme")
        self.assertTrue(c.ts.startswith("2026-01-01"))

    def test_importada_diz_se_inseriu(self):
        primeira, inseriu = self.ledger.registrar_correcao_importada(
            "disco cheio 1", "rotacionar", "acme", fonte="import", chave_importacao="k1",
            ts="2025-03-04T00:00:00.000000+00:00")
        self.assertTrue(inseriu)
        self.assertEqual(primeira.ts, "2025-03-04T00:00:00.000000+00:00")
        segunda, inseriu = self.ledger.registrar_correcao_importada(
            "disco cheio 1", "outra nota", "acme", fonte="import", chave_importacao="k1")
        self.assertFalse(inseriu)
        self.assertEqual(segunda.id, primeira.id)
        self.assertEqual(len(self.ledger.correcoes_de(primeira.assinatura)), 1)

    def test_registrar_correcao_continua_devolvendo_a_correcao(self):
        c = self.ledger.registrar_correcao("disco cheio 1", "rotacionar", "acme",
                                           chave_importacao="k1")
        de_novo = self.ledger.registrar_correcao("disco cheio 1", "rotacionar", "acme",
                                                 chave_importacao="k1")
        self.assertEqual(de_novo.id, c.id)


class TestSoResolvidos(CasoComLedger):
    def setUp(self):
        super().setUp()
        self.ledger.registrar_erro("disco cheio em backup dados quando roda 1", "acme")
        self.ledger.registrar_erro("disco cheio em backup quando roda 2", "acme")
        self.ledger.registrar_correcao(
            "disco cheio em backup dados quando roda 9", "rotacionar log", "acme"
        )

    def test_buscar_so_resolvidos(self):
        todos = self.ledger.buscar("disco cheio em backup quando roda 7")
        self.assertTrue(any(not a.correcoes for a in todos))
        resolvidos = self.ledger.buscar("disco cheio em backup quando roda 7", so_resolvidos=True)
        self.assertTrue(resolvidos)
        self.assertTrue(all(a.correcoes for a in resolvidos))

    def test_n_vale_depois_do_filtro(self):
        # o sem correção é o melhor casamento; com n=1 o filtro não pode devolver vazio
        resolvidos = self.ledger.buscar("disco cheio em backup quando roda 7", n=1,
                                        so_resolvidos=True)
        self.assertEqual(len(resolvidos), 1)
        self.assertTrue(resolvidos[0].correcoes)

    def test_find_resolved_na_cli(self):
        codigo, saida = self.cli("find", "disco cheio em backup quando roda 7", "--resolved",
                                 "--json")
        self.assertEqual(codigo, 0)
        achados = json.loads(saida)["achados"]
        self.assertTrue(achados)
        self.assertTrue(all(a["correcoes"] for a in achados))


class TestPortaoQueSoPula(CasoComLedger):
    def setUp(self):
        super().setUp()
        for _ in range(3):
            self.ledger.registrar_portao("fix-noop", "pulou", "sem runner", "acme")
        self.ledger.registrar_portao("em-dash", "aprovou", "", "acme")
        self.ledger.registrar_portao("em-dash", "pulou", "", "acme")

    def test_saida_humana_marca_o_portao_que_nunca_decide(self):
        _, saida = self.cli("top")
        linhas = {l.split(":")[0]: l for l in saida.splitlines() if l.startswith("port")}
        self.assertIn("nunca decidiu", linhas["portão fix-noop"])
        self.assertIn("0/0 reprovou", linhas["portão fix-noop"])
        self.assertNotIn("nunca decidiu", linhas["portão em-dash"])

    def test_json_traz_o_booleano(self):
        _, saida = self.cli("top", "--json")
        portoes = {p["portao"]: p for p in json.loads(saida)["portoes"]}
        self.assertIs(portoes["fix-noop"]["nunca_decidiu"], True)
        self.assertIs(portoes["em-dash"]["nunca_decidiu"], False)


if __name__ == "__main__":
    unittest.main()
