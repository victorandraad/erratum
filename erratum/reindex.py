from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from erratum.dominio import Assinatura


@dataclass(frozen=True)
class ResultadoDeReindex:
    antes: int
    depois: int
    erros_alterados: int
    correcoes_alteradas: int
    simulado: bool
    versao: int


class Reindexador:
    def __init__(self, banco):
        self._banco = banco

    def rodar(self, simular=False):
        with self._banco.transacao() as con:
            antes = self._distintas(con)
            erros = list(con.execute("SELECT id, signature, text FROM errors"))
            fixes = list(
                con.execute("SELECT id, signature, import_key FROM fixes")
            )
            fts_semente = {
                (l["src"] or "").split(":", 1)[-1]: l["text"]
                for l in con.execute(
                    "SELECT src, text FROM ledger_fts WHERE src LIKE 'seed:%'"
                )
            }
            mapa = self._mapa_de_erros(erros)
            novas_erros = []
            erros_alterados = 0
            for e in erros:
                nova = Assinatura(e["text"]).valor
                novas_erros.append((e["id"], nova))
                if nova != e["signature"]:
                    erros_alterados += 1
            novas_fixes = []
            correcoes_alteradas = 0
            for f in fixes:
                nova = self._nova_da_correcao(f, fts_semente, mapa)
                novas_fixes.append((f["id"], nova))
                if nova != f["signature"]:
                    correcoes_alteradas += 1
            depois = len(
                {n for _, n in novas_erros} | {n for _, n in novas_fixes}
            )
            if not simular:
                for id_, nova in novas_erros:
                    con.execute(
                        "UPDATE errors SET signature = ? WHERE id = ?",
                        (nova, id_),
                    )
                for id_, nova in novas_fixes:
                    con.execute(
                        "UPDATE fixes SET signature = ? WHERE id = ?",
                        (nova, id_),
                    )
                self._reconstruir_fts(con)
                con.execute(
                    "INSERT OR REPLACE INTO meta(key, value)"
                    " VALUES ('regra_assinatura', ?)",
                    (str(Assinatura.VERSAO),),
                )
            return ResultadoDeReindex(
                antes=antes,
                depois=depois,
                erros_alterados=erros_alterados,
                correcoes_alteradas=correcoes_alteradas,
                simulado=simular,
                versao=Assinatura.VERSAO,
            )

    def _distintas(self, con):
        linhas = con.execute(
            "SELECT signature FROM errors"
            " UNION SELECT signature FROM fixes"
        )
        return len(list(linhas))

    def _mapa_de_erros(self, erros):
        por_antiga = {}
        for e in erros:
            por_antiga.setdefault(e["signature"], []).append(
                Assinatura(e["text"]).valor
            )
        return {
            antiga: Counter(novas).most_common(1)[0][0]
            for antiga, novas in por_antiga.items()
        }

    def _nova_da_correcao(self, fix, fts_semente, mapa):
        chave = fix["import_key"] or ""
        if chave.startswith("semente:"):
            slug = chave.split(":", 1)[-1]
            texto = fts_semente.get(slug)
            if texto:
                return Assinatura(texto).valor
        antiga = fix["signature"]
        if antiga in mapa:
            return mapa[antiga]
        return Assinatura(antiga).valor

    def _reconstruir_fts(self, con, *a, **k):
        sementes = {}
        for linha in con.execute(
            "SELECT text, note, src FROM ledger_fts WHERE src LIKE 'seed:%'"
        ):
            sementes[linha["src"]] = (linha["text"], linha["note"])
        con.execute("DELETE FROM ledger_fts")
        for linha in con.execute("SELECT id, signature, text FROM errors"):
            con.execute(
                "INSERT INTO ledger_fts(signature, text, note, src)"
                " VALUES (?, ?, ?, ?)",
                (
                    linha["signature"],
                    linha["text"],
                    "",
                    "error:%d" % linha["id"],
                ),
            )
        for linha in con.execute(
            "SELECT id, signature, note, import_key FROM fixes"
        ):
            chave = linha["import_key"] or ""
            if chave.startswith("semente:"):
                slug = chave.split(":", 1)[-1]
                src = "seed:%s" % slug
                texto, _nota = sementes.get(src, ("", ""))
                con.execute(
                    "INSERT INTO ledger_fts(signature, text, note, src)"
                    " VALUES (?, ?, ?, ?)",
                    (linha["signature"], texto, linha["note"], src),
                )
            else:
                con.execute(
                    "INSERT INTO ledger_fts(signature, text, note, src)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        linha["signature"],
                        "",
                        linha["note"],
                        "fix:%d" % linha["id"],
                    ),
                )
