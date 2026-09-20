from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from erratum.dominio import Acerto, Correcao, Erro, Padrao, TaxaDePortao, VereditoDePortao


class RepositorioDeErros:
    def __init__(self, banco):
        self._banco = banco

    def inserir(self, erro, chave_importacao=None):
        gravado, _inserido = self.inserir_se_novo(erro, chave_importacao)
        return gravado

    def inserir_se_novo(self, erro, chave_importacao=None):
        if chave_importacao:
            existente = self._por_chave(chave_importacao)
            if existente is not None:
                return existente, False
        contexto_json = json.dumps(erro.contexto or {}, ensure_ascii=False)
        try:
            with self._banco.transacao() as con:
                if chave_importacao:
                    linha = con.execute(
                        "SELECT * FROM errors WHERE import_key = ?",
                        (chave_importacao,),
                    ).fetchone()
                    if linha is not None:
                        return self._de_linha(linha), False
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
            return replace(erro, id=novo_id), True
        except sqlite3.IntegrityError:
            if not chave_importacao:
                raise
            existente = self._por_chave(chave_importacao)
            if existente is None:
                raise
            return existente, False

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

    def ultimo_ts(self, projeto):
        linhas = self._banco.consultar(
            "SELECT MAX(ts) AS ts FROM errors WHERE project = ?",
            (projeto,),
        )
        if not linhas:
            return None
        return linhas[0]["ts"]

    def agrupar(self, projeto=None, desde_ts=None):
        condicoes = []
        params = []
        if projeto is not None:
            condicoes.append("project = ?")
            params.append(projeto)
        if desde_ts is not None:
            condicoes.append("ts >= ?")
            params.append(desde_ts)
        where = ""
        if condicoes:
            where = " WHERE " + " AND ".join(condicoes)
        sql = (
            """
            SELECT
                signature AS assinatura,
                COUNT(*) AS ocorrencias,
                COUNT(
                    DISTINCT NULLIF(json_extract(context_json, '$.task'), '')
                ) AS tasks,
                GROUP_CONCAT(DISTINCT project) AS projetos,
                MAX(ts) AS ultimo_ts,
                MAX(text) AS exemplo,
                EXISTS(
                    SELECT 1 FROM fixes
                    WHERE fixes.signature = errors.signature
                ) AS resolvido
            FROM errors
            """
            + where
            + " GROUP BY signature"
        )
        linhas = self._banco.consultar(sql, tuple(params))
        return [self._padrao_de_linha(l) for l in linhas]

    def _padrao_de_linha(self, linha):
        bruto = linha["projetos"] or ""
        projetos = tuple(p for p in bruto.split(",") if p)
        return Padrao(
            assinatura=linha["assinatura"] or "",
            ocorrencias=int(linha["ocorrencias"] or 0),
            tasks=int(linha["tasks"] or 0),
            projetos=projetos,
            ultimo_ts=linha["ultimo_ts"] or "",
            exemplo=linha["exemplo"] or "",
            resolvido=bool(linha["resolvido"]),
        )

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


class RepositorioDeAcertos:
    def __init__(self, banco):
        self._banco = banco

    def inserir(self, acerto):
        contexto_json = json.dumps(acerto.contexto or {}, ensure_ascii=False)
        with self._banco.transacao() as con:
            cur = con.execute(
                """
                INSERT INTO wins(
                    ts, project, task, what, cost_usd, context_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    acerto.ts,
                    acerto.projeto,
                    acerto.task,
                    acerto.o_que,
                    acerto.custo_usd,
                    contexto_json,
                ),
            )
            return replace(acerto, id=cur.lastrowid)

    def contar_desde(self, projeto, ts=None):
        if ts is None:
            linhas = self._banco.consultar(
                "SELECT COUNT(*) AS n FROM wins WHERE project = ?",
                (projeto,),
            )
        else:
            linhas = self._banco.consultar(
                "SELECT COUNT(*) AS n FROM wins WHERE project = ? AND ts > ?",
                (projeto, ts),
            )
        return int(linhas[0]["n"] if linhas else 0)


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

    def taxas(self, projeto=None, desde_ts=None):
        condicoes = []
        params = []
        if projeto is not None:
            condicoes.append("project = ?")
            params.append(projeto)
        if desde_ts is not None:
            condicoes.append("ts >= ?")
            params.append(desde_ts)
        where = ""
        if condicoes:
            where = " WHERE " + " AND ".join(condicoes)
        sql = (
            """
            SELECT
                gate AS portao,
                COUNT(*) AS rodadas,
                SUM(CASE WHEN verdict = 'reprovou' THEN 1 ELSE 0 END)
                    AS reprovou,
                SUM(CASE WHEN verdict = 'pulou' THEN 1 ELSE 0 END) AS pulou
            FROM gate_runs
            """
            + where
            + " GROUP BY gate"
        )
        linhas = self._banco.consultar(sql, tuple(params))
        return [self._taxa_de_linha(l) for l in linhas]

    def _taxa_de_linha(self, linha):
        rodadas = int(linha["rodadas"] or 0)
        reprovou = int(linha["reprovou"] or 0)
        pulou = int(linha["pulou"] or 0)
        julgados = rodadas - pulou
        taxa = (reprovou / julgados) if julgados else 0.0
        return TaxaDePortao(
            portao=linha["portao"] or "",
            rodadas=rodadas,
            reprovou=reprovou,
            pulou=pulou,
            taxa=taxa,
        )
