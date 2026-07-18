"""Tests for Step 4: Graph-weighted retrieve scoring.

Retrieve score = text_sim × (1 + centrality + pressure + keyword_boost).
Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.3) dropped the
FSRS retrievability term — the substrate no longer holds card state.
"""

from dataclasses import replace

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Neuron, RetrievalSignals, Source, SynapseType


@pytest_asyncio.fixture
async def circuit(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    yield c
    await c.close()


# -------------------------------------------------------------------
# Basic keyword retrieve (existing behavior preserved)
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_returns_matching_neurons(circuit: Circuit):
    """Basic keyword matching still works."""
    n1 = Neuron.create("# Functor\n\nA mapping between categories.")
    n2 = Neuron.create("# Monad\n\nA monoid in the category of endofunctors.")
    n3 = Neuron.create("# Banana\n\nA yellow fruit.")
    for n in [n1, n2, n3]:
        await circuit.add_neuron(n)

    results = await circuit.retrieve("functor")
    ids = [r.id for r in results]
    assert n1.id in ids
    # n2 mentions "endofunctors" which contains "functor"
    assert n2.id in ids
    assert n3.id not in ids


@pytest.mark.asyncio
async def test_retrieve_empty_query_returns_nothing(circuit: Circuit):
    """Empty query should return no results."""
    n1 = Neuron.create("# Something")
    await circuit.add_neuron(n1)
    results = await circuit.retrieve("")
    assert len(results) == 0


# -------------------------------------------------------------------
# Graph centrality boosts well-connected neurons
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_well_connected_ranks_higher(circuit: Circuit):
    """A neuron with more connections should rank higher (all else equal)."""
    # Hub: connected to many
    hub = Neuron.create("# Linear Algebra\n\nThe study of linear maps.")
    spoke1 = Neuron.create("# Matrix\n\nA rectangular array.")
    spoke2 = Neuron.create("# Vector\n\nAn element of a vector space.")
    spoke3 = Neuron.create("# Eigenvalue\n\nA scalar in linear algebra.")
    # Isolated: same content relevance but no connections
    isolated = Neuron.create("# Linear Algebra intro\n\nBasics of linear algebra.")

    for n in [hub, spoke1, spoke2, spoke3, isolated]:
        await circuit.add_neuron(n)

    await circuit.add_synapse(hub.id, spoke1.id, SynapseType.REQUIRES)
    await circuit.add_synapse(hub.id, spoke2.id, SynapseType.REQUIRES)
    await circuit.add_synapse(hub.id, spoke3.id, SynapseType.REQUIRES)

    results = await circuit.retrieve("linear algebra")
    assert len(results) >= 2
    ids = [r.id for r in results]
    # Hub should rank higher than isolated due to centrality
    assert ids.index(hub.id) < ids.index(isolated.id)


# -------------------------------------------------------------------
# Pressure boost surfaces "about to fire" neurons
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pressure_boosts_retrieve_rank(circuit: Circuit):
    """Neurons with high pressure should rank higher."""
    n_pressure = Neuron.create("# Topology\n\nStudy of geometric properties.")
    n_no_pressure = Neuron.create("# Topology basics\n\nIntro to topology.")
    await circuit.add_neuron(n_pressure)
    await circuit.add_neuron(n_no_pressure)

    # Give one neuron high pressure
    circuit._set_pressure(n_pressure.id, 0.7)

    results = await circuit.retrieve("topology")
    assert len(results) >= 2
    assert results[0].id == n_pressure.id


# -------------------------------------------------------------------
# Limit and edge cases
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_respects_limit(circuit: Circuit):
    """Should return at most `limit` results."""
    for i in range(20):
        await circuit.add_neuron(Neuron.create(f"# Topic {i}\n\nAbout topic."))

    results = await circuit.retrieve("topic", limit=5)
    assert len(results) <= 5


@pytest.mark.asyncio
async def test_retrieve_no_matches(circuit: Circuit):
    """Query with no matches returns empty list."""
    await circuit.add_neuron(Neuron.create("# Apple\n\nA fruit."))
    results = await circuit.retrieve("quantum physics")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_retrieve_logs_query(circuit: Circuit):
    """Retrieve should log the query and results for future analysis."""
    n1 = Neuron.create("# Test\n\nA test neuron.")
    await circuit.add_neuron(n1)

    await circuit.retrieve("test")

    # Check that the retrieve was logged
    rows = await circuit._db.conn.execute_fetchall(
        "SELECT * FROM retrieve_log"
    )
    assert len(rows) >= 1
    assert rows[0]["query"] == "test"


# -------------------------------------------------------------------
# Community boost surfaces same-community neurons
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_community_boost_ranks_same_community_higher(circuit: Circuit):
    """Neurons in the dominant community should rank higher after community boost."""
    # Create two clusters about "algebra"
    # Cluster A: connected, will form a community
    a1 = Neuron.create("# Abstract Algebra\n\nStudy of algebraic structures.")
    a2 = Neuron.create("# Group Theory\n\nStudy of algebraic groups.")
    a3 = Neuron.create("# Ring Theory\n\nStudy of algebraic rings.")
    # Cluster B: isolated node about algebra
    b1 = Neuron.create("# Algebra basics\n\nIntroduction to algebra.")

    for n in [a1, a2, a3, b1]:
        await circuit.add_neuron(n)

    # Fully connect cluster A
    await circuit.add_synapse(a1.id, a2.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(a1.id, a3.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(a2.id, a3.id, SynapseType.RELATES_TO)

    # Detect communities so cluster A shares a community
    await circuit.detect_communities()

    # All cluster A should be same community, b1 different
    a_cid = circuit.get_community(a1.id)
    assert a_cid is not None
    assert circuit.get_community(a2.id) == a_cid
    assert circuit.get_community(a3.id) == a_cid

    results = await circuit.retrieve("algebra")
    ids = [r.id for r in results]
    # All cluster A should appear before b1 due to community + centrality boost
    a_indices = [ids.index(n.id) for n in [a1, a2, a3] if n.id in ids]
    b_index = ids.index(b1.id) if b1.id in ids else len(ids)
    assert all(ai < b_index for ai in a_indices)


# -------------------------------------------------------------------
# Filtered retrieval
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_by_domain(circuit: Circuit):
    """Filtering by domain should exclude non-matching neurons."""
    n1 = Neuron.create("# Functor\n\nA mapping.", type="concept", domain="math")
    n2 = Neuron.create("# Functor pattern\n\nDesign pattern.", type="concept", domain="cs")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    results = await circuit.retrieve("functor", filters={"domain": "math"})
    ids = [r.id for r in results]
    assert n1.id in ids
    assert n2.id not in ids


@pytest.mark.asyncio
async def test_filter_by_type(circuit: Circuit):
    """Filtering by type should exclude non-matching neurons."""
    n1 = Neuron.create("# Monad\n\nA monoid.", type="concept", domain="math")
    n2 = Neuron.create("# Monad tutorial\n\nStep by step.", type="procedure", domain="math")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    results = await circuit.retrieve("monad", filters={"type": "concept"})
    ids = [r.id for r in results]
    assert n1.id in ids
    assert n2.id not in ids


@pytest.mark.asyncio
async def test_filter_by_source_filterable(circuit: Circuit):
    """Filtering by source filterable metadata (strict: missing key = excluded)."""
    n1 = Neuron.create("# APPNP\n\nGraph PageRank for GNNs.", type="concept", domain="cs")
    n2 = Neuron.create("# GCN\n\nGraph convolution.", type="concept", domain="cs")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    src = Source(
        url="https://arxiv.org/abs/1810.05997",
        title="APPNP Paper",
        filterable={"year": "2018", "venue": "ICLR"},
    )
    await circuit.add_source(src)
    await circuit.attach_source(n1.id, src.id)
    # n2 has no source → missing key → should be excluded

    results = await circuit.retrieve("graph", filters={"year": "2018"})
    ids = [r.id for r in results]
    assert n1.id in ids
    assert n2.id not in ids


@pytest.mark.asyncio
async def test_filter_wrong_value_excludes(circuit: Circuit):
    """Filter value mismatch should exclude the neuron."""
    n1 = Neuron.create("# APPNP\n\nPageRank.", type="concept", domain="cs")
    await circuit.add_neuron(n1)

    src = Source(url="https://a.com", filterable={"year": "2018"})
    await circuit.add_source(src)
    await circuit.attach_source(n1.id, src.id)

    results = await circuit.retrieve("appnp", filters={"year": "2020"})
    assert len(results) == 0


@pytest.mark.asyncio
async def test_filter_combined_neuron_and_source(circuit: Circuit):
    """Combine neuron-level (domain) and source-level (filterable) filters."""
    n1 = Neuron.create("# Paper A\n\nGNN stuff.", type="concept", domain="cs")
    n2 = Neuron.create("# Paper B\n\nGNN stuff.", type="concept", domain="math")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    src = Source(url="https://a.com", filterable={"year": "2020"})
    await circuit.add_source(src)
    await circuit.attach_source(n1.id, src.id)
    await circuit.attach_source(n2.id, src.id)

    # Both have year=2020, but only n1 has domain=cs
    results = await circuit.retrieve("gnn", filters={"domain": "cs", "year": "2020"})
    ids = [r.id for r in results]
    assert n1.id in ids
    assert n2.id not in ids


@pytest.mark.asyncio
async def test_no_filters_returns_all(circuit: Circuit):
    """No filters should behave as before (return all matches)."""
    n1 = Neuron.create("# Topic A\n\nAbout topic.", domain="math")
    n2 = Neuron.create("# Topic B\n\nAbout topic.", domain="cs")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    results = await circuit.retrieve("topic")
    assert len(results) == 2


# -------------------------------------------------------------------
# Scored retrieval for adapter consumers
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_scored_returns_monotone_scores(circuit: Circuit):
    """Scored results expose the exact ordering used by retrieve()."""
    matching = [
        Neuron.create("# Functor\n\nA mapping between categories."),
        Neuron.create("# Monad\n\nA functor with extra structure."),
    ]
    unrelated = Neuron.create("# Banana\n\nA yellow fruit.")
    for neuron in [*matching, unrelated]:
        await circuit.add_neuron(neuron)

    scored = await circuit.retrieve_scored("functor")

    assert len(scored) == 2
    assert all(isinstance(neuron, Neuron) for neuron, _score in scored)
    assert all(isinstance(score, float) and score > 0.0 for _neuron, score in scored)
    scores = [score for _neuron, score in scored]
    assert scores == sorted(scores, reverse=True)
    assert unrelated.id not in {neuron.id for neuron, _score in scored}


@pytest.mark.asyncio
async def test_retrieve_and_retrieve_scored_agree(circuit: Circuit):
    """The compatibility API must preserve the scored API's rank order."""
    for index in range(5):
        await circuit.add_neuron(
            Neuron.create(f"# Topic {index}\n\nDescription about topic {index}.")
        )

    plain = await circuit.retrieve("topic")
    scored = await circuit.retrieve_scored("topic")

    assert [neuron.id for neuron in plain] == [
        neuron.id for neuron, _score in scored
    ]


@pytest.mark.asyncio
async def test_retrieve_scored_empty_query(circuit: Circuit):
    assert await circuit.retrieve_scored("") == []
    assert await circuit.retrieve_scored("   ") == []


@pytest.mark.parametrize(
    "name",
    ("keyword", "semantic", "centrality", "pressure", "feedback", "community"),
)
def test_retrieval_signals_require_strict_booleans(name: str):
    with pytest.raises(TypeError, match=rf"{name} must be a bool"):
        RetrievalSignals(**{name: 1})


@pytest.mark.asyncio
async def test_candidate_and_local_rerank_signals_can_be_ablated(circuit: Circuit):
    boosted = Neuron.create("# Topic\n\nShared retrieval text.")
    plain = Neuron.create("# Topic\n\nShared retrieval text.")
    await circuit.add_neuron(boosted)
    await circuit.add_neuron(plain)
    circuit._set_pressure(boosted.id, 0.7)
    circuit.set_retrieval_boost(boosted.id, 0.5)

    text_only = RetrievalSignals(
        semantic=False, centrality=False, pressure=False,
        feedback=False, community=False,
    )
    no_candidates = replace(text_only, keyword=False)

    def scores(result):
        return {neuron.id: score for neuron, score in result}

    base = scores(await circuit.retrieve_scored("topic", signals=text_only))
    pressure = scores(
        await circuit.retrieve_scored(
            "topic", signals=replace(text_only, pressure=True),
        )
    )
    feedback = scores(
        await circuit.retrieve_scored(
            "topic", signals=replace(text_only, feedback=True),
        )
    )

    assert base[boosted.id] == base[plain.id] == 1.0
    assert pressure[boosted.id] == pytest.approx(1.7)
    assert pressure[plain.id] == 1.0
    assert feedback[boosted.id] == pytest.approx(1.5)
    assert feedback[plain.id] == 1.0
    assert await circuit.retrieve_scored("topic") == await circuit.retrieve_scored(
        "topic", signals=RetrievalSignals(),
    )
    assert await circuit.retrieve("topic", signals=no_candidates) == []


@pytest.mark.asyncio
async def test_graph_rerank_signals_can_be_ablated(circuit: Circuit):
    hub = Neuron.create("# Algebra\n\nShared retrieval text.")
    spoke_a = Neuron.create("# Algebra\n\nShared retrieval text.")
    spoke_b = Neuron.create("# Algebra\n\nShared retrieval text.")
    isolated = Neuron.create("# Algebra\n\nShared retrieval text.")
    for neuron in (hub, spoke_a, spoke_b, isolated):
        await circuit.add_neuron(neuron)
    await circuit.add_synapse(hub.id, spoke_a.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(hub.id, spoke_b.id, SynapseType.RELATES_TO)
    await circuit.detect_communities()

    text_only = RetrievalSignals(
        semantic=False, centrality=False, pressure=False,
        feedback=False, community=False,
    )

    def scores(result):
        return {neuron.id: score for neuron, score in result}

    base = scores(await circuit.retrieve_scored("algebra", signals=text_only))
    centrality = scores(
        await circuit.retrieve_scored(
            "algebra", signals=replace(text_only, centrality=True),
        )
    )
    community = scores(
        await circuit.retrieve_scored(
            "algebra", signals=replace(text_only, community=True),
        )
    )

    assert base[hub.id] == base[isolated.id] == 1.0
    assert centrality[hub.id] > centrality[isolated.id]
    assert community[hub.id] > community[isolated.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
async def test_retrieval_boost_rejects_non_finite_values(
    circuit: Circuit, invalid: float
):
    neuron = Neuron.create("# Finite scoring\n\nScores must remain interoperable.")
    await circuit.add_neuron(neuron)

    with pytest.raises(ValueError, match="retrieval boost must be finite"):
        circuit.set_retrieval_boost(neuron.id, invalid)


@pytest.mark.asyncio
async def test_loading_non_finite_retrieval_boost_fails_explicitly(circuit: Circuit):
    neuron = Neuron.create("# Persisted scoring\n\nStored boosts need validation.")
    await circuit.add_neuron(neuron)
    await circuit._db.set_retrieval_boost(neuron.id, float("inf"))

    with pytest.raises(ValueError, match="retrieval boost must be finite"):
        await circuit._load_retrieval_boosts()
