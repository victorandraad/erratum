from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from erratum.busca import BuscaEmCascata, BuscaExterna, BuscaFTS, BuscaPorAssinatura
from erratum.decisao import Decisao, JuizExterno, Limiar
from erratum.dominio import Acerto, Assinatura, Correcao, Erro, VereditoDePortao
from erratum.reindex import Reindexador
from erratum.repositorios import (
    RepositorioDeAcertos,
    RepositorioDeCorrecoes,
    RepositorioDeErros,
    RepositorioDePistas,
    RepositorioDePortoes,
)


class ErroNaoEncontrado(Exception):
    pass


def _agora_utc():
    return datetime.now(timezone.utc)


class Ledger:
    def __init__(
        self,
        erros,
        correcoes,
        portoes,
        acertos,
        buscador,
        relogio,
        reindexador=None,
        banco=None,
        limiar=None,
        juiz=None,
        pistas=None,
    ):
        self._erros = erros
        self._correcoes = correcoes
        self._portoes = portoes
        self._acertos = acertos
        self._buscador = buscador
        self._relogio = relogio
        self._reindexador = reindexador
        self._banco = banco
        self._limiar = limiar if limiar is not None else Limiar()
        self._juiz = juiz
        self._pistas = pistas

    @classmethod
    def sobre(
        cls,
        banco,
        relogio=None,
        ambiente=None,
        aviso=None,
        limiar=None,
        juiz=None,
    ):
        if relogio is None:
            relogio = _agora_utc
        if ambiente is None:
            ambiente = os.environ
        erros = RepositorioDeErros(banco)
        correcoes = RepositorioDeCorrecoes(banco)
        portoes = RepositorioDePortoes(banco)
        acertos = RepositorioDeAcertos(banco)
        pistas = RepositorioDePistas(banco)
        buscadores = [
            BuscaPorAssinatura(erros, correcoes),
            BuscaFTS(banco, correcoes),
        ]
        cmd = ambiente.get("ERRATUM_SEARCH_CMD", "").strip()
        if cmd:
            buscadores.append(BuscaExterna(cmd, aviso=aviso))
        buscador = BuscaEmCascata(buscadores)
        if limiar is None:
            limiar = Limiar.do_ambiente(ambiente, aviso)
        if juiz is None:
            juiz_cmd = ambiente.get("ERRATUM_JUDGE_CMD", "").strip()
            if juiz_cmd:
                juiz = JuizExterno(juiz_cmd, aviso=aviso)
        return cls(
            erros,
            correcoes,
            portoes,
            acertos,
            buscador,
            relogio,
            reindexador=Reindexador(banco),
            banco=banco,
            limiar=limiar,
            juiz=juiz,
            pistas=pistas,
        )

    def regra_desatualizada(self):
        if self._banco is None:
            return True
        versao = self._banco.versao_da_regra()
        return versao is None or versao < Assinatura.VERSAO

    def reindexar(self, simular=False):
        reindexador = self._reindexador
        if reindexador is None:
            reindexador = Reindexador(self._banco)
        return reindexador.rodar(simular=simular)

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
        task="",
    ):
        contexto = dict(contexto) if contexto else {}
        if not task:
            task = contexto.get("task") or ""
        elif not contexto.get("task"):
            contexto["task"] = task
        decisao = None
        pistas = []
        if com_pistas:
            decisao = self.decidir(texto, so_resolvidos=True)
            pistas = list(decisao.achados)
        erro = self._montar_erro(
            texto, projeto, tipo, etapa, ferramenta, contexto, ts
        )
        gravado = self._erros.inserir(erro, chave_importacao=chave_importacao)
        if com_pistas:
            self._gravar_pistas(decisao, projeto, task, erro_id=gravado.id)
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

    def _candidatos(self, texto, n, so_resolvidos):
        pedido = n + 1
        while True:
            brutos = self._buscador.buscar(texto, pedido)
            if not so_resolvidos:
                return brutos
            filtrados = [a for a in brutos if a.correcoes]
            if len(filtrados) >= n + 1 or len(brutos) < pedido:
                return filtrados
            pedido *= 2

    def decidir(self, texto, n=5, so_resolvidos=False):
        brutos = self._candidatos(texto, n, so_resolvidos)
        classificados = self._limiar.classificar(brutos)
        if self._juiz is not None:
            classificados = self._juiz.julgar(
                texto, Assinatura(texto).valor, classificados
            )
        return Decisao.de(list(classificados)[:n])

    def buscar(self, texto, n=5, so_resolvidos=False):
        return list(self.decidir(texto, n=n, so_resolvidos=so_resolvidos).achados)

    def correcoes_de(self, assinatura):
        if isinstance(assinatura, Assinatura):
            assinatura = assinatura.valor
        return self._correcoes.por_assinatura(assinatura)

    def _assinatura_do_alvo(self, alvo):
        if isinstance(alvo, int):
            erro = self._erros.por_id(alvo)
            if erro is None:
                raise ErroNaoEncontrado(alvo)
            return erro.assinatura
        return Assinatura(alvo).valor

    def _montar_correcao(self, alvo, nota, projeto, ref, teste, fonte, ts):
        return Correcao(
            id=0,
            ts=self._ts() if ts is None else ts,
            projeto=projeto,
            assinatura=self._assinatura_do_alvo(alvo),
            nota=nota,
            ref=ref,
            teste=teste,
            fonte=fonte,
        )

    def registrar_correcao(
        self,
        alvo,
        nota,
        projeto,
        ref="",
        teste="",
        fonte="manual",
        chave_importacao=None,
        ts=None,
        task="",
    ):
        correcao = self._montar_correcao(
            alvo, nota, projeto, ref, teste, fonte, ts
        )
        gravado = self._correcoes.inserir(
            correcao, chave_importacao=chave_importacao
        )
        if task:
            self.registrar_desfecho(task, "resolveu", projeto=projeto)
        return gravado

    def registrar_semente(self, semente):
        slug = semente["slug"]
        erro = semente["erro"]
        chave = "semente:%s" % slug
        nota = "%s\nCausa: %s\nPrevenção: %s" % (
            semente["correcao"],
            semente["causa"],
            semente["prevencao"],
        )
        correcao = Correcao(
            id=0,
            ts=self._ts(),
            projeto="geral",
            assinatura=Assinatura(erro).valor,
            nota=nota,
            ref=chave,
            teste="",
            fonte="semente",
        )
        return self._correcoes.inserir_semente(correcao, erro, chave)

    def registrar_correcao_importada(
        self,
        alvo,
        nota,
        projeto,
        ref="",
        teste="",
        fonte="manual",
        chave_importacao=None,
        ts=None,
    ):
        correcao = self._montar_correcao(
            alvo, nota, projeto, ref, teste, fonte, ts
        )
        return self._correcoes.inserir_se_novo(
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
            return (p.resolvido, -max(p.tasks, 1), -p.ocorrencias, p.assinatura)

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
        if task:
            self.registrar_desfecho(task, "resolveu", projeto=projeto)
        return gravado, self.streak(projeto)

    def streak(self, projeto):
        return self._acertos.contar_desde(
            projeto, self._erros.ultimo_ts(projeto)
        )

    def registrar_pistas_de_consulta(
        self, texto, projeto, task="", n=5, so_resolvidos=False
    ):
        decisao = self.decidir(texto, n=n, so_resolvidos=so_resolvidos)
        self._gravar_pistas(decisao, projeto, task, erro_id=None)
        return decisao

    def registrar_desfecho(self, task, desfecho, projeto=None):
        if self._pistas is None:
            raise ValueError("sem repositorio de pistas")
        return self._pistas.fechar(task, desfecho, self._ts(), projeto=projeto)

    def _origem_da_pista(self, achado):
        primeira = achado.correcoes[0] if achado.correcoes else None
        if primeira is not None and primeira.fonte == "semente":
            return "semente"
        if achado.decidido_por == "juiz":
            return "juiz"
        if achado.origem == "external":
            return "externa"
        return achado.origem

    def _gravar_pistas(self, decisao, projeto, task, erro_id):
        if self._pistas is None:
            return
        ts = self._ts()
        linhas = []
        if decisao.veredito == "abstain":
            linhas.append(
                {
                    "ts": ts,
                    "project": projeto,
                    "task": task or "",
                    "erro_id": erro_id,
                    "correcao_id": None,
                    "origem": "",
                    "veredito": "abstain",
                    "confianca": 0.0,
                    "desfecho": None,
                    "desfecho_ts": None,
                }
            )
        else:
            achados = [a for a in decisao.achados if a.origem != "assinatura"]
            achados += [a for a in decisao.achados if a.origem == "assinatura"]
            for achado in achados:
                primeira = achado.correcoes[0] if achado.correcoes else None
                linhas.append(
                    {
                        "ts": ts,
                        "project": projeto,
                        "task": task or "",
                        "erro_id": erro_id,
                        "correcao_id": primeira.id if primeira is not None else None,
                        "origem": self._origem_da_pista(achado),
                        "veredito": achado.veredito,
                        "confianca": achado.confianca,
                        "desfecho": None,
                        "desfecho_ts": None,
                    }
                )
        self._pistas.inserir_varias(linhas)

    def efeito(self, projeto=None, dias=None):
        desde = None
        if dias is not None:
            desde = (self._relogio() - timedelta(days=dias)).isoformat(
                timespec="microseconds"
            )
        linhas = []
        if self._pistas is not None:
            linhas = [dict(l) for l in self._pistas.listar(projeto, desde)]
        return _agregar_efeito(linhas)


def _agregar(items):
    n = len(items)
    com = [x for x in items if x.get("desfecho")]
    res = [x for x in com if x.get("desfecho") == "resolveu"]
    taxa = (len(res) / len(com)) if com else None
    return n, len(com), len(res), taxa


def _quebra(linhas, chave):
    grupos = defaultdict(list)
    for linha in linhas:
        grupos[linha.get(chave) or ""].append(linha)
    saida = []
    for nome in sorted(grupos):
        n, com, res, taxa = _agregar(grupos[nome])
        saida.append(
            {
                chave: nome,
                "pistas": n,
                "com_desfecho": com,
                "resolveu": res,
                "taxa": taxa,
            }
        )
    return saida


def _desfecho_da_task(items):
    fechadas = [x for x in items if x.get("desfecho")]
    if not fechadas:
        return None
    return max(fechadas, key=lambda x: x.get("desfecho_ts") or "")["desfecho"]


def _grupo_task(nome, recs):
    n = len(recs)
    com = [x for x in recs if x.get("desfecho")]
    res = [x for x in com if x.get("desfecho") == "resolveu"]
    return {
        "grupo": nome,
        "n": n,
        "com_desfecho": len(com),
        "resolveu": len(res),
        "taxa": (len(res) / len(com)) if com else None,
        "amostra_pequena": n < 30,
    }


def _agregar_efeito(linhas):
    por_task = defaultdict(list)
    for linha in linhas:
        task = linha.get("task") or ""
        if task:
            por_task[(linha.get("project") or "", task)].append(linha)
    match_tasks = []
    abstain_tasks = []
    geral_tasks = []
    for items in por_task.values():
        rec = {"desfecho": _desfecho_da_task(items)}
        geral_tasks.append(rec)
        if any(x.get("veredito") == "match" for x in items):
            match_tasks.append(rec)
        elif items and all(x.get("veredito") == "abstain" for x in items):
            abstain_tasks.append(rec)
    return {
        "por_origem": _quebra(linhas, "origem"),
        "por_veredito": _quebra(linhas, "veredito"),
        "tasks": [
            _grupo_task("match", match_tasks),
            _grupo_task("abstain", abstain_tasks),
            _grupo_task("geral", geral_tasks),
        ],
    }
