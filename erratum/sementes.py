from __future__ import annotations

import json
from pathlib import Path

from erratum.receitas import Receita


class Semeador:
    def __init__(self, ledger, caminho=None):
        if caminho is None:
            caminho = Path(__file__).parent / "sementes.json"
        self._ledger = ledger
        self._caminho = Path(caminho)
        self._caminho_receitas = Path(__file__).parent / "receitas.json"

    def sementes(self):
        with open(self._caminho, encoding="utf-8") as fh:
            return json.load(fh)

    def receitas(self):
        with open(self._caminho_receitas, encoding="utf-8") as fh:
            return json.load(fh)

    def semear(self):
        novas = 0
        for semente in self.sementes():
            _gravado, inserido = self._ledger.registrar_semente(semente)
            if inserido:
                novas += 1
        return novas

    def semear_receitas(self):
        novas = 0
        for semente in self.receitas():
            receita = Receita(
                id=0,
                ts="",
                projeto="geral",
                nome=semente["slug"],
                quando=semente["quando"],
                comando=semente["comando"],
                notas=semente.get("notas") or "",
                perigo=semente.get("perigo"),
                em_vez_de=tuple(semente.get("em_vez_de") or ()),
                origem="semente",
            )
            chave = "semente-receita:%s" % semente["slug"]
            _gravado, inserido = self._ledger.inserir_semente_de_receita(
                receita, chave
            )
            if inserido:
                novas += 1
        return novas
