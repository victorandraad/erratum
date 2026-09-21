from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from erratum.dominio import Assinatura


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY,
        ts TEXT,
        project TEXT,
        kind TEXT,
        stage TEXT,
        tool TEXT,
        signature TEXT,
        text TEXT,
        context_json TEXT,
        import_key TEXT UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fixes (
        id INTEGER PRIMARY KEY,
        ts TEXT,
        project TEXT,
        signature TEXT,
        note TEXT,
        ref TEXT,
        test TEXT,
        source TEXT,
        import_key TEXT UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wins (
        id INTEGER PRIMARY KEY,
        ts TEXT,
        project TEXT,
        task TEXT,
        what TEXT,
        cost_usd REAL,
        context_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gate_runs (
        id INTEGER PRIMARY KEY,
        ts TEXT,
        project TEXT,
        gate TEXT,
        verdict TEXT,
        detail TEXT
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS ledger_fts USING fts5(
        signature, text, note, src UNINDEXED,
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pistas (
        id INTEGER PRIMARY KEY,
        ts TEXT,
        project TEXT,
        task TEXT,
        erro_id INTEGER,
        correcao_id INTEGER,
        origem TEXT,
        veredito TEXT,
        confianca REAL,
        desfecho TEXT,
        desfecho_ts TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_errors_signature ON errors(signature)",
    "CREATE INDEX IF NOT EXISTS idx_fixes_signature ON fixes(signature)",
    "CREATE INDEX IF NOT EXISTS idx_errors_project_ts ON errors(project, ts)",
    "CREATE INDEX IF NOT EXISTS idx_pistas_project_task ON pistas(project, task)",
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
)


class Banco:
    def __init__(self, caminho=None, ambiente=None):
        if ambiente is None:
            ambiente = os.environ
        if caminho is None:
            caminho = ambiente.get("ERRATUM_DB")
            if not caminho:
                caminho = self.caminho_padrao(ambiente)
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._con = None
        self._abrir()

    @classmethod
    def caminho_padrao(cls, ambiente=None):
        home = Path.home()
        if ambiente:
            bruto = ambiente.get("HOME")
            if bruto:
                home = Path(bruto)
        return home / ".local" / "state" / "erratum" / "ledger.db"

    def _abrir(self):
        ultimo = None
        for i in range(40):
            con = None
            try:
                con = sqlite3.connect(
                    str(self.caminho), timeout=5, isolation_level=None
                )
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA busy_timeout = 5000")
                con.execute("PRAGMA journal_mode = WAL")
                self._aplicar_schema(con)
                self._con = con
                return
            except sqlite3.OperationalError as e:
                if con is not None:
                    try:
                        con.close()
                    except sqlite3.Error:
                        pass
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    time.sleep(0.025 * (i + 1))
                    ultimo = e
                    continue
                raise
        raise ultimo

    def _aplicar_schema(self, con):
        for sql in _SCHEMA:
            try:
                con.execute(sql)
            except sqlite3.OperationalError as e:
                # IF NOT EXISTS nao cobre todas as corridas no CREATE VIRTUAL
                if "already exists" not in str(e).lower():
                    raise
        self._carimbar_regra_se_vazio(con)

    def _carimbar_regra_se_vazio(self, con):
        achou = con.execute(
            "SELECT 1 FROM meta WHERE key = 'regra_assinatura'"
        ).fetchone()
        if achou is not None:
            return
        n = con.execute(
            "SELECT (SELECT COUNT(*) FROM errors)"
            " + (SELECT COUNT(*) FROM fixes)"
        ).fetchone()[0]
        if n:
            return
        try:
            con.execute(
                "INSERT OR IGNORE INTO meta(key, value)"
                " VALUES ('regra_assinatura', ?)",
                (str(Assinatura.VERSAO),),
            )
        except sqlite3.IntegrityError:
            pass

    def versao_da_regra(self):
        try:
            linhas = self.consultar(
                "SELECT value FROM meta WHERE key = ?",
                ("regra_assinatura",),
            )
        except sqlite3.OperationalError:
            return None
        if not linhas or linhas[0]["value"] is None:
            return None
        try:
            return int(linhas[0]["value"])
        except (TypeError, ValueError):
            return None

    @contextmanager
    def transacao(self):
        self._con.execute("BEGIN IMMEDIATE")
        try:
            yield self._con
        except Exception:
            try:
                self._con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        else:
            self._con.execute("COMMIT")

    def consultar(self, sql, params=()):
        cur = self._con.execute(sql, params)
        return list(cur.fetchall())

    def fechar(self):
        con = self._con
        self._con = None
        if con is not None:
            con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()
