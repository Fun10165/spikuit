"""Smoke tests for the AMKB v0.7.0 schema additions.

These verify the migration lands cleanly and the new tables/columns
exist. Behavioral tests for soft-retire, events, and transactions
land in later commits.
"""

from __future__ import annotations

import pytest

from spikuit_core.db import Database


@pytest.mark.asyncio
async def test_amkb_tables_created(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        cur = await db.conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN "
            "('changeset', 'event', 'neuron_predecessor')"
        )
        names = {row[0] async for row in cur}
        assert names == {"changeset", "event", "neuron_predecessor"}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_retired_at_columns_added(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        for table in ("neuron", "synapse"):
            cur = await db.conn.execute(f"PRAGMA table_info({table})")
            cols = {row[1] async for row in cur}
            assert "retired_at" in cols, f"{table}.retired_at missing"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_migration_is_idempotent(tmp_path):
    """Connecting twice must not error on already-applied migrations."""
    path = tmp_path / "test.db"
    db = Database(path)
    await db.connect()
    await db.close()

    db2 = Database(path)
    await db2.connect()
    try:
        cur = await db2.conn.execute("PRAGMA table_info(neuron)")
        cols = {row[1] async for row in cur}
        assert "retired_at" in cols
    finally:
        await db2.close()


@pytest.mark.asyncio
async def test_changeset_insert_roundtrip(tmp_path):
    """Basic write/read on the new changeset table."""
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.conn.execute(
            "INSERT INTO changeset "
            "(id, tag, actor_id, actor_kind, started_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("cs1", "test", "tester", "system", "2026-04-13T00:00:00Z", "open"),
        )
        await db.conn.commit()
        cur = await db.conn.execute("SELECT id, status FROM changeset")
        rows = [(row["id"], row["status"]) async for row in cur]
        assert rows == [("cs1", "open")]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_list_changesets_filters_and_orders_history(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        records = [
            ("cs-offset", "review", "bob", "2026-04-13T01:00:00.500000+01:00"),
            ("cs-a", "ingest", "alice", "2026-04-13T00:00:01+00:00"),
            ("cs-b", "review", "bob", "2026-04-13T00:00:02+00:00"),
            ("cs-c", "ingest", "alice", "2026-04-13T00:00:03+00:00"),
        ]
        for changeset_id, tag, actor_id, committed_at in records:
            await db.insert_changeset_open(
                changeset_id=changeset_id,
                tag=tag,
                actor_id=actor_id,
                actor_kind="human",
                started_at=committed_at,
            )
            await db.commit_changeset(
                changeset_id,
                events=[],
                committed_at=committed_at,
            )

        await db.insert_changeset_open(
            changeset_id="cs-aborted",
            tag="ingest",
            actor_id="alice",
            actor_kind="human",
            started_at="2026-04-13T00:00:04+00:00",
        )
        await db.abort_changeset("cs-aborted")

        assert [row["id"] for row in await db.list_changesets()] == [
            "cs-offset",
            "cs-a",
            "cs-b",
            "cs-c",
        ]
        assert [
            row["id"]
            for row in await db.list_changesets(
                since="2026-04-13T00:00:02+00:00",
                until="2026-04-13T00:00:03+00:00",
            )
        ] == ["cs-b", "cs-c"]
        assert [
            row["id"]
            for row in await db.list_changesets(
                since="2026-04-13T00:00:00.750000Z",
                until="2026-04-13T01:00:01+01:00",
            )
        ] == ["cs-a"]
        assert [
            row["id"]
            for row in await db.list_changesets(actor_id="alice", tag="ingest")
        ] == ["cs-a", "cs-c"]
        assert [
            row["id"] for row in await db.list_changesets(status=None)
        ] == ["cs-offset", "cs-a", "cs-b", "cs-c", "cs-aborted"]
        assert [
            row["id"]
            for row in await db.list_changesets(status=None, limit=4)
        ] == ["cs-offset", "cs-a", "cs-b", "cs-c"]
        assert len(await db.list_changesets(limit=1)) == 1
        with pytest.raises(ValueError, match="limit must be non-negative"):
            await db.list_changesets(limit=-1)
    finally:
        await db.close()
