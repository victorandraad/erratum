"""Apoio dos testes: cada teste monta o próprio Ledger em tmpdir, com relógio falso que só anda
pra frente (assim ordem por ts é determinística sem sleep)."""
from __future__ import annotations

import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


class Relogio:
    def __init__(self, inicio=None):
        self.agora = inicio or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        self.agora += timedelta(seconds=1)
        return self.agora

    def avancar(self, **kw):
        self.agora += timedelta(**kw)


class CasoComLedger(unittest.TestCase):
    def setUp(self):
        from erratum.banco import Banco
        from erratum.ledger import Ledger
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.caminho = Path(self._tmp.name) / "ledger.db"
        self.relogio = Relogio()
        self.banco = Banco(self.caminho)
        self.addCleanup(self.banco.fechar)
        self.ledger = Ledger.sobre(self.banco, relogio=self.relogio)

    def cli(self, *argv, entrada=""):
        """Roda a Cli em processo e devolve (codigo, stdout)."""
        from erratum.cli import Cli
        saida = io.StringIO()
        cli = Cli(lambda: self.ledger, entrada=io.StringIO(entrada), saida=saida,
                  projeto_padrao=lambda: "acme")
        return cli.executar(list(argv)), saida.getvalue()
