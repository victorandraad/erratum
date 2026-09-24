from __future__ import annotations

import math
import re
import shlex
import sqlite3
import subprocess
import sys
import unicodedata
from abc import ABC, abstractmethod

from erratum.dominio import Achado, Assinatura
from erratum.idioma import t


def _dobrar(texto):
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


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
            veredito="match",
            confianca=1.0,
            decidido_por="assinatura",
        )
        return [achado][:n]


class BuscaFTS(Buscador):
    _TOKEN = re.compile(r"\w{3,}")

    def __init__(self, banco, correcoes, tabela="ledger_fts", montar=None):
        self._banco = banco
        self._correcoes = correcoes
        self._tabela = tabela
        self._montar = montar

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

    def _termos(self, texto):
        vistos = set()
        termos = []
        for tok in self._TOKEN.findall(_dobrar(texto)):
            if tok in vistos:
                continue
            vistos.add(tok)
            termos.append(tok)
            if len(termos) == 12:
                break
        return termos

    def _idf(self, termos):
        vocab = "voc_" + self._tabela
        self._banco.consultar(
            "CREATE VIRTUAL TABLE IF NOT EXISTS temp.%s "
            "USING fts5vocab(main, %s, 'row')" % (vocab, self._tabela)
        )
        n_docs = self._banco.consultar(
            "SELECT COUNT(*) AS n FROM %s" % self._tabela
        )
        N = int(n_docs[0]["n"] if n_docs else 0)
        idfs = {}
        for termo in termos:
            linhas = self._banco.consultar(
                "SELECT doc FROM temp.%s WHERE term = ?" % vocab, (termo,)
            )
            n = int(linhas[0]["doc"]) if linhas else 0
            idfs[termo] = math.log((N - n + 0.5) / (n + 0.5) + 1.0)
        return idfs

    @staticmethod
    def _cobertura(linha, termos, idfs):
        if not termos:
            return 0.0
        denom = sum(idfs[t] for t in termos)
        if denom <= 0:
            return 0.0
        tokens = set(re.findall(r"\w+", _dobrar(linha)))
        num = sum(idfs[t] for t in termos if t in tokens)
        return num / denom

    def buscar(self, texto, n):
        consulta = self.consulta(texto)
        if not consulta:
            return []
        termos = self._termos(texto)
        try:
            idfs = self._idf(termos)
            tabela = self._tabela
            linhas = self._banco.consultar(
                """
                SELECT signature, text, note, src, bm25(%s) AS rank
                FROM %s
                WHERE %s MATCH ?
                ORDER BY rank, rowid
                """
                % (tabela, tabela, tabela),
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
            nota = linha["note"] or ""
            corpo = " ".join((assinatura, texto_linha, nota))
            cob = self._cobertura(corpo, termos, idfs)
            if assinatura not in indice:
                indice[assinatura] = len(grupos)
                grupos.append(
                    {
                        "assinatura": assinatura,
                        "pontuacao": linha["rank"],
                        "texto": texto_linha,
                        "cobertura": cob,
                        "src": linha["src"] or "",
                        "note": nota,
                    }
                )
                continue
            grupo = grupos[indice[assinatura]]
            if cob > grupo["cobertura"]:
                grupo["cobertura"] = cob
            if not grupo["texto"] and texto_linha:
                grupo["texto"] = texto_linha
        achados = []
        for grupo in grupos[:n]:
            achado = self._achado_de(grupo)
            if achado is not None:
                achados.append(achado)
        return achados

    def _achado_de(self, grupo):
        if self._montar is not None:
            return self._montar(grupo)
        pontuacao = grupo["pontuacao"]
        return Achado(
            origem="fts",
            assinatura=grupo["assinatura"],
            texto=grupo["texto"],
            correcoes=tuple(
                self._correcoes.por_assinatura(grupo["assinatura"])
            ),
            pontuacao=0.0 if pontuacao is None else float(pontuacao),
            cobertura=grupo["cobertura"],
        )


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
        self._aviso.write(t("external search failed: %s\n", "busca externa falhou: %s\n") % texto)


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
