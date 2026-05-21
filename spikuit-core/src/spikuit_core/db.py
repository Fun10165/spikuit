"""Spikuit Core database — async SQLite persistence layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import sqlite_vec

from .models import Grade, Neuron, QuizItem, QuizItemRole, Source, Spike, Synapse, SynapseConfidence, SynapseType

DEFAULT_DB_PATH: Path = Path.home() / ".spikuit" / "spikuit.db"

# SQLite journal modes Spikuit supports. ``WAL`` is the default — fastest on
# a single machine. ``DELETE`` keeps the whole database in one file at every
# transaction boundary (no ``-wal`` / ``-shm`` sidecars), which is what a
# file-synced Brain vault needs: a Syncthing/Dropbox sync that catches WAL
# mode mid-checkpoint can ship a stale or torn ``.db``. The remaining modes
# are accepted for completeness.
_JOURNAL_MODES: frozenset[str] = frozenset(
    {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
)


def normalize_journal_mode(mode: str) -> str:
    """Validate and canonicalize a SQLite ``journal_mode`` string.

    SQLite silently ignores an unknown ``PRAGMA journal_mode`` value, so a
    typo would otherwise leave the database in its previous mode with no
    error. Validate up front instead.

    Raises:
        ValueError: If ``mode`` is not a recognized journal mode.
    """
    normalized = mode.strip().upper()
    if normalized not in _JOURNAL_MODES:
        raise ValueError(
            f"unsupported journal_mode {mode!r}; "
            f"expected one of {sorted(_JOURNAL_MODES)}"
        )
    return normalized

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS neuron (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    type TEXT,
    domain TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS synapse (
    pre TEXT NOT NULL REFERENCES neuron(id),
    post TEXT NOT NULL REFERENCES neuron(id),
    type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    co_fires INTEGER NOT NULL DEFAULT 0,
    last_co_fire TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (pre, post, type)
);

CREATE TABLE IF NOT EXISTS spike (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neuron_id TEXT NOT NULL REFERENCES neuron(id),
    grade INTEGER NOT NULL,
    fired_at TEXT NOT NULL,
    session_id TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS retrieve_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    neuron_ids TEXT NOT NULL,
    retrieved_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_neuron_type ON neuron(type);
CREATE INDEX IF NOT EXISTS idx_neuron_domain ON neuron(domain);
CREATE INDEX IF NOT EXISTS idx_synapse_pre ON synapse(pre);
CREATE INDEX IF NOT EXISTS idx_synapse_post ON synapse(post);
CREATE INDEX IF NOT EXISTS idx_spike_neuron ON spike(neuron_id);
CREATE INDEX IF NOT EXISTS idx_spike_session ON spike(session_id);

CREATE TABLE IF NOT EXISTS retrieval_boost (
    neuron_id TEXT PRIMARY KEY REFERENCES neuron(id),
    boost REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_item (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    hints TEXT NOT NULL DEFAULT '[]',
    grading_criteria TEXT NOT NULL DEFAULT '',
    scaffold_level TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_item_neuron (
    quiz_item_id TEXT NOT NULL REFERENCES quiz_item(id) ON DELETE CASCADE,
    neuron_id TEXT NOT NULL REFERENCES neuron(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    PRIMARY KEY (quiz_item_id, neuron_id)
);

CREATE INDEX IF NOT EXISTS idx_quiz_item_neuron_nid ON quiz_item_neuron(neuron_id);

CREATE TABLE IF NOT EXISTS source (
    id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT,
    author TEXT,
    section TEXT,
    excerpt TEXT,
    storage_uri TEXT,
    content_hash TEXT,
    notes TEXT,
    accessed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS neuron_source (
    neuron_id TEXT NOT NULL REFERENCES neuron(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    PRIMARY KEY (neuron_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_url ON source(url);
CREATE INDEX IF NOT EXISTS idx_neuron_source_sid ON neuron_source(source_id);

-- AMKB plumbing (v0.7.0): changeset/event log, lineage junction.
-- Soft-retire columns for neuron/synapse live in _run_migrations
-- because the base tables predate this feature.

CREATE TABLE IF NOT EXISTS changeset (
    id TEXT PRIMARY KEY,
    tag TEXT,
    actor_id TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    committed_at TEXT,
    status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_changeset_committed_at ON changeset(committed_at);

CREATE TABLE IF NOT EXISTS event (
    id TEXT PRIMARY KEY,
    changeset_id TEXT NOT NULL REFERENCES changeset(id),
    seq INTEGER NOT NULL,
    op TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_changeset ON event(changeset_id, seq);
CREATE INDEX IF NOT EXISTS idx_event_target ON event(target_kind, target_id);
CREATE INDEX IF NOT EXISTS idx_event_at ON event(at);

CREATE TABLE IF NOT EXISTS neuron_predecessor (
    child_id TEXT NOT NULL REFERENCES neuron(id),
    parent_id TEXT NOT NULL REFERENCES neuron(id),
    at TEXT NOT NULL,
    PRIMARY KEY (child_id, parent_id)
);

CREATE INDEX IF NOT EXISTS idx_neuron_predecessor_parent
    ON neuron_predecessor(parent_id);
"""


# Canonical live-row SQL fragments. Every SELECT on neuron / synapse that
# serves live-state behavior MUST use these (see amkb-core-plumbing-spec §7).
LIVE_NEURON = "n.retired_at IS NULL"
LIVE_SYNAPSE = "s.retired_at IS NULL"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class Database:
    """Async SQLite wrapper for Spikuit persistence."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        embedding_dimension: int | None = None,
        journal_mode: str = "WAL",
    ) -> None:
        self.db_path: Path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._embedding_dimension = embedding_dimension
        self._journal_mode = normalize_journal_mode(journal_mode)

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        await self._run_migrations()
        # Load sqlite-vec extension and create vec table if dimension is set
        if self._embedding_dimension is not None:
            await self._init_vec_table(self._embedding_dimension)

    async def _run_migrations(self) -> None:
        """Run schema migrations for existing databases."""
        migrations = [
            "ALTER TABLE neuron ADD COLUMN community_id INTEGER",
            "ALTER TABLE source ADD COLUMN filterable TEXT",
            "ALTER TABLE source ADD COLUMN searchable TEXT",
            "ALTER TABLE source ADD COLUMN fetched_at TEXT",
            "ALTER TABLE source ADD COLUMN http_etag TEXT",
            "ALTER TABLE source ADD COLUMN http_last_modified TEXT",
            "ALTER TABLE source ADD COLUMN status TEXT DEFAULT 'active'",
            "ALTER TABLE synapse ADD COLUMN confidence TEXT DEFAULT 'extracted'",
            "ALTER TABLE synapse ADD COLUMN confidence_score REAL DEFAULT 1.0",
            "ALTER TABLE spike ADD COLUMN notes TEXT",
            # AMKB plumbing (v0.7.0): soft-retire columns.
            "ALTER TABLE neuron ADD COLUMN retired_at TEXT",
            "ALTER TABLE synapse ADD COLUMN retired_at TEXT",
            "CREATE INDEX IF NOT EXISTS idx_neuron_retired_at ON neuron(retired_at)",
            "CREATE INDEX IF NOT EXISTS idx_synapse_retired_at ON synapse(retired_at)",
        ]
        for sql in migrations:
            try:
                await self.conn.execute(sql)
                await self.conn.commit()
            except Exception:
                pass  # Column already exists

    async def _init_vec_table(self, dimension: int) -> None:
        """Initialize sqlite-vec virtual table for embeddings."""

        def _load_extension():
            """Load sqlite-vec in the worker thread (same thread as the connection)."""
            raw = self.conn._conn  # sqlite3.Connection in worker thread
            raw.enable_load_extension(True)
            sqlite_vec.load(raw)
            raw.enable_load_extension(False)

        # Run in aiosqlite's worker thread where the connection lives
        await self.conn._execute(_load_extension)
        await self.conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS neuron_vec "
            f"USING vec0(embedding float[{dimension}])"
        )
        # Mapping table: rowid ↔ neuron_id (vec0 uses integer rowids)
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS neuron_vec_map (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                neuron_id TEXT NOT NULL UNIQUE REFERENCES neuron(id)
            );
        """)
        await self.conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # -- AMKB changeset / event log (v0.7.0) --------------------------------

    async def insert_changeset_open(
        self,
        *,
        changeset_id: str,
        tag: str | None,
        actor_id: str,
        actor_kind: str,
        started_at: str,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO changeset "
            "(id, tag, actor_id, actor_kind, started_at, status) "
            "VALUES (?, ?, ?, ?, ?, 'open')",
            (changeset_id, tag, actor_id, actor_kind, started_at),
        )
        await self.conn.commit()

    async def commit_changeset(
        self,
        changeset_id: str,
        *,
        events: list[tuple[str, str, str, str | None, str | None, str]],
        committed_at: str,
    ) -> None:
        """Flush buffered events and mark the changeset committed.

        Each event tuple is (op, target_kind, target_id, before_json,
        after_json, at).
        """
        import uuid

        for seq, (op, kind, tid, before, after, at) in enumerate(events):
            await self.conn.execute(
                "INSERT INTO event "
                "(id, changeset_id, seq, op, target_kind, target_id, "
                "before_json, after_json, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"ev_{uuid.uuid4().hex[:12]}",
                    changeset_id,
                    seq,
                    op,
                    kind,
                    tid,
                    before,
                    after,
                    at,
                ),
            )
        await self.conn.execute(
            "UPDATE changeset SET status='committed', committed_at=? WHERE id=?",
            (committed_at, changeset_id),
        )
        await self.conn.commit()

    async def abort_changeset(self, changeset_id: str) -> None:
        await self.conn.execute(
            "UPDATE changeset SET status='aborted' WHERE id=?",
            (changeset_id,),
        )
        await self.conn.commit()

    async def get_changeset(self, changeset_id: str) -> dict | None:
        cur = await self.conn.execute(
            "SELECT id, tag, actor_id, actor_kind, started_at, "
            "committed_at, status FROM changeset WHERE id=?",
            (changeset_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_events(
        self,
        *,
        changeset_id: str | None = None,
        target_id: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        clauses = []
        params: list[object] = []
        if changeset_id is not None:
            clauses.append("changeset_id = ?")
            params.append(changeset_id)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        cur = await self.conn.execute(
            "SELECT id, changeset_id, seq, op, target_kind, target_id, "
            "before_json, after_json, at FROM event"
            + where
            + " ORDER BY at, seq LIMIT ?",
            tuple(params),
        )
        return [dict(row) async for row in cur]

    # -- Lineage (neuron_predecessor) ---------------------------------------

    async def insert_predecessor(
        self, child_id: str, parent_id: str, at: str,
    ) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO neuron_predecessor (child_id, parent_id, at) "
            "VALUES (?, ?, ?)",
            (child_id, parent_id, at),
        )
        await self.conn.commit()

    async def get_predecessors(self, child_id: str) -> list[str]:
        rows = await self.conn.execute_fetchall(
            "SELECT parent_id FROM neuron_predecessor WHERE child_id = ? "
            "ORDER BY at",
            (child_id,),
        )
        return [r["parent_id"] for r in rows]

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    # -- Neuron CRUD --------------------------------------------------------

    async def insert_neuron(self, neuron: Neuron) -> None:
        await self.conn.execute(
            """INSERT INTO neuron (id, content, type, domain, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                neuron.id,
                neuron.content,
                neuron.type,
                neuron.domain,
                neuron.source,
                _ts(neuron.created_at),
                _ts(neuron.updated_at),
            ),
        )
        await self.conn.commit()

    async def get_neuron(
        self, neuron_id: str, *, include_retired: bool = False,
    ) -> Neuron | None:
        sql = "SELECT * FROM neuron WHERE id = ?"
        if not include_retired:
            sql += " AND retired_at IS NULL"
        rows = await self.conn.execute_fetchall(sql, (neuron_id,))
        return _row_to_neuron(rows[0]) if rows else None

    async def get_neuron_retired_at(self, neuron_id: str) -> datetime | None:
        """Return the soft-retire timestamp of a neuron, or ``None`` if live.

        Returns ``None`` for both live neurons and neurons that do not
        exist; callers needing to distinguish those cases should pair
        this with :meth:`get_neuron(include_retired=True)`.
        """
        rows = await self.conn.execute_fetchall(
            "SELECT retired_at FROM neuron WHERE id = ?", (neuron_id,),
        )
        if not rows:
            return None
        raw = rows[0]["retired_at"]
        if raw is None:
            return None
        return datetime.fromisoformat(raw)

    async def list_neurons(
        self,
        *,
        type: str | None = None,
        domain: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_retired: bool = False,
    ) -> list[Neuron]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_retired:
            clauses.append("retired_at IS NULL")
        if type:
            clauses.append("type = ?")
            params.append(type)
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = await self.conn.execute_fetchall(
            f"SELECT * FROM neuron {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [_row_to_neuron(r) for r in rows]

    async def update_neuron(self, neuron: Neuron) -> None:
        neuron.updated_at = datetime.now(timezone.utc)
        await self.conn.execute(
            """UPDATE neuron SET content=?, type=?, domain=?, source=?, updated_at=?
               WHERE id=?""",
            (
                neuron.content,
                neuron.type,
                neuron.domain,
                neuron.source,
                _ts(neuron.updated_at),
                neuron.id,
            ),
        )
        await self.conn.commit()

    async def delete_neuron(self, neuron_id: str) -> None:
        """Hard-delete a neuron and all its dependent rows.

        Reachable only from ``spkt history prune`` (v0.7.0+). Circuit's
        public ``remove_neuron`` always uses the soft path.
        """
        await self.conn.execute(
            "DELETE FROM synapse WHERE pre=? OR post=?", (neuron_id, neuron_id)
        )
        await self.conn.execute("DELETE FROM spike WHERE neuron_id=?", (neuron_id,))
        await self.delete_quiz_items_for_neuron(neuron_id)
        if self._embedding_dimension is not None:
            await self.delete_embedding(neuron_id)
        await self.conn.execute(
            "DELETE FROM neuron_predecessor WHERE child_id=? OR parent_id=?",
            (neuron_id, neuron_id),
        )
        await self.conn.execute("DELETE FROM neuron WHERE id=?", (neuron_id,))
        await self.conn.commit()

    async def prune_retired_neurons(self) -> dict[str, int]:
        """Physically delete every soft-retired neuron + its retired synapses.

        Also drops dangling retired synapses whose endpoints are still live
        (e.g. the result of ``soft_retire_synapse`` on its own). Preserves
        event log and changeset rows untouched. Returns a summary dict.
        """
        # Count every retired synapse up-front — delete_neuron below removes
        # those touching retired neurons along the way, so counting after
        # the loop would miss them.
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM synapse WHERE retired_at IS NOT NULL"
        )
        retired_synapse_count = int((await cur.fetchone())[0])

        retired_rows = await self.conn.execute_fetchall(
            "SELECT id FROM neuron WHERE retired_at IS NOT NULL"
        )
        retired_ids = [r["id"] for r in retired_rows]
        for nid in retired_ids:
            await self.delete_neuron(nid)

        # Drop any remaining retired synapses (endpoints still live).
        await self.conn.execute(
            "DELETE FROM synapse WHERE retired_at IS NOT NULL"
        )
        await self.conn.commit()

        return {
            "neurons_pruned": len(retired_ids),
            "synapses_pruned": retired_synapse_count,
        }

    async def soft_retire_neuron(
        self, neuron_id: str, at: str,
    ) -> list[tuple[str, str, str]]:
        """Mark a neuron and its synapses retired, drop its vector row.

        Returns the list of (pre, post, type) for each synapse that was
        cascade-retired, so the caller can emit synapse retire events.
        Spike history is preserved; quiz item links are cascade-removed.
        """
        cur = await self.conn.execute(
            "SELECT pre, post, type FROM synapse "
            "WHERE (pre=? OR post=?) AND retired_at IS NULL",
            (neuron_id, neuron_id),
        )
        retired_keys = [(r["pre"], r["post"], r["type"]) async for r in cur]
        await self.conn.execute(
            "UPDATE synapse SET retired_at=? "
            "WHERE (pre=? OR post=?) AND retired_at IS NULL",
            (at, neuron_id, neuron_id),
        )
        await self.conn.execute(
            "UPDATE neuron SET retired_at=? WHERE id=? AND retired_at IS NULL",
            (at, neuron_id),
        )
        # Quiz items are private flashcard state, not part of the graph
        # AMKB consumers see. Cascade-remove them so retired neurons stop
        # generating quiz prompts.
        await self.delete_quiz_items_for_neuron(neuron_id)
        if self._embedding_dimension is not None:
            await self.delete_embedding(neuron_id)
        await self.conn.commit()
        return retired_keys

    async def count_neurons(self, *, include_retired: bool = False) -> int:
        sql = "SELECT COUNT(*) FROM neuron"
        if not include_retired:
            sql += " WHERE retired_at IS NULL"
        rows = await self.conn.execute_fetchall(sql)
        return rows[0][0]

    # -- Synapse CRUD -------------------------------------------------------

    async def insert_synapse(self, synapse: Synapse) -> None:
        await self.conn.execute(
            """INSERT OR IGNORE INTO synapse
               (pre, post, type, weight, co_fires, last_co_fire,
                confidence, confidence_score, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                synapse.pre,
                synapse.post,
                synapse.type.value,
                synapse.weight,
                synapse.co_fires,
                _ts(synapse.last_co_fire) if synapse.last_co_fire else None,
                synapse.confidence.value,
                synapse.confidence_score,
                _ts(synapse.created_at),
                _ts(synapse.updated_at),
            ),
        )
        await self.conn.commit()

    async def get_synapse(
        self, pre: str, post: str, type: SynapseType,
        *, include_retired: bool = False,
    ) -> Synapse | None:
        sql = "SELECT * FROM synapse WHERE pre=? AND post=? AND type=?"
        if not include_retired:
            sql += " AND retired_at IS NULL"
        rows = await self.conn.execute_fetchall(sql, (pre, post, type.value))
        return _row_to_synapse(rows[0]) if rows else None

    async def get_synapses_from(
        self, neuron_id: str, *, include_retired: bool = False,
    ) -> list[Synapse]:
        sql = "SELECT * FROM synapse WHERE pre=?"
        if not include_retired:
            sql += " AND retired_at IS NULL"
        rows = await self.conn.execute_fetchall(sql, (neuron_id,))
        return [_row_to_synapse(r) for r in rows]

    async def get_synapses_to(
        self, neuron_id: str, *, include_retired: bool = False,
    ) -> list[Synapse]:
        sql = "SELECT * FROM synapse WHERE post=?"
        if not include_retired:
            sql += " AND retired_at IS NULL"
        rows = await self.conn.execute_fetchall(sql, (neuron_id,))
        return [_row_to_synapse(r) for r in rows]

    async def get_all_synapses(
        self, *, include_retired: bool = False,
    ) -> list[Synapse]:
        sql = "SELECT * FROM synapse"
        if not include_retired:
            sql += " WHERE retired_at IS NULL"
        rows = await self.conn.execute_fetchall(sql)
        return [_row_to_synapse(r) for r in rows]

    async def update_synapse(self, synapse: Synapse) -> None:
        synapse.updated_at = datetime.now(timezone.utc)
        await self.conn.execute(
            """UPDATE synapse SET weight=?, co_fires=?, last_co_fire=?,
                    confidence=?, confidence_score=?, updated_at=?
               WHERE pre=? AND post=? AND type=?""",
            (
                synapse.weight,
                synapse.co_fires,
                _ts(synapse.last_co_fire) if synapse.last_co_fire else None,
                synapse.confidence.value,
                synapse.confidence_score,
                _ts(synapse.updated_at),
                synapse.pre,
                synapse.post,
                synapse.type.value,
            ),
        )
        await self.conn.commit()

    async def delete_synapse(self, pre: str, post: str, type: SynapseType) -> None:
        """Hard-delete a synapse row.

        Reachable only from ``spkt history prune``. Circuit's public
        ``remove_synapse`` always uses the soft path.
        """
        await self.conn.execute(
            "DELETE FROM synapse WHERE pre=? AND post=? AND type=?",
            (pre, post, type.value),
        )
        await self.conn.commit()

    async def soft_retire_synapse(
        self, pre: str, post: str, type: SynapseType, at: str,
    ) -> bool:
        """Mark a single synapse retired. Returns True if a row was updated."""
        cur = await self.conn.execute(
            "UPDATE synapse SET retired_at=? "
            "WHERE pre=? AND post=? AND type=? AND retired_at IS NULL",
            (at, pre, post, type.value),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # -- Spike --------------------------------------------------------------

    async def insert_spike(self, spike: Spike) -> int:
        cursor = await self.conn.execute(
            """INSERT INTO spike (neuron_id, grade, fired_at, session_id, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                spike.neuron_id,
                spike.grade.value,
                _ts(spike.fired_at),
                spike.session_id,
                spike.notes,
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_spikes_for(
        self, neuron_id: str, *, limit: int = 50
    ) -> list[Spike]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM spike WHERE neuron_id=? ORDER BY fired_at DESC LIMIT ?",
            (neuron_id, limit),
        )
        return [_row_to_spike(r) for r in rows]

    # -- Embeddings ---------------------------------------------------------

    async def upsert_embedding(self, neuron_id: str, blob: bytes) -> None:
        """Insert or replace an embedding vector for a neuron."""
        # Get or create the rowid mapping
        rows = await self.conn.execute_fetchall(
            "SELECT rowid FROM neuron_vec_map WHERE neuron_id = ?", (neuron_id,)
        )
        if rows:
            rid = rows[0]["rowid"]
            # Update: delete old vec row and re-insert
            await self.conn.execute(
                "DELETE FROM neuron_vec WHERE rowid = ?", (rid,)
            )
            await self.conn.execute(
                "INSERT INTO neuron_vec(rowid, embedding) VALUES (?, ?)",
                (rid, blob),
            )
        else:
            # Insert mapping first
            cursor = await self.conn.execute(
                "INSERT INTO neuron_vec_map (neuron_id) VALUES (?)", (neuron_id,)
            )
            rid = cursor.lastrowid
            await self.conn.execute(
                "INSERT INTO neuron_vec(rowid, embedding) VALUES (?, ?)",
                (rid, blob),
            )
        await self.conn.commit()

    async def get_embedding(self, neuron_id: str) -> bytes | None:
        """Get the embedding blob for a neuron, or None if not embedded."""
        rows = await self.conn.execute_fetchall(
            "SELECT rowid FROM neuron_vec_map WHERE neuron_id = ?", (neuron_id,)
        )
        if not rows:
            return None
        rid = rows[0]["rowid"]
        vec_rows = await self.conn.execute_fetchall(
            "SELECT embedding FROM neuron_vec WHERE rowid = ?", (rid,)
        )
        return vec_rows[0]["embedding"] if vec_rows else None

    async def delete_embedding(self, neuron_id: str) -> None:
        """Remove an embedding for a neuron."""
        rows = await self.conn.execute_fetchall(
            "SELECT rowid FROM neuron_vec_map WHERE neuron_id = ?", (neuron_id,)
        )
        if rows:
            rid = rows[0]["rowid"]
            await self.conn.execute("DELETE FROM neuron_vec WHERE rowid = ?", (rid,))
            await self.conn.execute("DELETE FROM neuron_vec_map WHERE rowid = ?", (rid,))
            await self.conn.commit()

    async def knn_search(self, query_blob: bytes, *, limit: int = 20) -> list[tuple[str, float]]:
        """Find nearest neighbors. Returns (neuron_id, distance) pairs."""
        rows = await self.conn.execute_fetchall(
            """
            SELECT m.neuron_id, v.distance
            FROM neuron_vec v
            JOIN neuron_vec_map m ON m.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (query_blob, limit),
        )
        return [(row["neuron_id"], row["distance"]) for row in rows]

    @property
    def has_embeddings(self) -> bool:
        """Whether embedding support is enabled."""
        return self._embedding_dimension is not None

    # -- Retrieval boost ----------------------------------------------------

    async def get_retrieval_boost(self, neuron_id: str) -> float:
        rows = await self.conn.execute_fetchall(
            "SELECT boost FROM retrieval_boost WHERE neuron_id = ?", (neuron_id,)
        )
        return rows[0]["boost"] if rows else 0.0

    async def set_retrieval_boost(self, neuron_id: str, boost: float) -> None:
        await self.conn.execute(
            """INSERT INTO retrieval_boost (neuron_id, boost, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(neuron_id) DO UPDATE SET boost=excluded.boost, updated_at=excluded.updated_at""",
            (neuron_id, boost, _ts(datetime.now(timezone.utc))),
        )
        await self.conn.commit()

    async def batch_set_retrieval_boosts(self, updates: dict[str, float]) -> None:
        """Set multiple retrieval boosts in a single transaction."""
        now = _ts(datetime.now(timezone.utc))
        for nid, boost in updates.items():
            await self.conn.execute(
                """INSERT INTO retrieval_boost (neuron_id, boost, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(neuron_id) DO UPDATE SET boost=excluded.boost, updated_at=excluded.updated_at""",
                (nid, boost, now),
            )
        await self.conn.commit()

    async def get_all_retrieval_boosts(self) -> dict[str, float]:
        rows = await self.conn.execute_fetchall("SELECT neuron_id, boost FROM retrieval_boost")
        return {row["neuron_id"]: row["boost"] for row in rows}

    # -- Quiz items ---------------------------------------------------------

    async def insert_quiz_item(self, item: QuizItem) -> None:
        await self.conn.execute(
            """INSERT INTO quiz_item (id, question, answer, hints, grading_criteria,
               scaffold_level, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id,
                item.question,
                item.answer,
                json.dumps(item.hints),
                item.grading_criteria,
                item.scaffold_level,
                _ts(item.created_at),
            ),
        )
        for nid, role in item.neuron_ids.items():
            await self.conn.execute(
                "INSERT INTO quiz_item_neuron (quiz_item_id, neuron_id, role) VALUES (?, ?, ?)",
                (item.id, nid, role.value),
            )
        await self.conn.commit()

    async def get_quiz_items(
        self,
        neuron_id: str,
        *,
        role: QuizItemRole | None = None,
        scaffold_level: str | None = None,
    ) -> list[QuizItem]:
        """Get quiz items associated with a neuron.

        Args:
            neuron_id: The neuron to look up.
            role: Filter by role (primary/supporting). None = any role.
            scaffold_level: Filter by scaffold-level label. None = any level.
        """
        clauses = ["qin.neuron_id = ?"]
        params: list[str] = [neuron_id]
        if role is not None:
            clauses.append("qin.role = ?")
            params.append(role.value)
        where = " AND ".join(clauses)

        rows = await self.conn.execute_fetchall(
            f"""SELECT qi.* FROM quiz_item qi
                JOIN quiz_item_neuron qin ON qin.quiz_item_id = qi.id
                WHERE {where}
                ORDER BY qi.created_at DESC""",
            params,
        )

        items: list[QuizItem] = []
        for row in rows:
            item = await self._hydrate_quiz_item(row)
            if scaffold_level is not None and item.scaffold_level != scaffold_level:
                continue
            items.append(item)
        return items

    async def get_quiz_item(self, item_id: str) -> QuizItem | None:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM quiz_item WHERE id = ?", (item_id,)
        )
        if not rows:
            return None
        return await self._hydrate_quiz_item(rows[0])

    async def delete_quiz_item(self, item_id: str) -> None:
        # quiz_item_neuron rows deleted by ON DELETE CASCADE
        await self.conn.execute("DELETE FROM quiz_item WHERE id = ?", (item_id,))
        await self.conn.commit()

    async def delete_quiz_items_for_neuron(self, neuron_id: str) -> int:
        """Delete all quiz items where this neuron is primary. Returns count."""
        rows = await self.conn.execute_fetchall(
            """SELECT quiz_item_id FROM quiz_item_neuron
               WHERE neuron_id = ? AND role = 'primary'""",
            (neuron_id,),
        )
        ids = [r["quiz_item_id"] for r in rows]
        for qid in ids:
            await self.conn.execute("DELETE FROM quiz_item WHERE id = ?", (qid,))
        await self.conn.commit()
        return len(ids)

    async def _hydrate_quiz_item(self, row: aiosqlite.Row) -> QuizItem:
        """Build a QuizItem from a quiz_item row, loading neuron associations."""
        assoc_rows = await self.conn.execute_fetchall(
            "SELECT neuron_id, role FROM quiz_item_neuron WHERE quiz_item_id = ?",
            (row["id"],),
        )
        neuron_ids = {r["neuron_id"]: QuizItemRole(r["role"]) for r in assoc_rows}
        return QuizItem(
            id=row["id"],
            question=row["question"],
            answer=row["answer"],
            hints=json.loads(row["hints"]),
            grading_criteria=row["grading_criteria"],
            scaffold_level=row["scaffold_level"] if row["scaffold_level"] else None,
            neuron_ids=neuron_ids,
            created_at=_parse_ts(row["created_at"]),
        )

    # -- Source CRUD --------------------------------------------------------

    async def insert_source(self, source: Source) -> None:
        await self.conn.execute(
            """INSERT INTO source (id, url, title, author, section, excerpt,
               storage_uri, content_hash, notes, filterable, searchable,
               accessed_at, fetched_at, http_etag, http_last_modified, status,
               created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source.id,
                source.url,
                source.title,
                source.author,
                source.section,
                source.excerpt,
                source.storage_uri,
                source.content_hash,
                source.notes,
                json.dumps(source.filterable) if source.filterable else None,
                json.dumps(source.searchable) if source.searchable else None,
                _ts(source.accessed_at) if source.accessed_at else None,
                _ts(source.fetched_at) if source.fetched_at else None,
                source.http_etag,
                source.http_last_modified,
                source.status,
                _ts(source.created_at),
            ),
        )
        await self.conn.commit()

    async def get_source(self, source_id: str) -> Source | None:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM source WHERE id = ?", (source_id,)
        )
        return _row_to_source(rows[0]) if rows else None

    async def find_source_by_url(self, url: str) -> Source | None:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM source WHERE url = ?", (url,)
        )
        return _row_to_source(rows[0]) if rows else None

    async def get_sources_for_neuron(self, neuron_id: str) -> list[Source]:
        rows = await self.conn.execute_fetchall(
            """SELECT s.* FROM source s
               JOIN neuron_source ns ON ns.source_id = s.id
               WHERE ns.neuron_id = ?
               ORDER BY s.created_at DESC""",
            (neuron_id,),
        )
        return [_row_to_source(r) for r in rows]

    async def get_neurons_for_source(self, source_id: str) -> list[str]:
        rows = await self.conn.execute_fetchall(
            "SELECT neuron_id FROM neuron_source WHERE source_id = ?",
            (source_id,),
        )
        return [r["neuron_id"] for r in rows]

    async def attach_source(self, neuron_id: str, source_id: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO neuron_source (neuron_id, source_id) VALUES (?, ?)",
            (neuron_id, source_id),
        )
        await self.conn.commit()

    async def update_source(self, source: Source) -> None:
        """Update all mutable fields of an existing Source."""
        await self.conn.execute(
            """UPDATE source SET url=?, title=?, author=?, section=?, excerpt=?,
               storage_uri=?, content_hash=?, notes=?, filterable=?, searchable=?,
               accessed_at=?, fetched_at=?, http_etag=?, http_last_modified=?, status=?
               WHERE id=?""",
            (
                source.url,
                source.title,
                source.author,
                source.section,
                source.excerpt,
                source.storage_uri,
                source.content_hash,
                source.notes,
                json.dumps(source.filterable) if source.filterable else None,
                json.dumps(source.searchable) if source.searchable else None,
                _ts(source.accessed_at) if source.accessed_at else None,
                _ts(source.fetched_at) if source.fetched_at else None,
                source.http_etag,
                source.http_last_modified,
                source.status,
                source.id,
            ),
        )
        await self.conn.commit()

    async def list_sources(self, *, limit: int = 1000) -> list[Source]:
        """List all sources."""
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM source ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [_row_to_source(r) for r in rows]

    async def detach_source(self, neuron_id: str, source_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM neuron_source WHERE neuron_id = ? AND source_id = ?",
            (neuron_id, source_id),
        )
        await self.conn.commit()

    # -- Filtered retrieval -------------------------------------------------

    async def get_filtered_neuron_ids(self, filters: dict[str, str]) -> set[str]:
        """Return neuron IDs matching ALL filters (strict: missing key = excluded).

        Neuron-level keys (type, domain) are matched on the neuron table.
        Other keys are matched via json_extract on source.filterable.
        """
        neuron_filters: dict[str, str] = {}
        source_filters: dict[str, str] = {}
        for k, v in filters.items():
            if k in ("type", "domain"):
                neuron_filters[k] = v
            else:
                source_filters[k] = v

        # Start with all neuron IDs (or those matching neuron-level filters)
        # retired_at IS NULL keeps soft-retired neurons out of retrieval.
        if neuron_filters:
            clauses = [f"{k} = ?" for k in neuron_filters]
            clauses.append("retired_at IS NULL")
            sql = f"SELECT id FROM neuron WHERE {' AND '.join(clauses)}"
            rows = await self.conn.execute_fetchall(sql, tuple(neuron_filters.values()))
            result = {r["id"] for r in rows}
        else:
            rows = await self.conn.execute_fetchall(
                "SELECT id FROM neuron WHERE retired_at IS NULL"
            )
            result = {r["id"] for r in rows}

        if not result or not source_filters:
            return result

        # For each source filter key, find neurons whose source has that key=value
        for key, value in source_filters.items():
            rows = await self.conn.execute_fetchall(
                """SELECT DISTINCT ns.neuron_id FROM neuron_source ns
                   JOIN source s ON ns.source_id = s.id
                   WHERE s.filterable IS NOT NULL
                     AND json_extract(s.filterable, ?) = ?""",
                (f"$.{key}", value),
            )
            matching = {r["neuron_id"] for r in rows}
            result &= matching  # strict intersection
            if not result:
                break

        return result

    # -- Metadata discovery -------------------------------------------------

    async def get_meta_keys(self) -> list[dict]:
        """Get distinct filterable + searchable keys with counts and samples.

        Returns list of dicts: {key, layer, count, sample_values}.
        """
        results: list[dict] = []
        for layer, col in [("filterable", "filterable"), ("searchable", "searchable")]:
            rows = await self.conn.execute_fetchall(
                f"""SELECT key, COUNT(*) as cnt,
                       GROUP_CONCAT(DISTINCT value) as samples
                    FROM source, json_each(source.{col})
                    WHERE source.{col} IS NOT NULL
                    GROUP BY key
                    ORDER BY cnt DESC"""
            )
            for r in rows:
                samples = r["samples"] or ""
                sample_list = samples.split(",")[:5]  # max 5 samples
                results.append({
                    "key": r["key"],
                    "layer": layer,
                    "count": r["cnt"],
                    "sample_values": sample_list,
                })
        return results

    async def get_meta_values(self, key: str) -> list[dict]:
        """Get distinct values for a filterable or searchable key with counts.

        Searches both filterable and searchable columns.
        Returns list of dicts: {value, layer, count}.
        """
        results: list[dict] = []
        for layer, col in [("filterable", "filterable"), ("searchable", "searchable")]:
            rows = await self.conn.execute_fetchall(
                f"""SELECT value, COUNT(*) as cnt
                    FROM source, json_each(source.{col})
                    WHERE source.{col} IS NOT NULL AND key = ?
                    GROUP BY value
                    ORDER BY cnt DESC""",
                (key,),
            )
            for r in rows:
                results.append({
                    "value": r["value"],
                    "layer": layer,
                    "count": r["cnt"],
                })
        return results

    async def get_domain_counts(self) -> list[dict]:
        """Get domain names with neuron counts (live only)."""
        rows = await self.conn.execute_fetchall(
            """SELECT domain, COUNT(*) as count FROM neuron
               WHERE domain IS NOT NULL AND domain != ''
                 AND retired_at IS NULL
               GROUP BY domain ORDER BY count DESC"""
        )
        return [{"domain": r["domain"], "count": r["count"]} for r in rows]

    async def get_stale_sources(self, stale_days: int) -> list[Source]:
        """Get URL sources older than stale_days since last fetch."""
        rows = await self.conn.execute_fetchall(
            """SELECT * FROM source
               WHERE url IS NOT NULL AND url LIKE 'http%'
               AND (fetched_at IS NULL
                    OR julianday('now') - julianday(fetched_at) > ?)
               ORDER BY fetched_at ASC""",
            (stale_days,),
        )
        return [_row_to_source(r) for r in rows]

    async def rename_domain(self, old: str, new: str) -> int:
        """Rename all neurons with domain=old to domain=new. Returns count."""
        cursor = await self.conn.execute(
            "UPDATE neuron SET domain = ? WHERE domain = ?", (new, old)
        )
        await self.conn.commit()
        return cursor.rowcount

    async def merge_domains(self, sources: list[str], target: str) -> int:
        """Merge multiple domains into target. Returns total count."""
        total = 0
        for src in sources:
            if src == target:
                continue
            cursor = await self.conn.execute(
                "UPDATE neuron SET domain = ? WHERE domain = ?", (target, src)
            )
            total += cursor.rowcount
        await self.conn.commit()
        return total

    # -- Community ----------------------------------------------------------

    async def batch_update_community_ids(self, mapping: dict[str, int]) -> None:
        """Set community_id for multiple neurons in a single transaction."""
        for nid, cid in mapping.items():
            await self.conn.execute(
                "UPDATE neuron SET community_id = ? WHERE id = ?", (cid, nid)
            )
        await self.conn.commit()

    async def get_community_ids(self) -> dict[str, int]:
        """Return {neuron_id: community_id} for live neurons with a community."""
        rows = await self.conn.execute_fetchall(
            "SELECT id, community_id FROM neuron "
            "WHERE community_id IS NOT NULL AND retired_at IS NULL"
        )
        return {r["id"]: r["community_id"] for r in rows}

    # -- Retrieve log -------------------------------------------------------

    async def log_retrieve(self, query: str, neuron_ids: list[str]) -> None:
        await self.conn.execute(
            "INSERT INTO retrieve_log (query, neuron_ids, retrieved_at) VALUES (?, ?, ?)",
            (query, json.dumps(neuron_ids), _ts(datetime.now(timezone.utc))),
        )
        await self.conn.commit()


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------


def _row_to_neuron(row: aiosqlite.Row) -> Neuron:
    return Neuron(
        id=row["id"],
        content=row["content"],
        type=row["type"],
        domain=row["domain"],
        source=row["source"],
        created_at=_parse_ts(row["created_at"]),
        updated_at=_parse_ts(row["updated_at"]),
    )


def _row_to_synapse(row: aiosqlite.Row) -> Synapse:
    keys = row.keys()
    confidence_raw = row["confidence"] if "confidence" in keys else "extracted"
    confidence_score = row["confidence_score"] if "confidence_score" in keys else 1.0
    return Synapse(
        pre=row["pre"],
        post=row["post"],
        type=SynapseType(row["type"]),
        weight=row["weight"],
        co_fires=row["co_fires"],
        last_co_fire=_parse_ts(row["last_co_fire"]) if row["last_co_fire"] else None,
        confidence=SynapseConfidence(confidence_raw),
        confidence_score=confidence_score,
        created_at=_parse_ts(row["created_at"]),
        updated_at=_parse_ts(row["updated_at"]),
    )


def _row_to_source(row: aiosqlite.Row) -> Source:
    keys = row.keys()
    filterable_raw = row["filterable"] if "filterable" in keys else None
    searchable_raw = row["searchable"] if "searchable" in keys else None
    return Source(
        id=row["id"],
        url=row["url"],
        title=row["title"],
        author=row["author"],
        section=row["section"],
        excerpt=row["excerpt"],
        storage_uri=row["storage_uri"],
        content_hash=row["content_hash"],
        notes=row["notes"],
        filterable=json.loads(filterable_raw) if filterable_raw else None,
        searchable=json.loads(searchable_raw) if searchable_raw else None,
        accessed_at=_parse_ts(row["accessed_at"]) if row["accessed_at"] else None,
        fetched_at=_parse_ts(row["fetched_at"]) if "fetched_at" in keys and row["fetched_at"] else None,
        http_etag=row["http_etag"] if "http_etag" in keys else None,
        http_last_modified=row["http_last_modified"] if "http_last_modified" in keys else None,
        status=row["status"] if "status" in keys and row["status"] else "active",
        created_at=_parse_ts(row["created_at"]),
    )


def _row_to_spike(row: aiosqlite.Row) -> Spike:
    keys = row.keys()
    return Spike(
        neuron_id=row["neuron_id"],
        grade=Grade(row["grade"]),
        fired_at=_parse_ts(row["fired_at"]),
        session_id=row["session_id"],
        notes=row["notes"] if "notes" in keys else None,
    )


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)
