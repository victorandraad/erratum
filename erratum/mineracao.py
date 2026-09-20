from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass

from erratum.dominio import Assinatura


def _sha256(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _texto_do_conteudo(conteudo):
    if isinstance(conteudo, str):
        return conteudo.strip()
    if isinstance(conteudo, list):
        partes = []
        for bloco in conteudo:
            if not isinstance(bloco, dict):
                continue
            texto = bloco.get("text")
            if isinstance(texto, str):
                partes.append(texto)
        return " ".join(partes).strip()
    return ""


@dataclass(frozen=True)
class ErroDeStream:
    ferramenta: str
    texto: str
    id_da_chamada: str


@dataclass(frozen=True)
class GrupoDeStream:
    assinatura: str
    ocorrencias: int
    execucoes: int
    ferramenta: str
    exemplo: str


@dataclass(frozen=True)
class RelatorioDeImportacao:
    lidos: int
    novos: int
    ignorados: int


class MineradorDeStream:
    def extrair(self, eventos):
        nomes = {}
        erros = []
        for evento in eventos:
            if not isinstance(evento, dict):
                continue
            mensagem = evento.get("message")
            if not isinstance(mensagem, dict):
                continue
            conteudo = mensagem.get("content")
            if not isinstance(conteudo, list):
                continue
            for bloco in conteudo:
                if not isinstance(bloco, dict):
                    continue
                tipo = bloco.get("type")
                if tipo == "tool_use":
                    id_uso = bloco.get("id")
                    if id_uso is not None:
                        nomes[id_uso] = bloco.get("name") or "?"
                elif tipo == "tool_result" and bloco.get("is_error"):
                    id_chamada = bloco.get("tool_use_id") or ""
                    erros.append(
                        ErroDeStream(
                            ferramenta=nomes.get(id_chamada, "?"),
                            texto=_texto_do_conteudo(bloco.get("content")),
                            id_da_chamada=id_chamada,
                        )
                    )
        return erros

    def agregar(self, execucoes):
        grupos = {}
        for id_exec, eventos in execucoes:
            for erro in self.extrair(eventos):
                assinatura = Assinatura(erro.texto).valor
                grupo = grupos.get(assinatura)
                if grupo is None:
                    grupo = {
                        "ocorrencias": 0,
                        "execucoes": set(),
                        "ferramentas": Counter(),
                        "exemplo": erro.texto,
                    }
                    grupos[assinatura] = grupo
                grupo["ocorrencias"] += 1
                grupo["execucoes"].add(id_exec)
                grupo["ferramentas"][erro.ferramenta] += 1
        resultado = []
        for assinatura, grupo in grupos.items():
            ferramenta = grupo["ferramentas"].most_common(1)[0][0]
            resultado.append(
                GrupoDeStream(
                    assinatura=assinatura,
                    ocorrencias=grupo["ocorrencias"],
                    execucoes=len(grupo["execucoes"]),
                    ferramenta=ferramenta,
                    exemplo=grupo["exemplo"],
                )
            )
        resultado.sort(
            key=lambda g: (g.execucoes, g.ocorrencias), reverse=True
        )
        return resultado


class ImportadorJsonl:
    def __init__(self, ledger):
        self._ledger = ledger

    def importar(self, linhas, projeto_padrao):
        lidos = 0
        novos = 0
        ignorados = 0
        for linha in linhas:
            if not isinstance(linha, str) or not linha.strip():
                continue
            try:
                dado = json.loads(linha)
            except json.JSONDecodeError:
                ignorados += 1
                continue
            if not isinstance(dado, dict):
                ignorados += 1
                continue
            texto = dado.get("text")
            if not isinstance(texto, str) or not texto:
                ignorados += 1
                continue
            lidos += 1
            contexto = {}
            task = dado.get("task")
            if task:
                contexto["task"] = task
            projeto = str(dado.get("project") or projeto_padrao)
            _erro, inserido = self._ledger.registrar_erro_importado(
                texto,
                projeto,
                tipo=dado.get("kind") or "error",
                etapa=dado.get("stage") or "",
                ferramenta=dado.get("tool") or "",
                contexto=contexto,
                chave_importacao="import:" + _sha256(
                    projeto + "\n" + linha.strip()
                ),
                ts=dado.get("ts") or None,
            )
            if inserido:
                novos += 1
        return RelatorioDeImportacao(
            lidos=lidos, novos=novos, ignorados=ignorados
        )
