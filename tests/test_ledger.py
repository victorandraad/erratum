from __future__ import annotations

import multiprocessing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.apoio import CasoComLedger


def _insere_em_lote(args):
    """Roda em outro processo: abre o PRÓPRIO Banco (é o cenário real, várias CLIs ao mesmo tempo)."""
    caminho, processo, quantos = args
    from erratum.banco import Banco
    from erratum.ledger import Ledger
    with Banco(caminho) as banco:
        ledger = Ledger.sobre(banco)
        for i in range(quantos):
            # letras: Assinatura troca digito por N, e o contador colapsa
            # assinatura+escopo iguais. Aqui cada insert tem de ser linha propria.
            marca = chr(65 + processo) + chr(65 + (i % 26)) + chr(65 + (i // 26))
            ledger.registrar_erro("falha concorrente %s" % marca, "acme")
    return quantos


class TestBanco(unittest.TestCase):
    def test_wal_timeout_e_caminho_por_ambiente(self):
        from erratum.banco import Banco
        with tempfile.TemporaryDirectory() as tmp:
            alvo = Path(tmp) / "sub" / "l.db"
            with Banco(ambiente={"ERRATUM_DB": str(alvo)}) as banco:
                self.assertEqual(banco.caminho, alvo)
                self.assertEqual(banco.consultar("PRAGMA journal_mode")[0][0], "wal")
                self.assertEqual(banco.consultar("PRAGMA busy_timeout")[0][0], 5000)
                tabelas = {r[0] for r in banco.consultar("SELECT name FROM sqlite_master")}
            self.assertTrue({"errors", "fixes", "wins", "gate_runs", "ledger_fts"} <= tabelas)

    def test_caminho_padrao_fica_no_state_do_usuario(self):
        from erratum.banco import Banco
        self.assertEqual(Banco.caminho_padrao({}),
                         Path.home() / ".local" / "state" / "erratum" / "ledger.db")

    def test_transacao_desfaz_no_erro(self):
        from erratum.banco import Banco
        with tempfile.TemporaryDirectory() as tmp, Banco(Path(tmp) / "l.db") as banco:
            with self.assertRaises(RuntimeError):
                with banco.transacao() as con:
                    con.execute("INSERT INTO wins(ts, project, what) VALUES('t','acme','x')")
                    raise RuntimeError("no meio")
            self.assertEqual(banco.consultar("SELECT COUNT(*) FROM wins")[0][0], 0)


class TestConcorrencia(unittest.TestCase):
    def test_concorrencia(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "ledger.db")
            with multiprocessing.get_context("spawn").Pool(8) as pool:
                feitos = pool.map(_insere_em_lote, [(caminho, p, 50) for p in range(8)])
            self.assertEqual(sum(feitos), 400)
            con = sqlite3.connect(caminho)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 400)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM ledger_fts").fetchone()[0], 400)
            con.close()


class TestErroECorrecao(CasoComLedger):
    def test_registra_erro_com_assinatura_e_contexto(self):
        erro, pistas = self.ledger.registrar_erro(
            "Exit code 127 /tmp/w-1/bin/runner: No such file", "acme",
            etapa="dev", ferramenta="Bash", contexto={"task": "t1"})
        self.assertEqual(erro.assinatura, "exit code N /PATH: no such file")
        self.assertEqual((erro.projeto, erro.etapa, erro.ferramenta), ("acme", "dev", "Bash"))
        self.assertEqual(erro.contexto, {"task": "t1"})
        self.assertEqual(pistas, [])
        self.assertEqual(self.ledger.erro(erro.id), erro)

    def test_fix_cobre_ocorrencias_futuras(self):
        antigo, _ = self.ledger.registrar_erro("Exit code 127 /tmp/w-1/bin/runner: No such file", "acme")
        correcao = self.ledger.registrar_correcao(antigo.id, "prep do worktree", "acme",
                                                  ref="abc123", teste="test_prep")
        self.assertEqual(correcao.assinatura, antigo.assinatura)
        # ocorrência FUTURA, outro caminho e outro código: mesma assinatura, já nasce com a correção
        _, pistas = self.ledger.registrar_erro("Exit code 1 /tmp/w-99/bin/runner: No such file", "acme")
        self.assertEqual([c.nota for c in pistas[0].correcoes], ["prep do worktree"])
        self.assertEqual(pistas[0].correcoes[0].ref, "abc123")
        # e a passada também: a correção casa por assinatura, não por id
        self.assertEqual(self.ledger.correcoes_de(antigo.assinatura)[0].id, correcao.id)

    def test_fix_aceita_texto_cru(self):
        correcao = self.ledger.registrar_correcao("Timeout 30s em /srv/fila", "aumentar o teto", "acme")
        self.assertEqual(correcao.assinatura, "timeout Ns em /PATH")

    def test_fix_de_id_inexistente_acusa(self):
        from erratum.ledger import ErroNaoEncontrado
        with self.assertRaises(ErroNaoEncontrado):
            self.ledger.registrar_correcao(999, "nota", "acme")

    def test_chave_de_importacao_e_idempotente(self):
        a, _ = self.ledger.registrar_erro("falha x", "acme", chave_importacao="k1")
        b, _ = self.ledger.registrar_erro("falha x", "acme", chave_importacao="k1")
        self.assertEqual(a.id, b.id)
        self.assertEqual(self.banco.consultar("SELECT COUNT(*) FROM errors")[0][0], 1)

    def test_registrar_portao_grava_aprovou_e_reprovou(self):
        ok = self.ledger.registrar_portao("em-dash", "aprovou", "", "acme")
        ruim = self.ledger.registrar_portao("stub-neutro", "reprovou", "classe Nula", "acme")
        self.assertEqual((ok.portao, ok.veredito, ruim.detalhe), ("em-dash", "aprovou", "classe Nula"))
        linhas = self.banco.consultar("SELECT gate, verdict, project FROM gate_runs ORDER BY id")
        self.assertEqual([tuple(l) for l in linhas],
                         [("em-dash", "aprovou", "acme"), ("stub-neutro", "reprovou", "acme")])


if __name__ == "__main__":
    unittest.main()
