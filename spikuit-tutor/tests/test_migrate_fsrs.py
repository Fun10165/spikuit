"""Tests for ``scripts/migrate_fsrs_to_tutor.py`` — the Stage 2 FSRS migration.

Design ref: ``docs/design/tutor-extraction-stage2.md`` §6 / §7. §7 asks
for a fixture substrate DB with ``fsrs_state`` rows → run the script →
assert ``fsrs_card`` parity, idempotency on re-run, and that
``--reverse`` round-trips.

``card_json`` survives the migration verbatim: ``Card.from_json`` and
``Card.to_json`` round-trip exactly, so these tests compare the raw JSON
strings rather than reconstructed ``Card`` objects.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from fsrs import Card, State

# The migration script lives in scripts/, not an installed package — load
# it by path so the test can call its async functions directly.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_fsrs_to_tutor.py"
_spec = importlib.util.spec_from_file_location("migrate_fsrs_to_tutor", _SCRIPT)
assert _spec is not None and _spec.loader is not None
migrate_fsrs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate_fsrs)


# A pre-Stage-2 substrate carried FSRS state in this table.
_FSRS_STATE_SCHEMA = """
CREATE TABLE fsrs_state (
    neuron_id TEXT PRIMARY KEY,
    card_json TEXT NOT NULL
);
"""


def _sample_rows() -> dict[str, str]:
    """Two cards as ``{neuron_id: card_json}``: one fresh, one reviewed."""
    fresh = Card()
    reviewed = Card()
    reviewed.state = State.Review
    reviewed.stability = 12.0
    reviewed.difficulty = 6.5
    return {"n1": fresh.to_json(), "n2": reviewed.to_json()}


def _make_substrate_db(path: Path, rows: dict[str, str]) -> None:
    """Build a pre-Stage-2 substrate DB carrying ``fsrs_state`` rows."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_FSRS_STATE_SCHEMA)
        conn.executemany(
            "INSERT INTO fsrs_state (neuron_id, card_json) VALUES (?, ?)",
            list(rows.items()),
        )
        conn.commit()
    finally:
        conn.close()


def _make_substrate_db_no_fsrs(path: Path) -> None:
    """A Stage-2-fresh substrate DB — has neurons but no ``fsrs_state``."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE neuron (id TEXT PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()


def _read_card_json(path: Path, table: str) -> dict[str, str]:
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(f"SELECT neuron_id, card_json FROM {table}").fetchall()
    finally:
        conn.close()
    return {nid: card_json for nid, card_json in rows}


def _read_created_at(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("SELECT neuron_id, created_at FROM fsrs_card").fetchall()
    finally:
        conn.close()
    return {nid: created for nid, created in rows}


# -- Forward ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_parity(tmp_path):
    """Every ``fsrs_state`` row lands in ``fsrs_card`` with card_json verbatim."""
    rows = _sample_rows()
    substrate = tmp_path / "brain.db"
    overlay = tmp_path / "brain.tutor.db"
    _make_substrate_db(substrate, rows)

    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=False)

    assert _read_card_json(overlay, "fsrs_card") == rows


@pytest.mark.asyncio
async def test_forward_idempotent(tmp_path):
    """Re-running forward upserts in place — no duplicates, created_at kept."""
    rows = _sample_rows()
    substrate = tmp_path / "brain.db"
    overlay = tmp_path / "brain.tutor.db"
    _make_substrate_db(substrate, rows)

    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=False)
    created_first = _read_created_at(overlay)

    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=False)
    created_second = _read_created_at(overlay)

    assert _read_card_json(overlay, "fsrs_card") == rows
    # created_at is stamped once; a re-run that re-inserted would reset it.
    assert created_second == created_first


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(tmp_path):
    """``--dry-run`` reports counts but never creates the overlay file."""
    rows = _sample_rows()
    substrate = tmp_path / "brain.db"
    overlay = tmp_path / "brain.tutor.db"
    _make_substrate_db(substrate, rows)

    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=True)

    assert not overlay.exists()


@pytest.mark.asyncio
async def test_forward_substrate_without_fsrs_state(tmp_path):
    """A substrate DB with no ``fsrs_state`` table → clean no-op."""
    substrate = tmp_path / "brain.db"
    overlay = tmp_path / "brain.tutor.db"
    _make_substrate_db_no_fsrs(substrate)

    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=False)

    assert not overlay.exists()


@pytest.mark.asyncio
async def test_forward_missing_substrate(tmp_path):
    """A missing substrate DB is reported, not crashed on."""
    substrate = tmp_path / "absent.db"
    overlay = tmp_path / "absent.tutor.db"

    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=False)

    assert not overlay.exists()


# -- Reverse ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_round_trips(tmp_path):
    """forward → wipe ``fsrs_state`` → reverse restores it verbatim."""
    rows = _sample_rows()
    substrate = tmp_path / "brain.db"
    overlay = tmp_path / "brain.tutor.db"
    _make_substrate_db(substrate, rows)

    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=False)

    # Simulate a rollback scenario: the table has been emptied.
    conn = sqlite3.connect(str(substrate))
    conn.execute("DELETE FROM fsrs_state")
    conn.commit()
    conn.close()

    await migrate_fsrs.migrate_reverse(substrate, overlay, dry_run=False)

    assert _read_card_json(substrate, "fsrs_state") == rows


@pytest.mark.asyncio
async def test_reverse_recreates_missing_table(tmp_path):
    """``--reverse`` onto a DB whose ``fsrs_state`` was dropped recreates it."""
    rows = _sample_rows()
    src = tmp_path / "src.db"
    overlay = tmp_path / "src.tutor.db"
    _make_substrate_db(src, rows)
    await migrate_fsrs.migrate_forward(src, overlay, dry_run=False)

    # A fresh substrate DB with no fsrs_state table at all.
    fresh = tmp_path / "fresh.db"
    _make_substrate_db_no_fsrs(fresh)

    await migrate_fsrs.migrate_reverse(fresh, overlay, dry_run=False)

    assert _read_card_json(fresh, "fsrs_state") == rows


@pytest.mark.asyncio
async def test_reverse_dry_run_writes_nothing(tmp_path):
    """``--reverse --dry-run`` leaves the substrate DB untouched."""
    rows = _sample_rows()
    substrate = tmp_path / "brain.db"
    overlay = tmp_path / "brain.tutor.db"
    _make_substrate_db(substrate, rows)
    await migrate_fsrs.migrate_forward(substrate, overlay, dry_run=False)

    conn = sqlite3.connect(str(substrate))
    conn.execute("DELETE FROM fsrs_state")
    conn.commit()
    conn.close()

    await migrate_fsrs.migrate_reverse(substrate, overlay, dry_run=True)

    assert _read_card_json(substrate, "fsrs_state") == {}
