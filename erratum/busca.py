from __future__ import annotations

from abc import ABC, abstractmethod

from erratum.dominio import Achado, Assinatura


class Buscador(ABC):
    @abstractmethod
    def buscar(self, texto, n):
        raise NotImplementedError


class BuscaPorAssinatura(Buscador):
    def __init__(self, erros, correcoes):
        self._erros = erros
        self._correcoes = correcoes

    def buscar(self, texto, n):
        valor = Assinatura(texto).valor
        erros = self._erros.por_assinatura(valor)
        correcoes = self._correcoes.por_assinatura(valor)
        if not erros and not correcoes:
            return []
        achado = Achado(
            origem="assinatura",
            assinatura=valor,
            texto=erros[0].texto if erros else "",
            correcoes=tuple(correcoes),
            pontuacao=1.0,
        )
        return [achado][:n]
