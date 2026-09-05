"""Passage index — SQLite FTS5 (BM25).

This is what makes project memory (spec §13) work without an embedding vendor:
every passage of every source added to a project is indexed here, so "according
to the papers I uploaded earlier…" is answered by searching the user's own
corpus and citing the passages that actually matched.

The interface is deliberately narrow so a vector store can replace it by
implementing ``add``/``search``/``remove`` and registering under the same
capability.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import settings
from ...core.provenance import Passage
from ...core.registry import Provider, ProviderStatus

CAPABILITY = "passage_index"

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
    passage_id UNINDEXED,
    project_id UNINDEXED,
    source_id  UNINDEXED,
    body,
    tokenize = 'porter unicode61'
);
CREATE TABLE IF NOT EXISTS passage_meta (
    passage_id     TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    page           INTEGER,
    section        TEXT,
    char_start     INTEGER,
    char_end       INTEGER,
    start_seconds  REAL,
    end_seconds    REAL
);
CREATE INDEX IF NOT EXISTS passage_meta_project ON passage_meta(project_id);
CREATE INDEX IF NOT EXISTS passage_meta_source  ON passage_meta(source_id);
"""

# FTS5 reserves these; a raw user question would otherwise be a syntax error.
_FTS_UNSAFE = re.compile(r"[^\w\s]", re.UNICODE)


def to_match_query(text: str) -> str:
    """Turn free text into a safe OR-query of its content words."""
    from ...core.text import content_tokens

    words = [w for w in content_tokens(_FTS_UNSAFE.sub(" ", text)) if len(w) > 2][:24]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


class SqliteFtsIndex(Provider):
    capability = CAPABILITY
    name = "sqlite_fts"
    requires_credentials = False
    priority = 10

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.data_dir / "passages.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._fts_ok: bool | None = None

    # -- connection ----------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()
            self._local.conn = conn
        return conn

    def status(self) -> ProviderStatus:
        if self._fts_ok is None:
            try:
                self._conn()
                self._fts_ok = True
            except sqlite3.OperationalError as exc:
                self._fts_ok = False
                self._fts_error = str(exc)
        if not self._fts_ok:
            return ProviderStatus(
                False, f"SQLite was built without FTS5 support: {getattr(self, '_fts_error', '')}"
            )
        return ProviderStatus(True, details={"path": str(self.path), "engine": "fts5/bm25"})

    # -- writes --------------------------------------------------------
    def add(self, project_id: str, passages: list[Passage]) -> int:
        if not passages:
            return 0
        conn = self._conn()
        with conn:
            for p in passages:
                conn.execute(
                    "DELETE FROM passages WHERE passage_id = ?", (p.id,)
                )
                conn.execute(
                    "INSERT INTO passages (passage_id, project_id, source_id, body) "
                    "VALUES (?, ?, ?, ?)",
                    (p.id, project_id, p.source_id, p.text),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO passage_meta "
                    "(passage_id, project_id, source_id, page, section, char_start, "
                    " char_end, start_seconds, end_seconds) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        p.id, project_id, p.source_id, p.page, p.section,
                        p.char_start, p.char_end, p.start_seconds, p.end_seconds,
                    ),
                )
        return len(passages)

    def remove_source(self, source_id: str) -> int:
        conn = self._conn()
        with conn:
            cur = conn.execute("DELETE FROM passages WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM passage_meta WHERE source_id = ?", (source_id,))
        return cur.rowcount

    def remove_project(self, project_id: str) -> int:
        conn = self._conn()
        with conn:
            cur = conn.execute("DELETE FROM passages WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM passage_meta WHERE project_id = ?", (project_id,))
        return cur.rowcount

    # -- reads ---------------------------------------------------------
    def search(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 12,
        source_ids: list[str] | None = None,
    ) -> list[Passage]:
        match = to_match_query(query)
        if not match:
            return []
        sql = (
            "SELECT p.passage_id, p.source_id, p.body, bm25(passages) AS rank, "
            "       m.page, m.section, m.char_start, m.char_end, "
            "       m.start_seconds, m.end_seconds "
            "FROM passages p "
            "LEFT JOIN passage_meta m ON m.passage_id = p.passage_id "
            "WHERE passages MATCH ? AND p.project_id = ? "
        )
        params: list = [match, project_id]
        if source_ids:
            sql += f"AND p.source_id IN ({','.join('?' * len(source_ids))}) "
            params.extend(source_ids)
        sql += "ORDER BY rank LIMIT ?"
        params.append(limit)

        try:
            rows = self._conn().execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

        out: list[Passage] = []
        for row in rows:
            # bm25() returns lower-is-better; expose an increasing relevance score.
            out.append(
                Passage(
                    id=row["passage_id"],
                    source_id=row["source_id"],
                    text=row["body"],
                    page=row["page"],
                    section=row["section"],
                    char_start=row["char_start"],
                    char_end=row["char_end"],
                    start_seconds=row["start_seconds"],
                    end_seconds=row["end_seconds"],
                    score=round(1.0 / (1.0 + abs(row["rank"] or 0.0)), 4),
                )
            )
        return out

    def count(self, project_id: str) -> int:
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM passage_meta WHERE project_id = ?", (project_id,)
        ).fetchone()
        return int(row["n"]) if row else 0
