"""Corpus de logs reais (anonimizados) em tests/corpus: trava o veredito do Ledger.decidir com
sementes e a assinatura normalizada de cada log. Se a assinatura mudar sem bump de
Assinatura.VERSAO, o teste falha e diz isso; com bump, regrave o manifesto:

    python3 -B -m tests.test_corpus_assinatura --regravar
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from erratum.dominio import Assinatura
from erratum.sementes import Semeador
from tests.apoio import CasoComLedger

CORPUS = Path(__file__).parent / "corpus"
MANIFESTO = CORPUS / "esperado.json"


def _log(arquivo):
    return (CORPUS / arquivo).read_text(encoding="utf-8")


def _manifesto():
    return json.loads(MANIFESTO.read_text(encoding="utf-8"))


class TestCorpusDeAssinatura(CasoComLedger):
    def setUp(self):
        super().setUp()
        self.esperado = _manifesto()
        self.casos = {c["arquivo"]: c for c in self.esperado["casos"]}

    def test_todo_log_do_corpus_esta_no_manifesto(self):
        logs = sorted(p.name for p in CORPUS.glob("*.log"))
        self.assertEqual(logs, sorted(self.casos))
        self.assertGreaterEqual(len(logs), 20)

    def test_assinatura_normalizada(self):
        versao = self.esperado["versao_assinatura"]
        for arquivo, caso in self.casos.items():
            atual = Assinatura(_log(arquivo)).valor
            if atual == caso["assinatura_normalizada"]:
                continue
            if Assinatura.VERSAO == versao:
                self.fail(
                    "mudou assinatura sem bump de Assinatura.VERSAO (%s): %r virou %r"
                    % (arquivo, caso["assinatura_normalizada"], atual)
                )
            self.fail(
                "Assinatura.VERSAO %d != %d do manifesto: regrave com "
                "python3 -B -m tests.test_corpus_assinatura --regravar"
                % (Assinatura.VERSAO, versao)
            )

    def test_veredito_com_sementes(self):
        Semeador(self.ledger).semear()
        for arquivo, caso in self.casos.items():
            d = self.ledger.decidir(_log(arquivo), so_resolvidos=True)
            self.assertEqual(d.veredito, caso["veredito"], arquivo)

    def test_erros_distintos_nao_colidem(self):
        for a, b in self.esperado["pares"]["distintos"]:
            self.assertNotEqual(Assinatura(_log(a)), Assinatura(_log(b)), (a, b))

    def test_mesmo_erro_em_caminho_ou_worktree_diferente_colide(self):
        for a, b in self.esperado["pares"]["iguais"]:
            self.assertEqual(Assinatura(_log(a)), Assinatura(_log(b)), (a, b))

    @unittest.expectedFailure
    def test_colisoes_conhecidas_ainda_colidem(self):
        # defeito conhecido do normalizador: quando for corrigido este teste passa e o
        # expectedFailure acusa; mova o par para pares.distintos
        for a, b, _motivo in self.esperado["colisoes_conhecidas"]:
            self.assertNotEqual(Assinatura(_log(a)), Assinatura(_log(b)), (a, b))


def regravar():
    """Regrava assinatura, veredito e versao do manifesto a partir do codigo atual."""
    import tempfile
    from erratum.banco import Banco
    from erratum.ledger import Ledger
    esperado = _manifesto()
    with tempfile.TemporaryDirectory() as tmp:
        banco = Banco(Path(tmp) / "ledger.db")
        ledger = Ledger.sobre(banco, ambiente={})
        Semeador(ledger).semear()
        for caso in esperado["casos"]:
            texto = _log(caso["arquivo"])
            caso["assinatura_normalizada"] = Assinatura(texto).valor
            caso["veredito"] = ledger.decidir(texto, so_resolvidos=True).veredito
        banco.fechar()
    esperado["versao_assinatura"] = Assinatura.VERSAO
    MANIFESTO.write_text(json.dumps(esperado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__" and "--regravar" in sys.argv:
    regravar()
