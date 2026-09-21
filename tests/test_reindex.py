"""`erratum reindex`: recalcula as assinaturas gravadas com a regra atual, reconstrói o FTS,
numa transação, idempotente; e a tabela meta avisa quando o banco está com regra antiga."""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from erratum.banco import Banco
from erratum.dominio import Assinatura
from erratum.ledger import Ledger
from erratum.reindex import Reindexador
from tests.apoio import CasoComLedger, Relogio


def _envelhecer(banco):
    """Deixa o banco como um ledger da regra antiga: assinatura = texto minúsculo, sem meta."""
    with banco.transacao() as con:
        con.execute("UPDATE errors SET signature = lower(text)")
        con.execute("UPDATE ledger_fts SET signature = lower(text) WHERE src LIKE 'error:%'")
        con.execute("DELETE FROM meta")


class TestReindex(CasoComLedger):
    def _semear(self):
        # tasks distintas: o contador de repeticao so colapsa o mesmo escopo
        self.ledger.registrar_erro(
            "conflito ao mergear feat/a em develop", "acme",
            contexto={"task": "t1"}, com_pistas=False)
        self.ledger.registrar_erro(
            "conflito ao mergear feat/b em principal", "acme",
            contexto={"task": "t2"}, com_pistas=False)
        self.ledger.registrar_erro(
            "timeout 30s", "acme", contexto={"task": "t3"}, com_pistas=False)
        _envelhecer(self.banco)
        # correção presa à assinatura ANTIGA do erro 1, como num banco real pré-regra
        with self.banco.transacao() as con:
            con.execute(
                "INSERT INTO fixes(ts, project, signature, note, ref, test, source) "
                "VALUES ('2026-01-01', 'acme', 'conflito ao mergear feat/a em develop', "
                "'rebase antes do merge', '', '', 'manual')")
            con.execute("INSERT INTO ledger_fts(signature, text, note, src) VALUES "
                        "('conflito ao mergear feat/a em develop', '', 'rebase antes do merge', 'fix:1')")

    def test_junta_assinaturas_e_correcao_acompanha(self):
        self._semear()
        r = Reindexador(self.banco).rodar()
        self.assertEqual((r.antes, r.depois), (3, 2))
        nova = Assinatura("conflito ao mergear feat/zzz em qualquer").valor
        self.assertEqual(len(self.ledger.correcoes_de(nova)), 1)
        # o segundo erro, que nunca teve correção, agora acha a do primeiro pela assinatura
        achados = self.ledger.buscar("conflito ao mergear feat/c em outra", so_resolvidos=True)
        self.assertEqual(achados[0].origem, "assinatura")

    def test_dry_run_nao_escreve(self):
        self._semear()
        r = Reindexador(self.banco).rodar(simular=True)
        self.assertEqual((r.antes, r.depois), (3, 2))
        sigs = self.banco.consultar("SELECT DISTINCT signature FROM errors")
        self.assertEqual(len(sigs), 3)
        self.assertTrue(Ledger.sobre(self.banco).regra_desatualizada())

    def test_idempotente_e_fts_reconstruido(self):
        self._semear()
        Reindexador(self.banco).rodar()
        foto = self.banco.consultar("SELECT signature, text, note, src FROM ledger_fts ORDER BY src")
        r = Reindexador(self.banco).rodar()
        self.assertEqual((r.antes, r.depois), (2, 2))
        depois = self.banco.consultar("SELECT signature, text, note, src FROM ledger_fts ORDER BY src")
        self.assertEqual([tuple(l) for l in foto], [tuple(l) for l in depois])
        self.assertEqual(len(foto), 4)
        novo = Assinatura("conflito ao mergear feat/a em develop").valor
        self.assertEqual({l["signature"] for l in foto if l["src"] in ("error:1", "error:2", "fix:1")}, {novo})

    def test_semente_mantem_o_texto_no_fts(self):
        from erratum.sementes import Semeador
        Semeador(self.ledger).semear()
        antes = self.banco.consultar("SELECT text FROM ledger_fts WHERE src LIKE 'seed:%' ORDER BY src")
        Reindexador(self.banco).rodar()
        depois = self.banco.consultar("SELECT text FROM ledger_fts WHERE src LIKE 'seed:%' ORDER BY src")
        self.assertEqual([l["text"] for l in antes], [l["text"] for l in depois])
        self.assertTrue(all(l["text"] for l in depois))

    def test_falha_no_meio_desfaz_tudo(self):
        self._semear()

        class Explode(Reindexador):
            def _reconstruir_fts(self, con, *a, **k):
                raise RuntimeError("caiu no meio")

        with self.assertRaises(RuntimeError):
            Explode(self.banco).rodar()
        self.assertEqual(len(self.banco.consultar("SELECT DISTINCT signature FROM errors")), 3)
        self.assertEqual(len(self.banco.consultar("SELECT * FROM ledger_fts")), 4)

    def test_meta_grava_a_versao_e_o_aviso_some(self):
        self._semear()
        ledger = Ledger.sobre(self.banco)
        self.assertTrue(ledger.regra_desatualizada())
        Reindexador(self.banco).rodar()
        self.assertFalse(ledger.regra_desatualizada())
        linha = self.banco.consultar("SELECT value FROM meta WHERE key = 'regra_assinatura'")
        self.assertEqual(linha[0]["value"], str(Assinatura.VERSAO))

    def test_banco_novo_ja_nasce_na_regra_atual(self):
        self.assertFalse(self.ledger.regra_desatualizada())
        self.ledger.registrar_erro("x", "acme", com_pistas=False)
        self.assertFalse(Ledger.sobre(self.banco).regra_desatualizada())


class TestBancoAntigoSemMeta(unittest.TestCase):
    def test_abre_sem_perder_dado_e_acusa_regra_antiga(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "velho.db"
            with Banco(caminho) as banco:
                Ledger.sobre(banco, relogio=Relogio()).registrar_erro("falha 1", "acme", com_pistas=False)
            con = sqlite3.connect(str(caminho))
            con.execute("DROP TABLE meta")
            con.commit()
            con.close()
            with Banco(caminho) as banco:
                ledger = Ledger.sobre(banco, relogio=Relogio())
                self.assertEqual(ledger.erro(1).texto, "falha 1")
                self.assertTrue(ledger.regra_desatualizada())
            # reabrir NÃO pode carimbar a versão atual num banco que já tem dado
            with Banco(caminho) as banco:
                self.assertTrue(Ledger.sobre(banco).regra_desatualizada())


class TestCliReindex(CasoComLedger):
    def _cli_com_aviso(self, *argv):
        from erratum.cli import Cli
        saida, aviso = io.StringIO(), io.StringIO()
        cli = Cli(lambda: self.ledger, entrada=io.StringIO(""), saida=saida,
                  projeto_padrao=lambda: "acme", aviso=aviso)
        return cli.executar(list(argv)), saida.getvalue(), aviso.getvalue()

    def test_reindex_imprime_antes_e_depois(self):
        self.ledger.registrar_erro(
            "push em feat/a", "acme", contexto={"task": "t1"}, com_pistas=False)
        self.ledger.registrar_erro(
            "push em feat/b", "acme", contexto={"task": "t2"}, com_pistas=False)
        _envelhecer(self.banco)
        codigo, saida = self.cli("reindex", "--dry-run")
        self.assertEqual(codigo, 0)
        self.assertIn("2", saida)
        self.assertIn("1", saida)
        self.assertIn("simula", saida.lower())
        codigo, saida = self.cli("reindex", "--json")
        dado = json.loads(saida)
        self.assertEqual((dado["antes"], dado["depois"], dado["simulado"]), (2, 1, False))

    def test_err_e_find_avisam_no_stderr_quando_a_regra_e_antiga(self):
        self.ledger.registrar_erro("push em feat/a", "acme", com_pistas=False)
        _envelhecer(self.banco)
        for argv in (("err", "outro erro"), ("find", "push")):
            _, saida, aviso = self._cli_com_aviso(*argv)
            self.assertIn("erratum reindex", aviso)
            self.assertNotIn("erratum reindex", saida)
        self._cli_com_aviso("reindex")
        _, _, aviso = self._cli_com_aviso("find", "push")
        self.assertEqual(aviso, "")


if __name__ == "__main__":
    unittest.main()
