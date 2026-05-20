"""Tests for Circuit — Neuron/Synapse CRUD and graph operations."""

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Grade, Neuron, Source, Spike, SynapseConfidence, SynapseType


@pytest_asyncio.fixture
async def circuit(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    yield c
    await c.close()


SAMPLE_CONTENT = """\
---
type: vocab
domain: language
source: test
---

# functor

圏の間の写像。
"""


# -- Neuron CRUD -----------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_get_neuron(circuit):
    neuron = Neuron.create(SAMPLE_CONTENT)
    await circuit.add_neuron(neuron)

    got = await circuit.get_neuron(neuron.id)
    assert got is not None
    assert got.id == neuron.id
    assert got.type == "vocab"
    assert got.domain == "language"
    assert got.source == "test"
    assert "functor" in got.content


@pytest.mark.asyncio
async def test_list_neurons_by_type(circuit):
    n1 = Neuron.create("---\ntype: vocab\n---\n# a")
    n2 = Neuron.create("---\ntype: concept\n---\n# b")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    vocabs = await circuit.list_neurons(type="vocab")
    assert len(vocabs) == 1
    assert vocabs[0].id == n1.id


@pytest.mark.asyncio
async def test_update_neuron(circuit):
    neuron = Neuron.create(SAMPLE_CONTENT)
    await circuit.add_neuron(neuron)

    neuron.content = neuron.content.replace("functor", "monad")
    neuron.type = "concept"
    await circuit.update_neuron(neuron)

    got = await circuit.get_neuron(neuron.id)
    assert "monad" in got.content
    assert got.type == "concept"


@pytest.mark.asyncio
async def test_remove_neuron(circuit):
    neuron = Neuron.create(SAMPLE_CONTENT)
    await circuit.add_neuron(neuron)
    await circuit.remove_neuron(neuron.id)

    assert await circuit.get_neuron(neuron.id) is None
    assert circuit.neuron_count == 0


# -- Synapse CRUD ----------------------------------------------------------


@pytest.mark.asyncio
async def test_add_directed_synapse(circuit):
    n1 = Neuron.create("---\ntype: vocab\n---\n# A")
    n2 = Neuron.create("---\ntype: vocab\n---\n# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    created = await circuit.add_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    assert len(created) == 1
    assert circuit.synapse_count == 1

    # Direction: n1 -> n2
    assert n2.id in circuit.neighbors(n1.id)
    assert n1.id not in circuit.neighbors(n2.id)


@pytest.mark.asyncio
async def test_add_bidirectional_synapse(circuit):
    n1 = Neuron.create("---\ntype: vocab\n---\n# A")
    n2 = Neuron.create("---\ntype: vocab\n---\n# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    created = await circuit.add_synapse(n1.id, n2.id, SynapseType.CONTRASTS)
    assert len(created) == 2
    assert circuit.synapse_count == 2

    # Both directions
    assert n2.id in circuit.neighbors(n1.id)
    assert n1.id in circuit.neighbors(n2.id)


@pytest.mark.asyncio
async def test_remove_bidirectional_synapse(circuit):
    n1 = Neuron.create("---\ntype: vocab\n---\n# A")
    n2 = Neuron.create("---\ntype: vocab\n---\n# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    await circuit.add_synapse(n1.id, n2.id, SynapseType.CONTRASTS)
    await circuit.remove_synapse(n1.id, n2.id, SynapseType.CONTRASTS)
    assert circuit.synapse_count == 0


@pytest.mark.asyncio
async def test_synapse_requires_existing_neurons(circuit):
    with pytest.raises(ValueError, match="Both neurons must exist"):
        await circuit.add_synapse("fake-1", "fake-2", SynapseType.RELATES_TO)


# -- Synapse confidence -----------------------------------------------------


@pytest.mark.asyncio
async def test_synapse_default_confidence_is_extracted(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    created = await circuit.add_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    assert created[0].confidence == SynapseConfidence.EXTRACTED
    assert created[0].confidence_score == 1.0

    # Verify persisted
    s = await circuit.get_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    assert s.confidence == SynapseConfidence.EXTRACTED
    assert s.confidence_score == 1.0


@pytest.mark.asyncio
async def test_synapse_inferred_confidence(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    created = await circuit.add_synapse(
        n1.id, n2.id, SynapseType.RELATES_TO,
        confidence=SynapseConfidence.INFERRED,
        confidence_score=0.75,
    )
    # Bidirectional: both should have INFERRED
    assert len(created) == 2
    for s in created:
        assert s.confidence == SynapseConfidence.INFERRED
        assert s.confidence_score == 0.75

    # Verify round-trip from DB
    s = await circuit.get_synapse(n1.id, n2.id, SynapseType.RELATES_TO)
    assert s.confidence == SynapseConfidence.INFERRED
    assert s.confidence_score == 0.75


@pytest.mark.asyncio
async def test_synapse_confidence_update_persists(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    await circuit.add_synapse(
        n1.id, n2.id, SynapseType.REQUIRES,
        confidence=SynapseConfidence.INFERRED,
        confidence_score=0.5,
    )

    # Update confidence via set_synapse_weight (which uses update_synapse)
    s = await circuit.get_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    s.confidence = SynapseConfidence.EXTRACTED
    s.confidence_score = 1.0
    await circuit._db.update_synapse(s)

    reloaded = await circuit.get_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    assert reloaded.confidence == SynapseConfidence.EXTRACTED
    assert reloaded.confidence_score == 1.0


@pytest.mark.asyncio
async def test_synapse_ambiguous_confidence(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    created = await circuit.add_synapse(
        n1.id, n2.id, SynapseType.CONTRASTS,
        confidence=SynapseConfidence.AMBIGUOUS,
        confidence_score=0.3,
    )
    assert created[0].confidence == SynapseConfidence.AMBIGUOUS

    s = await circuit.get_synapse(n1.id, n2.id, SynapseType.CONTRASTS)
    assert s.confidence == SynapseConfidence.AMBIGUOUS
    assert s.confidence_score == 0.3


@pytest.mark.asyncio
async def test_list_synapses_includes_confidence(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    await circuit.add_synapse(
        n1.id, n2.id, SynapseType.REQUIRES,
        confidence=SynapseConfidence.INFERRED,
        confidence_score=0.6,
    )

    synapses = await circuit.list_synapses(neuron_id=n1.id)
    assert len(synapses) == 1
    assert synapses[0].confidence == SynapseConfidence.INFERRED
    assert synapses[0].confidence_score == 0.6


# -- Spike (fire) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_records_spike(circuit):
    neuron = Neuron.create(SAMPLE_CONTENT)
    await circuit.add_neuron(neuron)

    spike = Spike(neuron_id=neuron.id, grade=Grade.FIRE)
    await circuit.fire(spike)

    spikes = await circuit._db.get_spikes_for(neuron.id)
    assert len(spikes) == 1
    assert spikes[0].grade == Grade.FIRE


# -- Ensemble ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensemble(circuit):
    # Create a chain: A -> B -> C
    na = Neuron.create("# A")
    nb = Neuron.create("# B")
    nc = Neuron.create("# C")
    nd = Neuron.create("# D (isolated)")
    for n in [na, nb, nc, nd]:
        await circuit.add_neuron(n)

    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES)
    await circuit.add_synapse(nb.id, nc.id, SynapseType.REQUIRES)

    # 1-hop from A: only B
    e1 = circuit.ensemble(na.id, hops=1)
    assert nb.id in e1
    assert nc.id not in e1

    # 2-hop from A: B and C
    e2 = circuit.ensemble(na.id, hops=2)
    assert nb.id in e2
    assert nc.id in e2
    assert nd.id not in e2  # isolated


# -- Retrieve ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_keyword(circuit):
    n1 = Neuron.create("# msgspec\n\nC拡張の高速シリアライザ")
    n2 = Neuron.create("# Pydantic\n\nバリデーション重視のライブラリ")
    n3 = Neuron.create("# functor\n\n圏の間の写像")
    for n in [n1, n2, n3]:
        await circuit.add_neuron(n)

    results = await circuit.retrieve("msgspec")
    assert len(results) == 1
    assert results[0].id == n1.id


@pytest.mark.asyncio
async def test_retrieve_logs(circuit):
    n1 = Neuron.create("# test neuron\n\ncontent here")
    await circuit.add_neuron(n1)

    await circuit.retrieve("test")

    # Check log was written
    rows = await circuit._db.conn.execute_fetchall("SELECT * FROM retrieve_log")
    assert len(rows) == 1
    assert rows[0]["query"] == "test"


# -- Stats ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)
    await circuit.add_synapse(n1.id, n2.id, SynapseType.RELATES_TO)

    s = await circuit.stats()
    assert s["neurons"] == 2
    assert s["synapses"] == 2  # bidirectional


# -- Graph reload -----------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_reload(tmp_path):
    """Graph should be fully reconstructed from DB on connect."""
    db_path = tmp_path / "reload.db"

    # First session: create data
    c1 = Circuit(db_path=db_path)
    await c1.connect()
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await c1.add_neuron(n1)
    await c1.add_neuron(n2)
    await c1.add_synapse(n1.id, n2.id, SynapseType.EXTENDS)
    await c1.close()

    # Second session: reload
    c2 = Circuit(db_path=db_path)
    await c2.connect()
    assert c2.neuron_count == 2
    assert c2.synapse_count == 1
    assert n2.id in c2.neighbors(n1.id)
    await c2.close()


# -- Source operations on Circuit -------------------------------------------


@pytest.mark.asyncio
async def test_circuit_add_and_get_source(circuit):
    s = Source(url="https://example.com", title="Example")
    await circuit.add_source(s)

    got = await circuit.get_source(s.id)
    assert got is not None
    assert got.url == "https://example.com"


@pytest.mark.asyncio
async def test_circuit_find_source_by_url(circuit):
    s = Source(url="https://unique.com", title="Unique")
    await circuit.add_source(s)

    found = await circuit.find_source_by_url("https://unique.com")
    assert found is not None
    assert found.id == s.id

    assert await circuit.find_source_by_url("https://nope.com") is None


@pytest.mark.asyncio
async def test_circuit_attach_and_get_sources(circuit):
    n = Neuron.create("# Test")
    await circuit.add_neuron(n)
    s1 = Source(url="https://a.com")
    s2 = Source(url="https://b.com")
    await circuit.add_source(s1)
    await circuit.add_source(s2)

    await circuit.attach_source(n.id, s1.id)
    await circuit.attach_source(n.id, s2.id)

    sources = await circuit.get_sources_for_neuron(n.id)
    assert len(sources) == 2
    assert {s.url for s in sources} == {"https://a.com", "https://b.com"}


@pytest.mark.asyncio
async def test_circuit_detach_source(circuit):
    n = Neuron.create("# Test")
    await circuit.add_neuron(n)
    s = Source(url="https://a.com")
    await circuit.add_source(s)
    await circuit.attach_source(n.id, s.id)

    await circuit.detach_source(n.id, s.id)
    assert await circuit.get_sources_for_neuron(n.id) == []


@pytest.mark.asyncio
async def test_circuit_source_survives_reload(tmp_path):
    """Source attachments should persist across Circuit reconnections."""
    db_path = tmp_path / "reload.db"

    c1 = Circuit(db_path=db_path)
    await c1.connect()
    n = Neuron.create("# Test")
    await c1.add_neuron(n)
    s = Source(url="https://persist.com", title="Persist")
    await c1.add_source(s)
    await c1.attach_source(n.id, s.id)
    await c1.close()

    c2 = Circuit(db_path=db_path)
    await c2.connect()
    sources = await c2.get_sources_for_neuron(n.id)
    assert len(sources) == 1
    assert sources[0].url == "https://persist.com"
    await c2.close()


# -- list_synapses -----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_synapses_all(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    n3 = Neuron.create("# C")
    for n in [n1, n2, n3]:
        await circuit.add_neuron(n)

    await circuit.add_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    await circuit.add_synapse(n2.id, n3.id, SynapseType.EXTENDS)

    synapses = await circuit.list_synapses()
    assert len(synapses) == 2


@pytest.mark.asyncio
async def test_list_synapses_by_neuron(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    n3 = Neuron.create("# C")
    for n in [n1, n2, n3]:
        await circuit.add_neuron(n)

    await circuit.add_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    await circuit.add_synapse(n2.id, n3.id, SynapseType.EXTENDS)

    # n2 is involved in both
    synapses = await circuit.list_synapses(neuron_id=n2.id)
    assert len(synapses) == 2

    # n1 is only in one
    synapses = await circuit.list_synapses(neuron_id=n1.id)
    assert len(synapses) == 1


@pytest.mark.asyncio
async def test_list_synapses_by_type(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    n3 = Neuron.create("# C")
    for n in [n1, n2, n3]:
        await circuit.add_neuron(n)

    await circuit.add_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    await circuit.add_synapse(n2.id, n3.id, SynapseType.RELATES_TO)  # bidirectional → 2 rows

    synapses = await circuit.list_synapses(type=SynapseType.REQUIRES)
    assert len(synapses) == 1
    assert synapses[0].pre == n1.id


# -- set_synapse_weight ------------------------------------------------------


@pytest.mark.asyncio
async def test_set_synapse_weight(circuit):
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    await circuit.add_synapse(n1.id, n2.id, SynapseType.REQUIRES, weight=0.5)

    updated = await circuit.set_synapse_weight(n1.id, n2.id, SynapseType.REQUIRES, 0.9)
    assert updated.weight == 0.9

    # Verify persisted
    got = await circuit.get_synapse(n1.id, n2.id, SynapseType.REQUIRES)
    assert got.weight == 0.9

    # Verify in-memory graph
    assert circuit._graph[n1.id][n2.id]["weight"] == 0.9


@pytest.mark.asyncio
async def test_set_synapse_weight_not_found(circuit):
    with pytest.raises(ValueError, match="Synapse not found"):
        await circuit.set_synapse_weight("x", "y", SynapseType.REQUIRES, 0.5)


# -- merge_neurons -----------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_neurons_basic(circuit):
    n1 = Neuron.create("# Target\n\nTarget content.")
    n2 = Neuron.create("# Source\n\nSource content.")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    result = await circuit.merge_neurons([n2.id], into_id=n1.id)

    assert result["merged"] == 1
    assert result["into"] == n1.id

    # Source neuron deleted
    assert await circuit.get_neuron(n2.id) is None

    # Target neuron has merged content
    target = await circuit.get_neuron(n1.id)
    assert "Target content." in target.content
    assert "Source content." in target.content


@pytest.mark.asyncio
async def test_merge_neurons_redirects_synapses(circuit):
    na = Neuron.create("# A")
    nb = Neuron.create("# B (target)")
    nc = Neuron.create("# C")
    for n in [na, nb, nc]:
        await circuit.add_neuron(n)

    # A -> C (requires), B is the target
    await circuit.add_synapse(na.id, nc.id, SynapseType.REQUIRES)

    result = await circuit.merge_neurons([na.id], into_id=nb.id)

    # A is deleted
    assert await circuit.get_neuron(na.id) is None

    # B now has a synapse to C (redirected from A)
    assert result["synapses_redirected"] == 1
    syn = await circuit.get_synapse(nb.id, nc.id, SynapseType.REQUIRES)
    assert syn is not None


@pytest.mark.asyncio
async def test_merge_neurons_transfers_sources(circuit):
    n1 = Neuron.create("# Target")
    n2 = Neuron.create("# Source")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    src = Source(url="https://example.com", title="Example")
    await circuit.add_source(src)
    await circuit.attach_source(n2.id, src.id)

    result = await circuit.merge_neurons([n2.id], into_id=n1.id)

    assert result["sources_transferred"] == 1
    target_sources = await circuit.get_sources_for_neuron(n1.id)
    assert len(target_sources) == 1
    assert target_sources[0].url == "https://example.com"


@pytest.mark.asyncio
async def test_merge_neurons_skips_self_loops(circuit):
    n1 = Neuron.create("# Target")
    n2 = Neuron.create("# Source")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)

    # Synapse between the two neurons being merged
    await circuit.add_synapse(n2.id, n1.id, SynapseType.REQUIRES)

    result = await circuit.merge_neurons([n2.id], into_id=n1.id)

    # Should not create self-loop
    assert result["synapses_redirected"] == 0
    syn = await circuit.get_synapse(n1.id, n1.id, SynapseType.REQUIRES)
    assert syn is None


@pytest.mark.asyncio
async def test_merge_neurons_into_id_in_sources_raises(circuit):
    n1 = Neuron.create("# A")
    await circuit.add_neuron(n1)

    with pytest.raises(ValueError, match="into_id must not be in source_ids"):
        await circuit.merge_neurons([n1.id], into_id=n1.id)


# -- _meta domain -----------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_meta_neuron_creates(circuit):
    n = await circuit.upsert_meta_neuron("_meta:overview", "# Brain overview")
    assert n.id == "_meta:overview"
    assert n.domain == "_meta"
    assert n.type == "meta"

    # Verify persisted
    loaded = await circuit.get_neuron("_meta:overview")
    assert loaded is not None
    assert loaded.content == "# Brain overview"


@pytest.mark.asyncio
async def test_upsert_meta_neuron_replaces(circuit):
    await circuit.upsert_meta_neuron("_meta:overview", "# V1")
    await circuit.upsert_meta_neuron("_meta:overview", "# V2")

    loaded = await circuit.get_neuron("_meta:overview")
    assert loaded.content == "# V2"
    # Should still be only 1 neuron
    assert circuit.neuron_count == 1


@pytest.mark.asyncio
async def test_meta_neurons_cannot_be_fired(circuit):
    await circuit.upsert_meta_neuron("_meta:overview", "# Overview")

    with pytest.raises(ValueError, match="auto-generated"):
        await circuit.fire(Spike(neuron_id="_meta:overview", grade=Grade.FIRE))


@pytest.mark.asyncio
async def test_clear_meta_neurons(circuit):
    await circuit.upsert_meta_neuron("_meta:overview", "# Overview")
    await circuit.upsert_meta_neuron("_meta:cutoff", "# Cutoff")
    n = Neuron.create("# Regular", domain="math")
    await circuit.add_neuron(n)

    removed = await circuit.clear_meta_neurons()
    assert removed == 2
    assert circuit.neuron_count == 1
    assert await circuit.get_neuron("_meta:overview") is None
    assert await circuit.get_neuron(n.id) is not None


# -- generate_manual --------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_manual_basic(circuit):
    n1 = Neuron.create("# Functor\n\nA mapping between categories.", domain="math", type="concept")
    n2 = Neuron.create("# Monad\n\nA monoid in the category of endofunctors.", domain="math", type="concept")
    n3 = Neuron.create("# Bonjour\n\nHello in French.", domain="french", type="vocab")
    for n in [n1, n2, n3]:
        await circuit.add_neuron(n)

    result = await circuit.generate_manual()
    assert result["neuron_count"] == 3
    assert len(result["domains"]) == 2

    math_domain = next(d for d in result["domains"] if d["name"] == "math")
    assert math_domain["neuron_count"] == 2
    assert len(math_domain["topics"]) > 0

    french_domain = next(d for d in result["domains"] if d["name"] == "french")
    assert french_domain["neuron_count"] == 1
    assert french_domain["limited_coverage"] is True


@pytest.mark.asyncio
async def test_generate_manual_writes_meta(circuit):
    n1 = Neuron.create("# Functor", domain="math", type="concept")
    await circuit.add_neuron(n1)

    await circuit.generate_manual(write_meta=True)

    overview = await circuit.get_neuron("_meta:overview")
    assert overview is not None
    assert "1 neurons" in overview.content

    cutoff = await circuit.get_neuron("_meta:cutoff")
    assert cutoff is not None

    examples = await circuit.get_neuron("_meta:examples")
    assert examples is not None

    coverage = await circuit.get_neuron("_meta:coverage:math")
    assert coverage is not None
    assert "math" in coverage.content.lower()


@pytest.mark.asyncio
async def test_generate_manual_excludes_meta_from_count(circuit):
    n1 = Neuron.create("# A", domain="math")
    await circuit.add_neuron(n1)
    await circuit.upsert_meta_neuron("_meta:overview", "# old")

    result = await circuit.generate_manual()
    assert result["neuron_count"] == 1  # _meta neuron not counted


@pytest.mark.asyncio
async def test_generate_manual_empty_brain(circuit):
    result = await circuit.generate_manual()
    assert result["neuron_count"] == 0
    assert result["domains"] == []
    assert result["cutoff"] is None
    assert result["sources"] == []


# -- Community summaries ----------------------------------------------------


@pytest.mark.asyncio
async def test_generate_community_summaries_basic(circuit):
    # Create two clusters: A-B (math) and C-D (french)
    na = Neuron.create("# Functor\n\nMapping.", domain="math", type="concept")
    nb = Neuron.create("# Monad\n\nEndofunctor.", domain="math", type="concept")
    nc = Neuron.create("# Bonjour\n\nHello.", domain="french", type="vocab")
    nd = Neuron.create("# Merci\n\nThanks.", domain="french", type="vocab")
    for n in [na, nb, nc, nd]:
        await circuit.add_neuron(n)
    await circuit.add_synapse(na.id, nb.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(nc.id, nd.id, SynapseType.RELATES_TO)

    await circuit.detect_communities()
    results = await circuit.generate_community_summaries()

    assert len(results) == 2
    for r in results:
        assert r["member_count"] == 2
        assert r["id"].startswith("cs-")

    # Summary neurons exist
    summary = await circuit.get_neuron(results[0]["id"])
    assert summary is not None
    assert summary.type == "community_summary"
    assert "Community" in summary.content


@pytest.mark.asyncio
async def test_community_summaries_replace_on_rerun(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    for n in [na, nb]:
        await circuit.add_neuron(n)
    await circuit.add_synapse(na.id, nb.id, SynapseType.RELATES_TO)

    await circuit.detect_communities()
    r1 = await circuit.generate_community_summaries()
    assert len(r1) == 1

    # Re-run: should replace, not duplicate
    r2 = await circuit.generate_community_summaries()
    assert len(r2) == 1

    # Only 1 summary neuron total (old removed)
    summaries = [nid for nid in circuit._graph.nodes
                 if circuit._graph.nodes[nid].get("type") == "community_summary"]
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_community_summaries_linked_via_summarizes(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    for n in [na, nb]:
        await circuit.add_neuron(n)
    await circuit.add_synapse(na.id, nb.id, SynapseType.RELATES_TO)

    await circuit.detect_communities()
    results = await circuit.generate_community_summaries()

    summary_id = results[0]["id"]
    synapses = await circuit.list_synapses(neuron_id=summary_id)
    summarizes = [s for s in synapses if s.type == SynapseType.SUMMARIZES]
    assert len(summarizes) == 2  # linked to both members


@pytest.mark.asyncio
async def test_community_summaries_skip_singletons(circuit):
    na = Neuron.create("# A", domain="math")
    await circuit.add_neuron(na)

    await circuit.detect_communities()
    results = await circuit.generate_community_summaries()
    assert len(results) == 0  # single node, no summary


@pytest.mark.asyncio
async def test_community_summaries_empty_graph(circuit):
    results = await circuit.generate_community_summaries()
    assert results == []


# -- Consolidation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate_plan_structure(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    await circuit.add_neuron(na)
    await circuit.add_neuron(nb)
    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES)

    plan = await circuit.consolidate()
    assert "state_hash" in plan
    assert "sws" in plan
    assert "shy" in plan
    assert "rem" in plan
    assert "triage" in plan
    assert "summary" in plan
    assert plan["summary"]["weight_decays"] == 1  # 1 synapse decayed


@pytest.mark.asyncio
async def test_consolidate_shy_decay(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    await circuit.add_neuron(na)
    await circuit.add_neuron(nb)
    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES, weight=0.5)

    plan = await circuit.consolidate(decay_factor=0.5)
    # 0.5 * 0.5 = 0.25 > default floor (0.05), so decayed not pruned
    assert len(plan["shy"]["decayed"]) == 1
    assert plan["shy"]["decayed"][0]["new_weight"] == 0.25
    assert len(plan["shy"]["prunable"]) == 0


@pytest.mark.asyncio
async def test_consolidate_shy_prune(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    await circuit.add_neuron(na)
    await circuit.add_neuron(nb)
    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES, weight=0.06)

    plan = await circuit.consolidate(decay_factor=0.5)
    # 0.06 * 0.5 = 0.03 < floor (0.05), so prunable
    assert len(plan["shy"]["prunable"]) == 1
    assert len(plan["shy"]["decayed"]) == 0


@pytest.mark.asyncio
async def test_consolidate_apply_validates_hash(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    await circuit.add_neuron(na)
    await circuit.add_neuron(nb)
    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES)

    plan = await circuit.consolidate()

    # Modify graph to invalidate hash
    nc = Neuron.create("# C", domain="math")
    await circuit.add_neuron(nc)

    with pytest.raises(ValueError, match="Brain state has changed"):
        await circuit.apply_consolidation(plan)


@pytest.mark.asyncio
async def test_consolidate_apply_decays_weights(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    await circuit.add_neuron(na)
    await circuit.add_neuron(nb)
    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES, weight=0.5)

    plan = await circuit.consolidate(decay_factor=0.8)
    result = await circuit.apply_consolidation(plan)
    assert result["weights_decayed"] == 1

    s = await circuit.get_synapse(na.id, nb.id, SynapseType.REQUIRES)
    assert abs(s.weight - 0.4) < 0.01


@pytest.mark.asyncio
async def test_consolidate_apply_prunes_synapse(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    await circuit.add_neuron(na)
    await circuit.add_neuron(nb)
    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES, weight=0.06)

    plan = await circuit.consolidate(decay_factor=0.5)
    result = await circuit.apply_consolidation(plan)
    assert result["synapses_pruned"] == 1
    assert circuit.synapse_count == 0


@pytest.mark.asyncio
async def test_consolidate_domain_filter(circuit):
    na = Neuron.create("# A", domain="math")
    nb = Neuron.create("# B", domain="math")
    nc = Neuron.create("# C", domain="french")
    nd = Neuron.create("# D", domain="french")
    for n in [na, nb, nc, nd]:
        await circuit.add_neuron(n)
    await circuit.add_synapse(na.id, nb.id, SynapseType.REQUIRES, weight=0.5)
    await circuit.add_synapse(nc.id, nd.id, SynapseType.REQUIRES, weight=0.5)

    plan = await circuit.consolidate(domain="math")
    assert plan["domain"] == "math"
    # Only math synapse should be in decay list
    assert len(plan["shy"]["decayed"]) == 1
    assert plan["shy"]["decayed"][0]["pre"] == na.id


@pytest.mark.asyncio
async def test_consolidate_empty_brain(circuit):
    plan = await circuit.consolidate()
    assert plan["summary"]["weight_decays"] == 0
    assert plan["summary"]["prunable_synapses"] == 0
    assert plan["summary"]["forget_candidates"] == 0


# -- Diagnose ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnose_orphans(circuit):
    """Neurons with no synapses are reported as orphans."""
    n1 = Neuron.create("# Orphan", domain="test")
    n2 = Neuron.create("# Connected A", domain="test")
    n3 = Neuron.create("# Connected B", domain="test")
    for n in (n1, n2, n3):
        await circuit.add_neuron(n)
    await circuit.add_synapse(n2.id, n3.id, SynapseType.RELATES_TO)

    result = await circuit.diagnose()
    assert n1.id in result["orphans"]
    assert n2.id not in result["orphans"]
    assert n3.id not in result["orphans"]


@pytest.mark.asyncio
async def test_diagnose_weak_synapses(circuit):
    """Synapses below threshold are flagged."""
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)
    await circuit.add_synapse(n1.id, n2.id, SynapseType.REQUIRES, weight=0.1)

    result = await circuit.diagnose(weak_synapse_threshold=0.2)
    assert len(result["weak_synapses"]) == 1
    assert result["weak_synapses"][0]["weight"] == 0.1


@pytest.mark.asyncio
async def test_diagnose_domain_balance(circuit):
    """Domain counts and imbalance ratio are computed."""
    for i in range(5):
        await circuit.add_neuron(Neuron.create(f"# Math {i}", domain="math"))
    await circuit.add_neuron(Neuron.create("# CS 1", domain="cs"))

    result = await circuit.diagnose()
    db = result["domain_balance"]
    assert db["counts"]["math"] == 5
    assert db["counts"]["cs"] == 1
    assert db["imbalance_ratio"] == 5.0


@pytest.mark.asyncio
async def test_diagnose_community_cohesion(circuit):
    """Intra/inter edge counts are correct."""
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    n3 = Neuron.create("# C")
    for n in (n1, n2, n3):
        await circuit.add_neuron(n)
    await circuit.add_synapse(n1.id, n2.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(n2.id, n3.id, SynapseType.RELATES_TO)

    # Manually assign communities
    circuit._graph.nodes[n1.id]["community_id"] = 0
    circuit._graph.nodes[n2.id]["community_id"] = 0
    circuit._graph.nodes[n3.id]["community_id"] = 1

    result = await circuit.diagnose()
    cc = result["community_cohesion"]
    assert cc["communities"] == 2
    # n1→n2 intra (both 0), n2→n3 inter (0→1)
    # relates_to is bidirectional: n1→n2, n2→n1, n2→n3, n3→n2
    # intra: n1→n2, n2→n1 (both community 0)
    # inter: n2→n3, n3→n2 (community 0→1, 1→0)
    assert cc["intra_edges"] >= 1
    assert cc["inter_edges"] >= 1


@pytest.mark.asyncio
async def test_diagnose_isolated_communities(circuit):
    """Communities with no cross-community edges are flagged."""
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    n3 = Neuron.create("# C")
    n4 = Neuron.create("# D")
    for n in (n1, n2, n3, n4):
        await circuit.add_neuron(n)
    # Only intra-community edges
    await circuit.add_synapse(n1.id, n2.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(n3.id, n4.id, SynapseType.RELATES_TO)

    circuit._graph.nodes[n1.id]["community_id"] = 0
    circuit._graph.nodes[n2.id]["community_id"] = 0
    circuit._graph.nodes[n3.id]["community_id"] = 1
    circuit._graph.nodes[n4.id]["community_id"] = 1

    result = await circuit.diagnose()
    # Both communities are isolated (no inter-community edges)
    assert 0 in result["isolated_communities"]
    assert 1 in result["isolated_communities"]


@pytest.mark.asyncio
async def test_diagnose_dangling_prerequisites(circuit):
    """Neurons requiring a weak prerequisite are flagged."""
    from datetime import datetime, timezone
    from spikuit_core import Spike

    prereq = Neuron.create("# Prerequisite")
    dependent = Neuron.create("# Dependent")
    await circuit.add_neuron(prereq)
    await circuit.add_neuron(dependent)
    await circuit.add_synapse(dependent.id, prereq.id, SynapseType.REQUIRES)

    # prereq has no spike history (never reviewed) → "never_reviewed"
    result = await circuit.diagnose()
    dangling = result["dangling_prerequisites"]
    assert any(d["requires"] == prereq.id and d["reason"] == "never_reviewed" for d in dangling)


@pytest.mark.asyncio
async def test_diagnose_source_freshness(circuit):
    """Source freshness counts are correct."""
    s1 = Source(url="http://example.com/a", title="A", status="active")
    s2 = Source(url="http://example.com/b", title="B", status="unreachable")
    s3 = Source(url="file:///local.txt", title="C")
    await circuit.add_source(s1)
    await circuit.add_source(s2)
    await circuit.add_source(s3)

    result = await circuit.diagnose()
    sf = result["source_freshness"]
    assert sf["total"] == 3
    assert sf["url_sources"] == 2
    assert sf["unreachable"] == 1


@pytest.mark.asyncio
async def test_diagnose_surprise_bridges(circuit):
    """Cross-community edges get surprise scores."""
    n1 = Neuron.create("# A")
    n2 = Neuron.create("# B")
    await circuit.add_neuron(n1)
    await circuit.add_neuron(n2)
    await circuit.add_synapse(n1.id, n2.id, SynapseType.RELATES_TO)

    circuit._graph.nodes[n1.id]["community_id"] = 0
    circuit._graph.nodes[n2.id]["community_id"] = 1

    result = await circuit.diagnose()
    bridges = result["surprise_bridges"]
    assert len(bridges) > 0
    assert bridges[0]["surprise_score"] > 0


@pytest.mark.asyncio
async def test_diagnose_empty_brain(circuit):
    """Diagnose on empty brain returns safe defaults."""
    result = await circuit.diagnose()
    assert result["orphans"] == []
    assert result["weak_synapses"] == []
    assert result["domain_balance"]["total"] == 0
    assert result["community_cohesion"]["communities"] == 0
    assert result["isolated_communities"] == []
    assert result["dangling_prerequisites"] == []
    assert result["surprise_bridges"] == []


# -- Domain Audit ----------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_audit_empty_brain(circuit):
    """Audit on empty brain returns empty results."""
    result = await circuit.domain_audit()
    assert result["domains"] == []
    assert result["suggestions"] == []
    assert result["community_keywords"] == {}


@pytest.mark.asyncio
async def test_domain_audit_single_domain_single_community(circuit):
    """Single domain in one community: no suggestions."""
    a = await circuit.add_neuron(Neuron.create("# Algebra\nRings and fields", type="concept", domain="math"))
    b = await circuit.add_neuron(Neuron.create("# Calculus\nLimits and derivatives", type="concept", domain="math"))
    await circuit.add_synapse(a.id, b.id, SynapseType.RELATES_TO)
    await circuit.detect_communities()

    result = await circuit.domain_audit()
    assert len(result["domains"]) == 1
    assert result["domains"][0]["domain"] == "math"
    assert result["domains"][0]["neuron_count"] == 2
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_domain_audit_split_suggestion(circuit):
    """Domain spanning 2 distinct communities triggers split suggestion."""
    # Cluster 1: tightly connected math-algebra neurons
    a1 = await circuit.add_neuron(Neuron.create("# Groups\nGroup theory", type="concept", domain="math"))
    a2 = await circuit.add_neuron(Neuron.create("# Rings\nRing theory", type="concept", domain="math"))
    a3 = await circuit.add_neuron(Neuron.create("# Fields\nField extensions", type="concept", domain="math"))
    await circuit.add_synapse(a1.id, a2.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(a2.id, a3.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(a1.id, a3.id, SynapseType.RELATES_TO)

    # Cluster 2: tightly connected math-calculus neurons
    b1 = await circuit.add_neuron(Neuron.create("# Limits\nEpsilon-delta", type="concept", domain="math"))
    b2 = await circuit.add_neuron(Neuron.create("# Derivatives\nDifferentiation", type="concept", domain="math"))
    b3 = await circuit.add_neuron(Neuron.create("# Integrals\nIntegration", type="concept", domain="math"))
    await circuit.add_synapse(b1.id, b2.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(b2.id, b3.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(b1.id, b3.id, SynapseType.RELATES_TO)

    await circuit.detect_communities()
    cmap = circuit.community_map()

    # Verify the two clusters are in different communities
    cluster1_comm = cmap[a1.id]
    cluster2_comm = cmap[b1.id]
    if cluster1_comm == cluster2_comm:
        # If Louvain puts them together (small graph), skip the assertion
        pytest.skip("Louvain merged clusters at this scale")

    result = await circuit.domain_audit()
    splits = [s for s in result["suggestions"] if s["action"] == "split"]
    assert len(splits) == 1
    assert splits[0]["domain"] == "math"
    assert len(splits[0]["communities"]) == 2


@pytest.mark.asyncio
async def test_domain_audit_merge_suggestion(circuit):
    """Multiple domains in same community triggers merge suggestion."""
    a = await circuit.add_neuron(Neuron.create("# ML Basics\nSupervised learning", type="concept", domain="ml"))
    b = await circuit.add_neuron(Neuron.create("# AI Ethics\nFairness in AI", type="concept", domain="ai"))
    c = await circuit.add_neuron(Neuron.create("# Deep Learning\nNeural networks", type="concept", domain="dl"))
    await circuit.add_synapse(a.id, b.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(b.id, c.id, SynapseType.RELATES_TO)
    await circuit.add_synapse(a.id, c.id, SynapseType.RELATES_TO)

    await circuit.detect_communities()

    result = await circuit.domain_audit()
    merges = [s for s in result["suggestions"] if s["action"] == "merge"]
    assert len(merges) == 1
    merge = merges[0]
    domain_names = {d["domain"] for d in merge["domains"]}
    assert domain_names == {"ml", "ai", "dl"}


@pytest.mark.asyncio
async def test_domain_audit_excludes_meta(circuit):
    """_meta domain and community_summary neurons are excluded from audit."""
    await circuit.add_neuron(Neuron.create("# Guide", type="guide", domain="_meta"))
    a = await circuit.add_neuron(Neuron.create("# Real", type="concept", domain="cs"))
    b = await circuit.add_neuron(Neuron.create("# Also Real", type="concept", domain="cs"))
    await circuit.add_synapse(a.id, b.id, SynapseType.RELATES_TO)
    await circuit.detect_communities()

    result = await circuit.domain_audit()
    domain_names = [d["domain"] for d in result["domains"]]
    assert "_meta" not in domain_names
    assert "cs" in domain_names


@pytest.mark.asyncio
async def test_domain_audit_keywords(circuit):
    """Community keywords are extracted from neuron titles."""
    a = await circuit.add_neuron(Neuron.create("# Functor\nCategory mapping", type="concept", domain="math"))
    b = await circuit.add_neuron(Neuron.create("# Monad\nEndofunctor monoid", type="concept", domain="math"))
    await circuit.add_synapse(a.id, b.id, SynapseType.RELATES_TO)
    await circuit.detect_communities()

    result = await circuit.domain_audit()
    # At least one community should have keywords
    assert any(len(kws) > 0 for kws in result["community_keywords"].values())
