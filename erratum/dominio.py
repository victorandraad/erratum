from __future__ import annotations

import re
from dataclasses import dataclass


class Assinatura:
    _RODADA = re.compile(r"\(rodada \d+(?:/\d+)?\)")
    # o ':' depois do caminho precisa permanecer (mensagens "arquivo: motivo")
    _CAMINHO = re.compile(r"/[^\s\"':]+")
    _DIGITOS = re.compile(r"\d+")

    def __init__(self, texto):
        self._valor = self._normalizar(texto)

    @classmethod
    def ja_normalizada(cls, valor):
        obj = cls.__new__(cls)
        obj._valor = valor
        return obj

    @property
    def valor(self):
        return self._valor

    def __str__(self):
        return self._valor

    def __eq__(self, other):
        if not isinstance(other, Assinatura):
            return NotImplemented
        return self._valor == other._valor

    def __hash__(self):
        return hash(self._valor)

    @classmethod
    def _normalizar(cls, texto):
        if texto is None:
            texto = ""
        texto = texto.strip().lower()
        texto = texto.replace("\n", " ")
        texto = cls._RODADA.sub("", texto)
        texto = cls._CAMINHO.sub("/PATH", texto)
        texto = cls._DIGITOS.sub("N", texto)
        texto = " ".join(texto.split())
        texto = texto[:120]
        if not texto:
            return "(sem texto)"
        return texto


@dataclass(frozen=True)
class Erro:
    id: int
    ts: str
    projeto: str
    tipo: str
    etapa: str
    ferramenta: str
    assinatura: str
    texto: str
    contexto: dict


@dataclass(frozen=True)
class Correcao:
    id: int
    ts: str
    projeto: str
    assinatura: str
    nota: str
    ref: str
    teste: str
    fonte: str


@dataclass(frozen=True)
class Acerto:
    id: int
    ts: str
    projeto: str
    task: str
    o_que: str
    custo_usd: float
    contexto: dict


@dataclass(frozen=True)
class VereditoDePortao:
    id: int
    ts: str
    projeto: str
    portao: str
    veredito: str
    detalhe: str


@dataclass(frozen=True)
class Padrao:
    assinatura: str
    ocorrencias: int
    tasks: int
    projetos: tuple
    ultimo_ts: str
    exemplo: str
    resolvido: bool


@dataclass(frozen=True)
class Achado:
    origem: str
    assinatura: str
    texto: str
    correcoes: tuple
    pontuacao: float
