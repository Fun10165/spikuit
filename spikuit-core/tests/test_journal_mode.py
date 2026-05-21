"""Tests for configurable SQLite ``journal_mode``.

A Brain vault synced across machines (Syncthing, Dropbox, ...) cannot use
WAL mode: the ``-wal`` / ``-shm`` sidecars are per-machine and a sync that
catches them mid-checkpoint can corrupt the database. ``journal_mode`` is
therefore configurable per Brain — default ``WAL``, ``DELETE`` for vaults.
"""

import pytest

from spikuit_core.config import BrainConfig, DatabaseConfig, load_config
from spikuit_core.db import Database, normalize_journal_mode


# -- normalize_journal_mode -------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("wal", "WAL"),
        ("DELETE", "DELETE"),
        ("  delete  ", "DELETE"),
        ("Truncate", "TRUNCATE"),
    ],
)
def test_normalize_journal_mode_canonicalizes(raw, expected):
    assert normalize_journal_mode(raw) == expected


def test_normalize_journal_mode_rejects_unknown():
    with pytest.raises(ValueError, match="unsupported journal_mode"):
        normalize_journal_mode("bogus")


# -- DatabaseConfig parsing -------------------------------------------------


def test_database_config_defaults_to_wal():
    assert DatabaseConfig().journal_mode == "WAL"
    assert BrainConfig().database.journal_mode == "WAL"


def test_load_config_reads_database_section(tmp_path):
    spikuit_dir = tmp_path / ".spikuit"
    spikuit_dir.mkdir()
    (spikuit_dir / "config.toml").write_text(
        '[brain]\nname = "vault"\n\n[database]\njournal_mode = "DELETE"\n'
    )
    config = load_config(tmp_path)
    assert config.database.journal_mode == "DELETE"


def test_load_config_database_section_absent_defaults_wal(tmp_path):
    spikuit_dir = tmp_path / ".spikuit"
    spikuit_dir.mkdir()
    (spikuit_dir / "config.toml").write_text('[brain]\nname = "plain"\n')
    config = load_config(tmp_path)
    assert config.database.journal_mode == "WAL"


# -- Database applies the mode ---------------------------------------------


@pytest.mark.asyncio
async def test_database_applies_delete_mode(tmp_path):
    db = Database(tmp_path / "circuit.db", journal_mode="DELETE")
    await db.connect()
    try:
        cur = await db._conn.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
        assert row[0].upper() == "DELETE"
    finally:
        await db.close()
    # DELETE mode never leaves a -wal sidecar behind — the whole point.
    assert not (tmp_path / "circuit.db-wal").exists()


@pytest.mark.asyncio
async def test_database_defaults_to_wal(tmp_path):
    db = Database(tmp_path / "circuit.db")
    await db.connect()
    try:
        cur = await db._conn.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
        assert row[0].upper() == "WAL"
    finally:
        await db.close()


def test_database_rejects_unknown_journal_mode(tmp_path):
    with pytest.raises(ValueError, match="unsupported journal_mode"):
        Database(tmp_path / "circuit.db", journal_mode="bogus")
