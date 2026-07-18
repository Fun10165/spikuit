"""Run the amkb conformance suite against SpikuitStore.

Re-imports test functions from `amkb.conformance.*` so they are
collected under spikuit-agents/tests/, which makes our local conftest's
`store` fixture (a SpikuitStore) the one in scope rather than
amkb-sdk's default DictStore.

Tests that exercise functionality the v0.7.1 adapter doesn't yet
support (e.g. ``KIND_CATEGORY``, ``revert``, multi-tx concurrency,
non-Spikuit AMKB rels like ``derived_from`` / ``attested_by``, or
free-form attribute filtering) are overridden with a ``pytest.skip``
stub at the bottom of this module so they appear as skipped rather
than failing. Capability-gated tests (L3 ``supports_*`` flags) skip
themselves automatically because the Store does not advertise the
flags.
"""

import pytest
from amkb.types import KIND_CONCEPT, LAYER_CONCEPT

from amkb.conformance.test_l1_core import *  # noqa: F401,F403
from amkb.conformance.test_l2_lineage import *  # noqa: F401,F403
from amkb.conformance.test_l3_transactional import *  # noqa: F401,F403
from amkb.conformance.test_l4a_structural import *  # noqa: F401,F403
from amkb.conformance.test_l4b_intent import *  # noqa: F401,F403


def test_retrieve_exposes_monotone_scores(store, actor) -> None:
    with store.begin(tag="scored-retrieval", actor=actor) as tx:
        tx.create(
            kind=KIND_CONCEPT,
            layer=LAYER_CONCEPT,
            content="# Functor\n\nA mapping between categories.",
        )
        tx.create(
            kind=KIND_CONCEPT,
            layer=LAYER_CONCEPT,
            content="# Monad\n\nA functor with extra structure.",
        )
        tx.commit()

    hits = store.retrieve("functor", k=10)

    assert len(hits) == 2
    scores = [hit.score for hit in hits]
    assert all(score is not None and score > 0.0 for score in scores)
    assert scores == sorted(scores, reverse=True)


def test_history_applies_time_actor_tag_and_limit_filters(store, actor) -> None:
    committed = []
    for index, tag in enumerate(("first", "middle", "last")):
        with store.begin(tag=tag, actor=actor) as tx:
            tx.create(
                kind=KIND_CONCEPT,
                layer=LAYER_CONCEPT,
                content=f"# History {index}\n\nChangeset {index}.",
            )
            result = tx.commit()
        committed.append(result)

    refs = [changeset.ref for changeset in committed]
    middle = committed[1]

    assert store.history() == refs
    assert store.history(since=middle.committed_at) == refs[1:]
    assert store.history(until=middle.committed_at) == refs[:2]
    assert store.history(actor=middle.actor) == refs
    assert store.history(tag="middle") == [middle.ref]
    assert store.history(limit=2) == refs[:2]


# -- v0.7.1 known-skips -------------------------------------------------------

# L2 ---------------------------------------------------------------------

@pytest.mark.skip(
    reason="KIND_CATEGORY not yet supported by Spikuit adapter (v0.7.x roadmap)",
)
def test_L2_merge_02_kind_mismatch_rejected(store, actor) -> None:  # noqa: F811
    pass


# L3 ---------------------------------------------------------------------
# Spikuit's Circuit forbids nested transactions (TransactionNestingError)
# and we have no revert() yet — the whole L3 block is parked until v0.8+.

@pytest.mark.skip(
    reason="Spikuit Circuit forbids concurrent transactions in v0.7.x "
    "(TransactionNestingError); MVCC is on the v0.8+ roadmap",
)
def test_L3_concurrent_02_disjoint_both_commit(store, actor) -> None:  # noqa: F811
    pass


@pytest.mark.skip(reason="Store.revert() not implemented in v0.7.1 adapter")
def test_L3_revert_01_of_simple_creation(store, actor) -> None:  # noqa: F811
    pass


@pytest.mark.skip(reason="Store.revert() not implemented in v0.7.1 adapter")
def test_L3_revert_04_unknown_tag(store, actor) -> None:  # noqa: F811
    pass


# L4a --------------------------------------------------------------------
# `neighbors_04` and `walk_02` exercise rels (`derived_from`, `attested_by`)
# that have no SynapseType counterpart in Spikuit — link() rejects them
# with E_INVALID_REL before the test can even set up its fixture graph.

@pytest.mark.skip(
    reason="REL_DERIVED_FROM has no SynapseType in Spikuit (v0.7.x)",
)
def test_L4a_neighbors_04_relation_filter(store, actor) -> None:  # noqa: F811
    pass


@pytest.mark.skip(
    reason="REL_ATTESTED_BY has no SynapseType in Spikuit (v0.7.x)",
)
def test_L4a_walk_02_source_nodes_excluded(store, actor) -> None:  # noqa: F811
    pass


# L4b --------------------------------------------------------------------
# Spikuit only stores type/domain/source as queryable attrs, not free-form
# user attrs, so filter-by-bucket isn't reachable in the v0.7.1 adapter.

@pytest.mark.skip(
    reason="Free-form attr filtering not supported by Spikuit adapter "
    "(v0.7.x): only type/domain/source are queryable attrs",
)
def test_L4b_retrieve_03_limit_and_filter(store, actor) -> None:  # noqa: F811
    pass
