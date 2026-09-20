from __future__ import annotations

import json
from dataclasses import replace

from erratum.dominio import Correcao, Erro, VereditoDePortao


class RepositorioDeErros:
    def __init__(self, banco):
        self._banco = banco

    def inserir(self, erro, chave_importacao=None):
        if chave_importacao:
            existente = self._por_chave(chave_importacao)
            if existente is not None:
                return existente
        contexto_json = json.dumps(erro.contexto or {}, ensure_ascii=False)
        with self._banco.transacao() as con:
            if chave_importacao:
                linha = con.execute(
                    "SELECT * FROM errors WHERE import_key = ?",
                    (chave_importacao,),
                ).fetchone()
                if linha is not None:
                    return self._de_linha(linha)
            cur = con.execute(
                """
                INSERT INTO errors(
                    ts, project, kind, stage, tool, signature, text,
                    context_json, import_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    erro.ts,
                    erro.projeto,
                    erro.tipo,
                    erro.etapa,
                    erro.ferramenta,
                    erro.assinatura,
                    erro.texto,
                    contexto_json,
                    chave_importacao,
                ),
            )
            novo_id = cur.lastrowid
            con.execute(
                """
                INSERT INTO ledger_fts(signature, text, note, src)
                VALUES (?, ?, ?, ?)
                """,
                (erro.assinatura, erro.texto, "", "error:%d" % novo_id),
            )
        return replace(erro, id=novo_id)

    def por_id(self, id_erro):
        linhas = self._banco.consultar(
            "SELECT * FROM errors WHERE id = ?", (id_erro,)
        )
        if not linhas:
            return None
        return self._de_linha(linhas[0])

    def por_assinatura(self, assinatura):
        linhas = self._banco.consultar(
            "SELECT * FROM errors WHERE signature = ? ORDER BY id",
            (assinatura,),
        )
        return [self._de_linha(l) for l in linhas]

    def _por_chave(self, chave):
        linhas = self._banco.consultar(
            "SELECT * FROM errors WHERE import_key = ?", (chave,)
        )
        if not linhas:
            return None
        return self._de_linha(linhas[0])

    def _de_linha(self, linha):
        bruto = linha["context_json"]
        contexto = json.loads(bruto) if bruto else {}
        return Erro(
            id=linha["id"],
            ts=linha["ts"] or "",
            projeto=linha["project"] or "",
            tipo=linha["kind"] or "",
            etapa=linha["stage"] or "",
            ferramenta=linha["tool"] or "",
            assinatura=linha["signature"] or "",
            texto=linha["text"] or "",
            contexto=contexto,
        )


class RepositorioDeCorrecoes:
    def __init__(self, banco):
        self._banco = banco

    def inserir(self, correcao, chave_importacao=None):
        if chave_importacao:
            existente = self._por_chave(chave_importacao)
            if existente is not None:
                return existente
        with self._banco.transacao() as con:
            if chave_importacao:
                linha = con.execute(
                    "SELECT * FROM fixes WHERE import_key = ?",
                    (chave_importacao,),
                ).fetchone()
                if linha is not None:
                    return self._de_linha(linha)
            cur = con.execute(
                """
                INSERT INTO fixes(
                    ts, project, signature, note, ref, test, source, import_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correcao.ts,
                    correcao.projeto,
                    correcao.assinatura,
                    correcao.nota,
                    correcao.ref,
                    correcao.teste,
                    correcao.fonte,
                    chave_importacao,
                ),
            )
            novo_id = cur.lastrowid
            con.execute(
                """
                INSERT INTO ledger_fts(signature, text, note, src)
                VALUES (?, ?, ?, ?)
                """,
                (correcao.assinatura, "", correcao.nota, "fix:%d" % novo_id),
            )
        return replace(correcao, id=novo_id)

    def por_assinatura(self, assinatura):
        linhas = self._banco.consultar(
            "SELECT * FROM fixes WHERE signature = ? ORDER BY id",
            (assinatura,),
        )
        return [self._de_linha(l) for l in linhas]

    def _por_chave(self, chave):
        linhas = self._banco.consultar(
            "SELECT * FROM fixes WHERE import_key = ?", (chave,)
        )
        if not linhas:
            return None
        return self._de_linha(linhas[0])

    def _de_linha(self, linha):
        return Correcao(
            id=linha["id"],
            ts=linha["ts"] or "",
            projeto=linha["project"] or "",
            assinatura=linha["signature"] or "",
            nota=linha["note"] or "",
            ref=linha["ref"] or "",
            teste=linha["test"] or "",
            fonte=linha["source"] or "",
        )


class RepositorioDePortoes:
    def __init__(self, banco):
        self._banco = banco

    def inserir(self, veredito):
        with self._banco.transacao() as con:
            cur = con.execute(
                """
                INSERT INTO gate_runs(ts, project, gate, verdict, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    veredito.ts,
                    veredito.projeto,
                    veredito.portao,
                    veredito.veredito,
                    veredito.detalhe,
                ),
            )
            return replace(veredito, id=cur.lastrowid)
