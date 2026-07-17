"""sqlite-vec vector store for local embedding search."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any
import sqlite_vec

class VectorStore:
    def __init__(self, db_path: str | Path):
        self._db_path = str(Path(db_path).expanduser())
        self._conn: sqlite3.Connection | None = None
    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    def ensure_schema(self, dims: int = 384) -> None:
        self._get_conn().execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_traces USING vec0(id TEXT PRIMARY KEY, embedding float[{dims}])").connection.commit()
    def insert(self, trace_id: str, embedding: list[float]) -> None:
        self._get_conn().execute("INSERT OR REPLACE INTO vec_traces(id, embedding) VALUES (?, ?)",[trace_id, json.dumps(embedding)]).connection.commit()
    def insert_batch(self, items: list[tuple[str, list[float]]]) -> None:
        conn = self._get_conn()
        conn.executemany("INSERT OR REPLACE INTO vec_traces(id, embedding) VALUES (?, ?)",[(tid, json.dumps(emb)) for tid, emb in items])
        conn.commit()
    def search(self, query_emb: list[float], k: int = 8) -> list[tuple[str, float]]:
        rows = self._get_conn().execute("SELECT id, distance FROM vec_traces WHERE embedding MATCH ? AND k = ?",[json.dumps(query_emb), k]).fetchall()
        return [(row[0], 1.0 - row[1] / 2.0) for row in rows]
    def delete(self, trace_id: str) -> None:
        self._get_conn().execute("DELETE FROM vec_traces WHERE id = ?", [trace_id]).connection.commit()
    def count(self) -> int:
        row = self._get_conn().execute("SELECT COUNT(*) as cnt FROM vec_traces").fetchone()
        return row[0] if row else 0
    def close(self) -> None:
        if self._conn: self._conn.close(); self._conn = None
