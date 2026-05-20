"""Migrate FSRS card state from spikuit-core into the spikuit-tutor overlay.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §6) re-homes FSRS
card state out of ``spikuit-core``'s ``fsrs_state`` table and into a
``spikuit-tutor``-owned overlay DB (the ``fsrs_card`` table). This
script copies the rows across; it mirrors the ``migrate_tataque.py``
pattern (argparse, ``--dry-run``, ``--brain`` / explicit ``--db-path``).

Usage::

    # Dry run — print counts and source/target paths, write nothing
    uv run python scripts/migrate_fsrs_to_tutor.py --dry-run

    # Forward migration of the current brain's substrate DB
    uv run python scripts/migrate_fsrs_to_tutor.py

    # Explicit substrate DB path
    uv run python scripts/migrate_fsrs_to_tutor.py --db-path ~/.spikuit/spikuit.db

    # Rollback: copy the overlay's cards back into `fsrs_state`
    uv run python scripts/migrate_fsrs_to_tutor.py --reverse

Forward is **idempotent** — re-running upserts by ``neuron_id`` and is a
no-op on an already-migrated DB. It does **not** drop ``fsrs_state``:
that table is left dormant for one release so rollback is a pure code
revert with nothing lost (§6, two-phase table drop). The ``--reverse``
flag exists for the case where reviews happened post-migration and the
fresh cards must be copied back into ``fsrs_state``.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

from fsrs import Card

from spikuit_core.config import load_config
from spikuit_tutor import TutorStore, default_overlay_path

# The substrate's original (pre-Stage-2) FSRS table. `--reverse`
# recreates it verbatim when rolling back onto a DB that has already
# had the table dropped; in the dormant window it still exists and the
# IF NOT EXISTS makes the statement a harmless no-op.
_FSRS_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS fsrs_state (
    neuron_id TEXT PRIMARY KEY REFERENCES neuron(id),
    card_json TEXT NOT NULL
);
"""


def _resolve_paths(
    brain: Path | None, db_path: Path | None, overlay_path: Path | None
) -> tuple[Path, Path]:
    """Resolve (substrate DB path, tutor overlay DB path).

    ``--db-path`` wins outright; otherwise the substrate DB is read from
    the brain config. The overlay defaults to ``<substrate-stem>.tutor.db``
    (§4.1) unless ``--overlay-path`` pins it explicitly.
    """
    if db_path is not None:
        substrate = db_path.expanduser()
    else:
        substrate = Path(load_config(brain).db_path)
    overlay = (
        overlay_path.expanduser()
        if overlay_path is not None
        else default_overlay_path(substrate)
    )
    return substrate, overlay


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    """Whether a table exists in a sqlite connection."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


# ── Forward: fsrs_state → fsrs_card ──────────────────────────────────


async def migrate_forward(
    substrate_path: Path, overlay_path: Path, *, dry_run: bool
) -> None:
    """Copy every ``fsrs_state`` row into the tutor overlay's ``fsrs_card``."""
    if not substrate_path.exists():
        print(f"substrate DB not found: {substrate_path}")
        return

    sdb = sqlite3.connect(str(substrate_path))
    sdb.row_factory = sqlite3.Row
    try:
        if not _has_table(sdb, "fsrs_state"):
            print(f"substrate: {substrate_path}")
            print("  no `fsrs_state` table — nothing to migrate")
            print("  (a Stage-2-fresh DB, or already past the dormant window)")
            return
        rows = sdb.execute(
            "SELECT neuron_id, card_json FROM fsrs_state"
        ).fetchall()
    finally:
        sdb.close()

    print(f"substrate: {substrate_path}  ({len(rows)} fsrs_state row(s))")
    print(f"overlay:   {overlay_path}")

    if dry_run:
        print(f"\n=== DRY RUN === would upsert {len(rows)} card(s) into fsrs_card")
        return
    if not rows:
        print("\nno rows to migrate — overlay left untouched")
        return

    store = TutorStore(overlay_path)
    await store.open()
    try:
        migrated = 0
        for row in rows:
            card = Card.from_json(row["card_json"])
            await store.upsert_card(row["neuron_id"], card)
            migrated += 1
    finally:
        await store.close()

    print(f"\n=== Migration complete === {migrated} card(s) in fsrs_card")
    print("`fsrs_state` left intact (dormant) — see §6 two-phase table drop.")


# ── Reverse: fsrs_card → fsrs_state ──────────────────────────────────


async def migrate_reverse(
    substrate_path: Path, overlay_path: Path, *, dry_run: bool
) -> None:
    """Roll back: copy the overlay's ``fsrs_card`` rows into ``fsrs_state``."""
    if not overlay_path.exists():
        print(f"tutor overlay DB not found: {overlay_path}")
        return

    store = TutorStore(overlay_path)
    await store.open()
    try:
        cards = store.cards()
    finally:
        await store.close()

    print(f"overlay:   {overlay_path}  ({len(cards)} fsrs_card row(s))")
    print(f"substrate: {substrate_path}")

    if dry_run:
        print(f"\n=== DRY RUN === would upsert {len(cards)} card(s) into fsrs_state")
        return
    if not substrate_path.exists():
        print(f"\nsubstrate DB not found: {substrate_path}")
        return

    sdb = sqlite3.connect(str(substrate_path))
    try:
        sdb.executescript(_FSRS_STATE_SCHEMA)
        restored = 0
        for nid, card in cards.items():
            sdb.execute(
                """INSERT INTO fsrs_state (neuron_id, card_json) VALUES (?, ?)
                   ON CONFLICT(neuron_id) DO UPDATE SET
                       card_json = excluded.card_json""",
                (nid, card.to_json()),
            )
            restored += 1
        sdb.commit()
    finally:
        sdb.close()

    print(f"\n=== Rollback complete === {restored} card(s) restored to fsrs_state")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate FSRS card state: spikuit-core fsrs_state ↔ "
        "spikuit-tutor overlay fsrs_card"
    )
    parser.add_argument(
        "--brain", type=Path, default=None, help="Brain root directory"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Explicit substrate DB path (overrides --brain)",
    )
    parser.add_argument(
        "--overlay-path",
        type=Path,
        default=None,
        help="Explicit tutor overlay DB path (default: <substrate-stem>.tutor.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts and source/target paths without writing",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Rollback: copy fsrs_card back into fsrs_state",
    )
    args = parser.parse_args()

    substrate_path, overlay_path = _resolve_paths(
        args.brain, args.db_path, args.overlay_path
    )
    if args.reverse:
        asyncio.run(
            migrate_reverse(substrate_path, overlay_path, dry_run=args.dry_run)
        )
    else:
        asyncio.run(
            migrate_forward(substrate_path, overlay_path, dry_run=args.dry_run)
        )


if __name__ == "__main__":
    main()
