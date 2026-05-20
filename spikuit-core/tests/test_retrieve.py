"""Tests for Step 4: Graph-weighted retrieve scoring.

Retrieve score = text_sim × (1 + centrality + pressure + keyword_boost).
Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.3) dropped the
FSRS retrievability term — the substrate no longer holds card state.
"""

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Neuron, Plasticity, Source, SynapseType
from spikuit_core.db import Database


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
