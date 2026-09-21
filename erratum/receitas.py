from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace


# grupo que contem + * ou { e o proprio grupo e seguido de + * ou {
_QUANTIFICADOR_ANINHADO = re.compile(r"\([^()]*[+*{][^()]*\)[+*{]")
_PLACEHOLDER = re.compile(r"<[^<>\s]+>")
_OPCIONAL = re.compile(r" \[(?=-|<)")


@dataclass(frozen=True)
class Receita:
    id: int
    ts: str
    projeto: str
    nome: str
    quando: str
    comando: str
    notas: str
    perigo: str
    em_vez_de: tuple
    origem: str

    def comando_obrigatorio(self):
        return _OPCIONAL.split(self.comando or "", 1)[0]


@dataclass(frozen=True)
class ResultadoDeVerificacao:
    tipo: str
    receita: Receita


class GuardaDeRegex:
    TAMANHO_MAXIMO = 300

    def validar(self, padrao):
        if not isinstance(padrao, str):
            raise ValueError("regex invalida")
        if len(padrao) > self.TAMANHO_MAXIMO:
            raise ValueError("regex longa demais")
        try:
            re.compile(padrao)
        except re.error as e:
            raise ValueError("regex invalida") from e
        if _QUANTIFICADOR_ANINHADO.search(padrao):
            raise ValueError("quantificador aninhado")


class RepositorioDeReceitas:
    def __init__(self, banco, guarda=None):
        self._banco = banco
        self._guarda = guarda if guarda is not None else GuardaDeRegex()

    def salvar(self, receita):
        for padrao in receita.em_vez_de:
            self._guarda.validar(padrao)
        em_vez = json.dumps(list(receita.em_vez_de), ensure_ascii=False)
        with self._banco.transacao() as con:
            con.execute(
                """
                INSERT INTO receitas(
                    ts, project, nome, quando, comando, notas, perigo,
                    em_vez_de_json, origem, import_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, nome) DO UPDATE SET
                    ts = excluded.ts,
                    quando = excluded.quando,
                    comando = excluded.comando,
                    notas = excluded.notas,
                    perigo = excluded.perigo,
                    em_vez_de_json = excluded.em_vez_de_json,
                    origem = excluded.origem
                """,
                (
                    receita.ts,
                    receita.projeto,
                    receita.nome,
                    receita.quando,
                    receita.comando,
                    receita.notas,
                    receita.perigo,
                    em_vez,
                    receita.origem,
                    None,
                ),
            )
            linha = con.execute(
                "SELECT * FROM receitas WHERE project = ? AND nome = ?",
                (receita.projeto, receita.nome),
            ).fetchone()
            gravada = self._de_linha(linha)
            _reindexar_fts(con, gravada)
        return gravada

    def inserir_semente(self, receita, chave_importacao):
        for padrao in receita.em_vez_de:
            self._guarda.validar(padrao)
        existente = self._por_chave(chave_importacao)
        if existente is not None:
            return existente, False
        linhas = self._banco.consultar(
            "SELECT * FROM receitas WHERE project = ? AND nome = ?",
            (receita.projeto, receita.nome),
        )
        if linhas:
            return self._de_linha(linhas[0]), False
        em_vez = json.dumps(list(receita.em_vez_de), ensure_ascii=False)
        try:
            with self._banco.transacao() as con:
                if chave_importacao:
                    linha = con.execute(
                        "SELECT * FROM receitas WHERE import_key = ?",
                        (chave_importacao,),
                    ).fetchone()
                    if linha is not None:
                        return self._de_linha(linha), False
                cur = con.execute(
                    """
                    INSERT INTO receitas(
                        ts, project, nome, quando, comando, notas, perigo,
                        em_vez_de_json, origem, import_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receita.ts,
                        receita.projeto,
                        receita.nome,
                        receita.quando,
                        receita.comando,
                        receita.notas,
                        receita.perigo,
                        em_vez,
                        receita.origem,
                        chave_importacao,
                    ),
                )
                gravada = replace(receita, id=cur.lastrowid)
                _reindexar_fts(con, gravada)
            return gravada, True
        except sqlite3.IntegrityError:
            existente = self._por_chave(chave_importacao)
            if existente is None:
                linhas = self._banco.consultar(
                    "SELECT * FROM receitas WHERE project = ? AND nome = ?",
                    (receita.projeto, receita.nome),
                )
                if linhas:
                    return self._de_linha(linhas[0]), False
                raise
            return existente, False

    def remover(self, nome, projeto):
        with self._banco.transacao() as con:
            linhas = con.execute(
                "SELECT id FROM receitas WHERE nome = ? AND project = ?",
                (nome, projeto),
            ).fetchall()
            if not linhas:
                return 0
            for linha in linhas:
                con.execute(
                    "DELETE FROM receitas_fts WHERE src = ?",
                    ("receita:%d" % linha["id"],),
                )
            cur = con.execute(
                "DELETE FROM receitas WHERE nome = ? AND project = ?",
                (nome, projeto),
            )
            return cur.rowcount

    def _por_chave(self, chave):
        if not chave:
            return None
        linhas = self._banco.consultar(
            "SELECT * FROM receitas WHERE import_key = ?", (chave,)
        )
        if not linhas:
            return None
        return self._de_linha(linhas[0])

    def por_nome(self, nome, projeto):
        for proj in (projeto, "geral"):
            linhas = self._banco.consultar(
                "SELECT * FROM receitas WHERE nome = ? AND project = ?",
                (nome, proj),
            )
            if linhas:
                return self._de_linha(linhas[0])
        return None

    def visiveis(self, projeto):
        linhas = self._banco.consultar(
            "SELECT * FROM receitas WHERE project IN (?, 'geral') ORDER BY id",
            (projeto,),
        )
        por_nome = {}
        for linha in linhas:
            receita = self._de_linha(linha)
            if receita.projeto == "geral":
                por_nome.setdefault(receita.nome, receita)
            else:
                por_nome[receita.nome] = receita
        # as do projeto na frente: quando duas receitas falam do comando, vale a local
        return sorted(por_nome.values(), key=lambda r: r.projeto == "geral")

    def _de_linha(self, linha):
        return Receita(
            id=linha["id"],
            ts=linha["ts"] or "",
            projeto=linha["project"] or "",
            nome=linha["nome"] or "",
            quando=linha["quando"] or "",
            comando=linha["comando"] or "",
            notas=linha["notas"] or "",
            perigo=linha["perigo"],
            em_vez_de=_em_vez_de_de(linha["em_vez_de_json"]),
            origem=linha["origem"] or "",
        )


class RepositorioDeUsos:
    def __init__(self, banco):
        self._banco = banco

    def inserir(
        self, projeto, task, receita_id, comando, tipo, ts, chave_importacao=None
    ):
        if chave_importacao:
            linhas = self._banco.consultar(
                "SELECT id FROM usos_de_receita WHERE import_key = ?",
                (chave_importacao,),
            )
            if linhas:
                return linhas[0]["id"]
        try:
            with self._banco.transacao() as con:
                if chave_importacao:
                    linha = con.execute(
                        "SELECT id FROM usos_de_receita WHERE import_key = ?",
                        (chave_importacao,),
                    ).fetchone()
                    if linha is not None:
                        return linha["id"]
                cur = con.execute(
                    """
                    INSERT INTO usos_de_receita(
                        ts, project, task, receita_id, comando, tipo,
                        import_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        projeto,
                        task or "",
                        receita_id,
                        comando,
                        tipo,
                        chave_importacao,
                    ),
                )
                return cur.lastrowid
        except sqlite3.IntegrityError:
            if not chave_importacao:
                raise
            linhas = self._banco.consultar(
                "SELECT id FROM usos_de_receita WHERE import_key = ?",
                (chave_importacao,),
            )
            if not linhas:
                raise
            return linhas[0]["id"]


class VerificadorDeComando:
    LIMITE_DO_COMANDO = 4096

    def __init__(self, receitas, usos, relogio):
        self._receitas = receitas
        self._usos = usos
        self._relogio = relogio

    def verificar(self, comando, projeto, task="", chave_importacao=None):
        """Avalia o comando contra as receitas visiveis do projeto.

        So os primeiros LIMITE_DO_COMANDO caracteres entram na avaliacao: a
        stdlib nao tem timeout de regex, por isso o teto de tamanho.
        """
        trecho = (comando or "")[: self.LIMITE_DO_COMANDO]
        visiveis = self._receitas.visiveis(projeto)
        # o canonico so protege a PROPRIA receita do seu em_vez_de: o comando cru que e
        # canonico de uma receita ainda pode ser o improviso que outra manda trocar
        for receita in visiveis:
            if _casa_desvio(trecho, receita) and not _casa_canonico(trecho, receita):
                self._gravar(
                    "desvio", projeto, task, receita, comando, chave_importacao
                )
                return ResultadoDeVerificacao("desvio", receita)
        for receita in visiveis:
            if _casa_canonico(trecho, receita):
                self._gravar(
                    "uso", projeto, task, receita, comando, chave_importacao
                )
                return ResultadoDeVerificacao("uso", receita)
        return ResultadoDeVerificacao(None, None)

    def _gravar(self, tipo, projeto, task, receita, comando, chave_importacao):
        ts = self._relogio().isoformat(timespec="microseconds")
        self._usos.inserir(
            projeto,
            task,
            receita.id,
            comando,
            tipo,
            ts,
            chave_importacao=chave_importacao,
        )


def _reindexar_fts(con, receita):
    src = "receita:%d" % receita.id
    con.execute("DELETE FROM receitas_fts WHERE src = ?", (src,))
    nota = receita.notas or ""
    con.execute(
        """
        INSERT INTO receitas_fts(signature, text, note, src)
        VALUES (?, ?, ?, ?)
        """,
        (receita.nome, receita.quando, nota, src),
    )


def _em_vez_de_de(bruto):
    try:
        dados = json.loads(bruto) if bruto else []
    except (TypeError, ValueError):
        return ()
    if not isinstance(dados, list):
        return ()
    return tuple(x for x in dados if isinstance(x, str))


def _padrao_canonico(comando):
    # trecho opcional so conta quando abre com flag ou marcador: " [--x" ou " [<x"
    base = _OPCIONAL.split(comando or "", 1)[0]
    if not base:
        return ""
    partes = [
        re.escape(literal).replace("\\ ", r"\s+")
        for literal in _PLACEHOLDER.split(base)
    ]
    # ponytail: marcador vale qualquer texto da mesma linha (lazy); com o teto de 4 KB
    # do comando o custo fica limitado. Se pesar, trocar por \S+ fora de aspas.
    return ".+?".join(partes)


def _casa_canonico(trecho, receita):
    padrao = _padrao_canonico(receita.comando)
    if not padrao:
        return False
    try:
        return re.search(padrao, trecho) is not None
    except re.error:
        return False


def _casa_desvio(trecho, receita):
    for padrao in receita.em_vez_de:
        if not isinstance(padrao, str):
            continue
        try:
            if re.search(padrao, trecho):
                return True
        except re.error:
            continue
    return False
