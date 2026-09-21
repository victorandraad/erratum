from __future__ import annotations

import json
from pathlib import Path


class Semeador:
    def __init__(self, ledger, caminho=None):
        if caminho is None:
            caminho = Path(__file__).parent / "sementes.json"
        self._ledger = ledger
        self._caminho = Path(caminho)

    def sementes(self):
        with open(self._caminho, encoding="utf-8") as fh:
            return json.load(fh)

    def semear(self):
        novas = 0
        for semente in self.sementes():
            _gravado, inserido = self._ledger.registrar_semente(semente)
            if inserido:
                novas += 1
        return novas
