"""Tests for spikuit_tutor.store — the FSRS overlay store (Stage 2 §5.1).

Exercises the store in isolation: no substrate, no Circuit. The store's
only contract with the substrate is the ``neuron_id`` join key and the
reconcile sweep, both of which are tested here with plain ID sets.
"""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
from fsrs import Card, Rating, Scheduler

from spikuit_tutor.store import TutorStore, default_overlay_path


def _reviewed_card() -> Card:
    """A card that has been through one FSRS review (``last_review`` set)."""
    card, _log = Scheduler().review_card(
        Card(), Rating.Good, dt.datetime.now(dt.timezone.utc)
    )
    return card


@pytest_asyncio.fixture
async def store(tmp_path):
    s = TutorStore(tmp_path / "test.tutor.db")
    await s.open()
    yield s
    await s.close()


# -- default_overlay_path ----------------------------------------------------


def test_default_overlay_path_swaps_suffix():
    assert default_overlay_path("/x/.spikuit/spikuit.db").name == "spikuit.tutor.db"
    # The substrate stem is preserved, only the suffix changes.
    assert default_overlay_path("/x/brainA.db").as_posix() == "/x/brainA.tutor.db"


# -- lifecycle ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_empty_db_has_no_cards(store):
    assert store.cards() == {}
    assert store.card_ids() == set()
    assert store.get_card("n1") is None


@pytest.mark.asyncio
async def test_conn_before_open_raises(tmp_path):
    s = TutorStore(tmp_path / "x.tutor.db")
    with pytest.raises(RuntimeError, match="not open"):
        _ = s.conn


@pytest.mark.asyncio
async def test_open_creates_db_file(tmp_path):
    path = tmp_path / "nested" / "deep" / "x.tutor.db"
    s = TutorStore(path)
    await s.open()
    await s.close()
    assert path.exists()


# -- upsert / get ------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_then_get_roundtrips(store):
    card = _reviewed_card()
    await store.upsert_card("n1", card)
    got = store.get_card("n1")
    assert got is not None
    assert got.due == card.due
    assert got.stability == card.stability


@pytest.mark.asyncio
async def test_upsert_persists_across_reopen(tmp_path):
    path = tmp_path / "persist.tutor.db"
    card = _reviewed_card()

    s1 = TutorStore(path)
    await s1.open()
    await s1.upsert_card("n1", card)
    await s1.close()

    s2 = TutorStore(path)
    await s2.open()
    reloaded = s2.get_card("n1")
    assert reloaded is not None
    assert reloaded.due == card.due
    await s2.close()


@pytest.mark.asyncio
async def test_upsert_preserves_created_at_updates_reviewed_at(store):
    await store.upsert_card("n1", Card())  # fresh card: never reviewed

    async def _row():
        rows = await store.conn.execute_fetchall(
            "SELECT created_at, reviewed_at FROM fsrs_card WHERE neuron_id='n1'"
        )
        return rows[0]

    first = await _row()
    assert first["reviewed_at"] is None  # a fresh Card() has no last_review

    await store.upsert_card("n1", _reviewed_card())  # re-upsert, now reviewed
    second = await _row()
    assert second["created_at"] == first["created_at"]  # stamped once
    assert second["reviewed_at"] is not None  # now tracks the review


@pytest.mark.asyncio
async def test_cards_and_card_ids(store):
    await store.upsert_card("n1", Card())
    await store.upsert_card("n2", Card())
    assert store.card_ids() == {"n1", "n2"}
    assert set(store.cards()) == {"n1", "n2"}
    # cards() returns a copy — mutating it does not touch the store.
    store.cards()["n3"] = Card()
    assert store.card_ids() == {"n1", "n2"}


# -- delete ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_card(store):
    await store.upsert_card("n1", Card())
    assert await store.delete_card("n1") is True
    assert store.get_card("n1") is None
    # gone from the DB too, not just the cache.
    rows = await store.conn.execute_fetchall("SELECT COUNT(*) AS c FROM fsrs_card")
    assert rows[0]["c"] == 0


@pytest.mark.asyncio
async def test_delete_missing_card_returns_false(store):
    assert await store.delete_card("nope") is False


# -- reconcile ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_prunes_orphans(store):
    await store.upsert_card("n1", Card())
    await store.upsert_card("n2", Card())
    await store.upsert_card("orphan", Card())

    pruned = await store.reconcile({"n1", "n2"})
    assert pruned == ["orphan"]
    assert store.card_ids() == {"n1", "n2"}
    rows = await store.conn.execute_fetchall("SELECT neuron_id FROM fsrs_card")
    assert {r["neuron_id"] for r in rows} == {"n1", "n2"}


@pytest.mark.asyncio
async def test_reconcile_is_idempotent(store):
    await store.upsert_card("n1", Card())
    await store.upsert_card("orphan", Card())
    assert await store.reconcile({"n1"}) == ["orphan"]
    # second sweep finds nothing to do.
    assert await store.reconcile({"n1"}) == []


@pytest.mark.asyncio
async def test_reconcile_on_open(tmp_path):
    path = tmp_path / "reconcile.tutor.db"

    s1 = TutorStore(path)
    await s1.open()
    await s1.upsert_card("n1", Card())
    await s1.upsert_card("orphan", Card())
    await s1.close()

    # Neuron "orphan" was deleted in the substrate between sessions.
    s2 = TutorStore(path)
    pruned = await s2.open(known_neuron_ids={"n1"})
    assert pruned == ["orphan"]
    assert s2.card_ids() == {"n1"}
    await s2.close()
