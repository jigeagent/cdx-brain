"""SQLite schema with engine extensions."""
from __future__ import annotations
from cdx_brain.cache.connection import CacheConnection
from cdx_brain.counterfactual.store import ensure_counterfactual_schema

def ensure_schema(conn_or_cache: CacheConnection) -> None:
    conn = conn_or_cache.conn if isinstance(conn_or_cache, CacheConnection) else conn_or_cache
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY,session_id TEXT NOT NULL,turn_index INTEGER NOT NULL DEFAULT 0,user_content TEXT NOT NULL,assistant_content TEXT NOT NULL DEFAULT '',embedding BLOB,reward REAL NOT NULL DEFAULT 0.0,tags TEXT DEFAULT '',metadata TEXT DEFAULT '{}',created_at TEXT NOT NULL,synced INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
        CREATE INDEX IF NOT EXISTS idx_traces_created ON traces(created_at);
        CREATE INDEX IF NOT EXISTS idx_traces_synced ON traces(synced);
        CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',trigger_pattern TEXT NOT NULL DEFAULT '',action_template TEXT NOT NULL DEFAULT '',embedding BLOB,confidence REAL NOT NULL DEFAULT 0.0,activation_count INTEGER NOT NULL DEFAULT 0,source_trace_ids TEXT DEFAULT '[]',metadata TEXT DEFAULT '{}',created_at TEXT NOT NULL,synced INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_policies_confidence ON policies(confidence DESC);
        CREATE TABLE IF NOT EXISTS skills (name TEXT PRIMARY KEY,description TEXT NOT NULL DEFAULT '',usage_guide TEXT NOT NULL DEFAULT '',source_policy_ids TEXT DEFAULT '[]',version INTEGER NOT NULL DEFAULT 1,metadata TEXT DEFAULT '{}',created_at TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS traces_fts USING fts5(user_content,assistant_content,tags,content='traces',content_rowid='rowid');
        CREATE TRIGGER IF NOT EXISTS traces_ai AFTER INSERT ON traces BEGIN INSERT INTO traces_fts(rowid,user_content,assistant_content,tags) VALUES (new.rowid,new.user_content,new.assistant_content,new.tags); END;
        CREATE TRIGGER IF NOT EXISTS traces_ad AFTER DELETE ON traces BEGIN INSERT INTO traces_fts(traces_fts,rowid,user_content,assistant_content,tags) VALUES ('delete',old.rowid,old.user_content,old.assistant_content,old.tags); END;
        CREATE TRIGGER IF NOT EXISTS traces_au AFTER UPDATE ON traces BEGIN INSERT INTO traces_fts(traces_fts,rowid,user_content,assistant_content,tags) VALUES ('delete',old.rowid,old.user_content,old.assistant_content,old.tags); INSERT INTO traces_fts(rowid,user_content,assistant_content,tags) VALUES (new.rowid,new.user_content,new.assistant_content,new.tags); END;
    """)
    conn.commit()
    _ensure_engine_tables(conn)
    _ensure_graph_tables(conn)
    ensure_counterfactual_schema(conn)

def _ensure_graph_tables(conn) -> None:
    """Phase 6 tables for graph multi-strategy + causal retrieval."""
    for sql in [
        "CREATE TABLE IF NOT EXISTS semantic_links (source_id TEXT NOT NULL,target_id TEXT NOT NULL,similarity REAL NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(source_id,target_id))",
        "CREATE INDEX IF NOT EXISTS idx_semantic_links_source ON semantic_links(source_id)",
        "CREATE TABLE IF NOT EXISTS memory_links (source_id TEXT NOT NULL,target_id TEXT NOT NULL,link_type TEXT NOT NULL DEFAULT 'causal',weight REAL NOT NULL DEFAULT 1.0,metadata TEXT DEFAULT '{}',created_at TEXT NOT NULL,PRIMARY KEY(source_id,target_id,link_type))",
        "CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_id)",
    ]:
        try: conn.execute(sql); conn.commit()
        except Exception: pass


def _ensure_engine_tables(conn) -> None:
    for sql in [
        "CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY,name TEXT NOT NULL,type TEXT NOT NULL DEFAULT 'CONCEPT',metadata TEXT DEFAULT '{}',created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS entity_edges (source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL,weight REAL NOT NULL DEFAULT 1.0,metadata TEXT DEFAULT '{}',created_at TEXT NOT NULL,PRIMARY KEY(source,target,relation))",
        "CREATE TABLE IF NOT EXISTS unit_entities (trace_id TEXT NOT NULL,entity_id TEXT NOT NULL,context TEXT DEFAULT '',created_at TEXT NOT NULL,PRIMARY KEY(trace_id,entity_id))",
        "CREATE INDEX IF NOT EXISTS idx_unit_entities_entity ON unit_entities(entity_id)",
    ]:
        try: conn.execute(sql); conn.commit()
        except Exception: pass

def ensure_decay_migration(conn_or_cache) -> None:
    conn = conn_or_cache.conn if hasattr(conn_or_cache, "conn") else conn_or_cache
    try: conn.execute("ALTER TABLE traces ADD COLUMN cold INTEGER NOT NULL DEFAULT 0"); conn.commit()
    except Exception: pass

def drop_schema(conn_or_cache: CacheConnection) -> None:
    conn = conn_or_cache.conn if isinstance(conn_or_cache, CacheConnection) else conn_or_cache
    conn.executescript("DROP TABLE IF EXISTS traces_fts;DROP TABLE IF EXISTS skills;DROP TABLE IF EXISTS policies;DROP TABLE IF EXISTS traces;DROP TABLE IF EXISTS entities;DROP TABLE IF EXISTS entity_edges;DROP TABLE IF EXISTS unit_entities;DROP TABLE IF EXISTS semantic_links;DROP TABLE IF EXISTS memory_links;")
    conn.commit()
