from __future__ import annotations

import re
import shlex
import sqlite3
import subprocess
import sys
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


class BuscaFTS(Buscador):
    _TOKEN = re.compile(r"\w{3,}")

    def __init__(self, banco, correcoes):
        self._banco = banco
        self._correcoes = correcoes

    @staticmethod
    def consulta(texto):
        vistos = set()
        tokens = []
        for tok in BuscaFTS._TOKEN.findall((texto or "").lower()):
            if tok in vistos:
                continue
            vistos.add(tok)
            tokens.append(tok)
            if len(tokens) == 12:
                break
        return " OR ".join('"%s"' % t for t in tokens)

    def buscar(self, texto, n):
        consulta = self.consulta(texto)
        if not consulta:
            return []
        try:
            linhas = self._banco.consultar(
                """
                SELECT signature, text, bm25(ledger_fts) AS rank
                FROM ledger_fts
                WHERE ledger_fts MATCH ?
                ORDER BY rank, rowid
                """,
                (consulta,),
            )
        except sqlite3.OperationalError:
            # FTS5 rejeita consulta malformada; o contrato e devolver vazio
            return []
        grupos = []
        indice = {}
        for linha in linhas:
            assinatura = linha["signature"] or ""
            texto_linha = linha["text"] or ""
            if assinatura not in indice:
                indice[assinatura] = len(grupos)
                grupos.append(
                    {
                        "assinatura": assinatura,
                        "pontuacao": linha["rank"],
                        "texto": texto_linha,
                    }
                )
                continue
            grupo = grupos[indice[assinatura]]
            if not grupo["texto"] and texto_linha:
                grupo["texto"] = texto_linha
        achados = []
        for grupo in grupos[:n]:
            pontuacao = grupo["pontuacao"]
            achados.append(
                Achado(
                    origem="fts",
                    assinatura=grupo["assinatura"],
                    texto=grupo["texto"],
                    correcoes=tuple(
                        self._correcoes.por_assinatura(grupo["assinatura"])
                    ),
                    pontuacao=0.0 if pontuacao is None else float(pontuacao),
                )
            )
        return achados


class BuscaExterna(Buscador):
    def __init__(self, comando, aviso=None, timeout=10):
        self._comando = comando
        self._aviso = sys.stderr if aviso is None else aviso
        self.timeout = timeout

    def buscar(self, texto, n):
        try:
            comando = self._comando or ""
            if not comando.strip():
                self._avisar("comando vazio")
                return []
            proc = subprocess.run(
                shlex.split(comando) + [texto],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0:
                self._avisar("codigo %s" % proc.returncode)
                return []
            achados = []
            for linha in proc.stdout.splitlines():
                if not linha:
                    continue
                achados.append(
                    Achado(
                        origem="external",
                        assinatura=Assinatura(linha).valor,
                        texto=linha,
                        correcoes=(),
                        pontuacao=0.0,
                    )
                )
                if len(achados) >= n:
                    break
            return achados
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            self._avisar(exc)
            return []

    def _avisar(self, motivo):
        texto = str(motivo).replace("\n", " ")
        self._aviso.write("busca externa falhou: %s\n" % texto)


class BuscaEmCascata(Buscador):
    def __init__(self, buscadores):
        self._buscadores = list(buscadores)

    def buscar(self, texto, n):
        vistos = set()
        resultado = []
        for buscador in self._buscadores:
            if len(resultado) >= n:
                return resultado
            for achado in buscador.buscar(texto, n + len(vistos)):
                if achado.assinatura in vistos:
                    continue
                vistos.add(achado.assinatura)
                resultado.append(achado)
                if len(resultado) >= n:
                    return resultado
        return resultado
