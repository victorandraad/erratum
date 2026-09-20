from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from erratum.busca import BuscaEmCascata, BuscaExterna, BuscaFTS, BuscaPorAssinatura
from erratum.dominio import Acerto, Assinatura, Correcao, Erro, VereditoDePortao
from erratum.repositorios import (
    RepositorioDeAcertos,
    RepositorioDeCorrecoes,
    RepositorioDeErros,
    RepositorioDePortoes,
)


class ErroNaoEncontrado(Exception):
    pass


def _agora_utc():
    return datetime.now(timezone.utc)


class Ledger:
    def __init__(self, erros, correcoes, portoes, acertos, buscador, relogio):
        self._erros = erros
        self._correcoes = correcoes
        self._portoes = portoes
        self._acertos = acertos
        self._buscador = buscador
        self._relogio = relogio

    @classmethod
    def sobre(cls, banco, relogio=None, ambiente=None, aviso=None):
        if relogio is None:
            relogio = _agora_utc
        if ambiente is None:
            ambiente = os.environ
        erros = RepositorioDeErros(banco)
        correcoes = RepositorioDeCorrecoes(banco)
        portoes = RepositorioDePortoes(banco)
        acertos = RepositorioDeAcertos(banco)
        buscadores = [
            BuscaPorAssinatura(erros, correcoes),
            BuscaFTS(banco, correcoes),
        ]
        cmd = ambiente.get("ERRATUM_SEARCH_CMD", "").strip()
        if cmd:
            buscadores.append(BuscaExterna(cmd, aviso=aviso))
        buscador = BuscaEmCascata(buscadores)
        return cls(erros, correcoes, portoes, acertos, buscador, relogio)

    def _ts(self):
        return self._relogio().isoformat(timespec="microseconds")

    def registrar_erro(
        self,
        texto,
        projeto,
        tipo="error",
        etapa="",
        ferramenta="",
        contexto=None,
        chave_importacao=None,
        ts=None,
        com_pistas=True,
    ):
        pistas = []
        if com_pistas:
            pistas = [a for a in self.buscar(texto) if a.correcoes]
        erro = self._montar_erro(
            texto, projeto, tipo, etapa, ferramenta, contexto, ts
        )
        gravado = self._erros.inserir(erro, chave_importacao=chave_importacao)
        return gravado, pistas

    def registrar_erro_importado(
        self,
        texto,
        projeto,
        tipo="error",
        etapa="",
        ferramenta="",
        contexto=None,
        chave_importacao=None,
        ts=None,
    ):
        erro = self._montar_erro(
            texto, projeto, tipo, etapa, ferramenta, contexto, ts
        )
        return self._erros.inserir_se_novo(erro, chave_importacao=chave_importacao)

    def _montar_erro(self, texto, projeto, tipo, etapa, ferramenta, contexto, ts):
        return Erro(
            id=0,
            ts=self._ts() if ts is None else ts,
            projeto=projeto,
            tipo=tipo,
            etapa=etapa,
            ferramenta=ferramenta,
            assinatura=Assinatura(texto).valor,
            texto=texto,
            contexto=dict(contexto) if contexto else {},
        )

    def erro(self, id_erro):
        return self._erros.por_id(id_erro)

    def buscar(self, texto, n=5):
        return self._buscador.buscar(texto, n)

    def correcoes_de(self, assinatura):
        if isinstance(assinatura, Assinatura):
            assinatura = assinatura.valor
        return self._correcoes.por_assinatura(assinatura)

    def registrar_correcao(
        self,
        alvo,
        nota,
        projeto,
        ref="",
        teste="",
        fonte="manual",
        chave_importacao=None,
    ):
        if isinstance(alvo, int):
            erro = self._erros.por_id(alvo)
            if erro is None:
                raise ErroNaoEncontrado(alvo)
            valor = erro.assinatura
        else:
            valor = Assinatura(alvo).valor
        correcao = Correcao(
            id=0,
            ts=self._ts(),
            projeto=projeto,
            assinatura=valor,
            nota=nota,
            ref=ref,
            teste=teste,
            fonte=fonte,
        )
        return self._correcoes.inserir(
            correcao, chave_importacao=chave_importacao
        )

    def registrar_portao(self, portao, veredito, detalhe, projeto):
        item = VereditoDePortao(
            id=0,
            ts=self._ts(),
            projeto=projeto,
            portao=portao,
            veredito=veredito,
            detalhe=detalhe,
        )
        return self._portoes.inserir(item)

    def o_que_repete(self, projeto, dias=None, resolvidos=False):
        desde = None
        if dias is not None:
            desde = (self._relogio() - timedelta(days=dias)).isoformat(
                timespec="microseconds"
            )
        padroes = self._erros.agrupar(projeto, desde)
        if not resolvidos:
            padroes = [p for p in padroes if not p.resolvido]

        def chave(p):
            peso = p.tasks if p.tasks > 0 else p.ocorrencias
            return (p.resolvido, -peso, -p.ocorrencias, p.assinatura)

        return sorted(padroes, key=chave)

    def taxa_de_portoes(self, projeto, dias=None):
        desde = None
        if dias is not None:
            desde = (self._relogio() - timedelta(days=dias)).isoformat(
                timespec="microseconds"
            )
        return self._portoes.taxas(projeto, desde)

    def registrar_acerto(
        self, o_que, projeto, task="", custo_usd=None, contexto=None
    ):
        acerto = Acerto(
            id=0,
            ts=self._ts(),
            projeto=projeto,
            task=task or "",
            o_que=o_que,
            custo_usd=custo_usd,
            contexto=dict(contexto) if contexto else {},
        )
        gravado = self._acertos.inserir(acerto)
        return gravado, self.streak(projeto)

    def streak(self, projeto):
        return self._acertos.contar_desde(
            projeto, self._erros.ultimo_ts(projeto)
        )
