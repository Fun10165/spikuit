"""Tutor FSRS overlay store — spikuit-tutor's own card-state database.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.1) re-homes FSRS
card state out of ``spikuit-core``'s ``fsrs_state`` table and into a
``spikuit-tutor``-owned SQLite store, joined to the substrate by
``neuron_id``. This module is that store.

The store holds exactly one table, ``fsrs_card``. It owns no graph data
— every topology read goes to the substrate live through the appkit
contract. The only cross-database integrity concern is orphaned cards
(a card whose neuron was deleted in the substrate); that is handled by
:meth:`TutorStore.reconcile`, run on open.

The store is a *per-overlay* file: one substrate KB may be reviewed by
several overlays (a second tutor, an experiment), each with its own
overlay DB. The overlay path is therefore configurable;
:func:`default_overlay_path` only supplies the common single-tutor
default of ``<substrate-stem>.tutor.db``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import aiosqlite
from fsrs import Card
from spikuit_core.appkit import normalize_journal_mode

# The overlay holds exactly one table. No `due` index: the tutor loads
# every card into memory on open, exactly as `Circuit` did pre-Stage-2.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS fsrs_card (
    neuron_id   TEXT PRIMARY KEY,   -- logical join to substrate neuron.id
    card_json   TEXT NOT NULL,
    reviewed_at TEXT,               -- last review timestamp, NULL until reviewed
    created_at  TEXT NOT NULL       -- when this card row first appeared
);
"""


def default_overlay_path(substrate_db_path: str | Path) -> Path:
    """Default overlay DB path for a substrate DB: ``<stem>.tutor.db``.

    The common single-tutor convention from §4.1. A substrate at
    ``~/.spikuit/spikuit.db`` gets an overlay at
    ``~/.spikuit/spikuit.tutor.db``. Callers reviewing one substrate
    with several overlays pass explicit paths instead.
    """
    return Path(substrate_db_path).with_suffix(".tutor.db")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _reviewed_at(card: Card) -> str | None:
    """ISO-8601 last-review timestamp of a card, or ``None`` if the card
    has never been reviewed (a fresh ``Card()`` has ``last_review`` unset).
    """
    last = getattr(card, "last_review", None)
    return last.isoformat() if isinstance(last, datetime) else None


class TutorStore:
    """SQLite-backed FSRS card store, owned by ``spikuit-tutor``.

    Mirrors how ``Circuit`` cached cards pre-Stage-2: every card is
    loaded into an in-memory dict on :meth:`open`, reads hit the cache,
    and writes go through to both the cache and the DB.
    """

    def __init__(self, db_path: str | Path, *, journal_mode: str = "WAL") -> None:
        self.db_path: Path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._cards: dict[str, Card] = {}
        # The overlay DB lives beside the substrate DB, so it must use the
        # same journal mode — a synced vault needs both files sidecar-free.
        self._journal_mode = normalize_journal_mode(journal_mode)

    # -- Lifecycle ----------------------------------------------------------

    async def open(
        self, *, known_neuron_ids: Iterable[str] | None = None
    ) -> list[str]:
        """Connect, create the schema, and load every card into memory.

        If ``known_neuron_ids`` is given, reconcile-on-open runs (§4.4):
        any ``fsrs_card`` row whose ``neuron_id`` is absent from that set
        is pruned as an orphan. Returns the list of pruned neuron IDs
        (empty when no reconcile was requested).
        """
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        await self._load()
        if known_neuron_ids is not None:
            return await self.reconcile(known_neuron_ids)
        return []

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("TutorStore is not open; call open() first.")
        return self._conn

    async def _load(self) -> None:
        """Load every ``fsrs_card`` row into the in-memory cache."""
        self._cards.clear()
        rows = await self.conn.execute_fetchall(
            "SELECT neuron_id, card_json FROM fsrs_card"
        )
        for row in rows:
            self._cards[row["neuron_id"]] = Card.from_json(row["card_json"])

    # -- Reads --------------------------------------------------------------

    def get_card(self, neuron_id: str) -> Card | None:
        """The cached FSRS card for a neuron, or ``None`` if it has no
        card yet (never reviewed — cards are created lazily, §4.4).
        """
        return self._cards.get(neuron_id)

    def cards(self) -> dict[str, Card]:
        """A copy of the full ``{neuron_id: Card}`` map."""
        return dict(self._cards)

    def card_ids(self) -> set[str]:
        """The set of neuron IDs that currently have a card.

        The tutor's due query unions past-due cards with neurons that
        have *no* card (the new/unlearned bucket); this set is the right
        operand of that difference (§4.4).
        """
        return set(self._cards)

    # -- Writes -------------------------------------------------------------

    async def upsert_card(self, neuron_id: str, card: Card) -> None:
        """Persist a card to both the cache and the DB.

        ``created_at`` is stamped once, on first insert, and preserved
        across later upserts; ``reviewed_at`` always tracks the card's
        current last-review timestamp.
        """
        self._cards[neuron_id] = card
        await self.conn.execute(
            """INSERT INTO fsrs_card (neuron_id, card_json, reviewed_at, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(neuron_id) DO UPDATE SET
                   card_json   = excluded.card_json,
                   reviewed_at = excluded.reviewed_at""",
            (neuron_id, card.to_json(), _reviewed_at(card), _now_iso()),
        )
        await self.conn.commit()

    async def delete_card(self, neuron_id: str) -> bool:
        """Drop a single card from the cache and the DB.

        Returns ``True`` if a row existed.
        """
        self._cards.pop(neuron_id, None)
        cur = await self.conn.execute(
            "DELETE FROM fsrs_card WHERE neuron_id=?", (neuron_id,)
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def reconcile(self, known_neuron_ids: Iterable[str]) -> list[str]:
        """Prune orphan cards — rows whose neuron no longer exists.

        SQLite cannot enforce a cross-file foreign key, so referential
        integrity between ``fsrs_card.neuron_id`` and the substrate's
        ``neuron.id`` is the tutor's responsibility (§4.1). Stage 2
        handles it with this reconcile-on-open sweep rather than a live
        event-driven reaper (§4.4 — the reaper is deferred).

        Idempotent. Returns the neuron IDs that were pruned.
        """
        known = set(known_neuron_ids)
        orphans = [nid for nid in self._cards if nid not in known]
        for nid in orphans:
            self._cards.pop(nid, None)
        if orphans:
            await self.conn.executemany(
                "DELETE FROM fsrs_card WHERE neuron_id=?",
                [(nid,) for nid in orphans],
            )
            await self.conn.commit()
        return orphans
