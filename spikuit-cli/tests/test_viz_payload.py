"""Unit tests for spikuit_cli.viz.payload.build_viz_payload.

See docs/design/graph-viz.md §3 for the contract these pin.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Grade, Neuron, Spike, SynapseType

from spikuit_cli.viz.payload import build_viz_payload
from spikuit_tutor import TutorScheduler, TutorStore


@pytest_asyncio.fixture
async def circuit(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    yield c
    await c.close()


async def _add(circuit, nid, title, *, domain=None, type="concept"):
    n = Neuron.create(f"# {title}\n\n{title} body.", id=nid, type=type, domain=domain)
    await circuit.add_neuron(n)
    return n


# -- empty circuit ------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_circuit_returns_empty_payload(circuit):
    payload = await build_viz_payload(circuit)
    assert payload["meta"]["neuron_count"] == 0
    assert payload["meta"]["synapse_count"] == 0
    assert payload["meta"]["weight_domain"] == [0.0, 1.0]
    assert payload["groups"] == []
    assert payload["nodes"] == []
    assert payload["edges"] == []


# -- basic shape ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_payload_shape(circuit):
    await _add(circuit, "n1", "Functor", domain="math")
    await _add(circuit, "n2", "Monad", domain="math")
    await circuit.add_synapse("n1", "n2", type=SynapseType.REQUIRES, weight=0.7)

    payload = await build_viz_payload(circuit)
    assert payload["meta"]["neuron_count"] == 2
    assert payload["meta"]["synapse_count"] == 1
    ids = {n["id"] for n in payload["nodes"]}
    assert ids == {"n1", "n2"}
    n1 = next(n for n in payload["nodes"] if n["id"] == "n1")
    assert n1["label"] == "Functor"
    assert n1["domain"] == "math"
    assert n1["type"] == "concept"
    edge = payload["edges"][0]
    assert edge == {"source": "n1", "target": "n2", "type": "requires", "weight": 0.7, "co_fires": 0}


@pytest.mark.asyncio
async def test_bidirectional_synapse_types_produce_two_edges(circuit):
    # add_synapse docstring: contrasts/relates_to auto-create the reverse edge.
    await _add(circuit, "n1", "A")
    await _add(circuit, "n2", "B")
    await circuit.add_synapse("n1", "n2", type=SynapseType.RELATES_TO, weight=0.5)

    payload = await build_viz_payload(circuit)
    assert payload["meta"]["synapse_count"] == 2
    pairs = {(e["source"], e["target"]) for e in payload["edges"]}
    assert pairs == {("n1", "n2"), ("n2", "n1")}


# -- group slotting (top-8 + Other) --------------------------------------------


@pytest.mark.asyncio
async def test_group_slotting_top8_plus_other_by_domain(circuit):
    # 12 domains, sized 12,11,...,1 so ranking is unambiguous. Domains d0..d7
    # (sizes 12..5) should get slots 1..8; d8..d11 (sizes 4..1) fold into Other.
    nid = 0
    for i in range(12):
        domain = f"d{i}"
        for _ in range(12 - i):
            await _add(circuit, f"n{nid}", f"T{nid}", domain=domain)
            nid += 1

    payload = await build_viz_payload(circuit)
    assert payload["meta"]["coloring"] == "domain"

    named_groups = [g for g in payload["groups"] if g["slot"] != "other"]
    assert [g["slot"] for g in named_groups] == list(range(1, 9))
    assert [g["key"] for g in named_groups] == [f"d{i}" for i in range(8)]
    assert [g["count"] for g in named_groups] == [12, 11, 10, 9, 8, 7, 6, 5]

    other = next(g for g in payload["groups"] if g["slot"] == "other")
    assert other["count"] == 4 + 3 + 2 + 1  # d8..d11
    assert other["label"] == "Other"

    nodes_by_domain = {n["domain"]: n["group"] for n in payload["nodes"]}
    assert nodes_by_domain["d0"] == 1
    assert nodes_by_domain["d7"] == 8
    assert nodes_by_domain["d8"] == "other"
    assert nodes_by_domain["d11"] == "other"


@pytest.mark.asyncio
async def test_unassigned_nodes_fold_into_other(circuit):
    await _add(circuit, "n1", "A", domain="math")
    await _add(circuit, "n2", "B", domain=None)

    payload = await build_viz_payload(circuit)
    n2 = next(n for n in payload["nodes"] if n["id"] == "n2")
    assert n2["group"] == "other"
    other = next(g for g in payload["groups"] if g["slot"] == "other")
    assert other["count"] == 1


@pytest.mark.asyncio
async def test_communities_take_priority_over_domain_when_present(circuit):
    await _add(circuit, "n1", "A", domain="math")
    await _add(circuit, "n2", "B", domain="math")
    await _add(circuit, "n3", "C", domain="language")
    # Manually assign communities (in-memory graph attribute — exactly what
    # community_map() reads; avoids depending on Louvain's actual clustering
    # for a deterministic test).
    circuit.graph.nodes["n1"]["community_id"] = 0
    circuit.graph.nodes["n2"]["community_id"] = 0
    circuit.graph.nodes["n3"]["community_id"] = 1

    payload = await build_viz_payload(circuit)
    assert payload["meta"]["coloring"] == "community"
    assert {g["kind"] for g in payload["groups"]} == {"community"}
    n1 = next(n for n in payload["nodes"] if n["id"] == "n1")
    assert n1["community_id"] == 0


# -- tutor overlay --------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tutor_db_touched_by_default(circuit, tmp_path):
    await _add(circuit, "n1", "A")
    # No .tutor.db file exists anywhere near tmp_path; overlay=None must not
    # require or create one.
    payload = await build_viz_payload(circuit)
    assert payload["nodes"][0]["tutor"] is None
    assert payload["meta"]["overlay"] is None
    assert not (tmp_path / "test.tutor.db").exists()


@pytest.mark.asyncio
async def test_overlay_tutor_requires_scheduler(circuit):
    await _add(circuit, "n1", "A")
    with pytest.raises(ValueError, match="scheduler"):
        await build_viz_payload(circuit, overlay="tutor")


@pytest.mark.asyncio
async def test_size_by_stability_requires_tutor_overlay(circuit):
    await _add(circuit, "n1", "A")
    with pytest.raises(ValueError, match="overlay"):
        await build_viz_payload(circuit, size_by="stability")


@pytest.mark.asyncio
async def test_size_by_stability_with_overlay(circuit, tmp_path):
    await _add(circuit, "n1", "A")
    await _add(circuit, "n2", "B")
    sched = TutorScheduler(circuit, TutorStore(tmp_path / "test.tutor.db"))
    await sched.open()
    try:
        await sched.review(Spike(neuron_id="n1", grade=Grade.FIRE))
        payload = await build_viz_payload(
            circuit, overlay="tutor", size_by="stability", scheduler=sched
        )
    finally:
        await sched.close()

    n1 = next(n for n in payload["nodes"] if n["id"] == "n1")
    n2 = next(n for n in payload["nodes"] if n["id"] == "n2")
    assert n1["tutor"] is not None
    assert n1["tutor"]["stability"] == sched.get_card("n1").stability
    assert n1["tutor"]["state"] == sched.get_card("n1").state.name
    assert isinstance(n1["tutor"]["due_in_days"], float)
    assert n1["size_raw"] == n1["tutor"]["stability"]
    assert n2["tutor"] is None  # never reviewed — no card yet (lazy creation)
    assert n2["size_raw"] == 0.0


# -- adversarial content --------------------------------------------------------


@pytest.mark.asyncio
async def test_adversarial_titles_survive_as_plain_data(circuit):
    evil_title = '<script>alert(1)</script> & "quoted" \'stuff\''
    n = Neuron.create(f"# {evil_title}\n\nBody with a newline\nand `backticks`.", id="n1")
    await circuit.add_neuron(n)

    payload = await build_viz_payload(circuit)
    node = payload["nodes"][0]
    assert node["label"] == evil_title
    assert "<script>" in node["label"]  # unescaped — data, not markup
    assert "Body with a newline" in node["excerpt"]


# -- component numbering ---------------------------------------------------------


@pytest.mark.asyncio
async def test_component_id_numbers_by_size_desc(circuit):
    for nid in ("a1", "a2", "a3"):
        await _add(circuit, nid, nid)
    await circuit.add_synapse("a1", "a2", type=SynapseType.RELATES_TO, weight=0.5)
    await circuit.add_synapse("a2", "a3", type=SynapseType.RELATES_TO, weight=0.5)

    for nid in ("b1", "b2"):
        await _add(circuit, nid, nid)
    await circuit.add_synapse("b1", "b2", type=SynapseType.RELATES_TO, weight=0.5)

    await _add(circuit, "c1", "c1")  # singleton, own component

    payload = await build_viz_payload(circuit)
    assert payload["meta"]["component_count"] == 3
    comp = {n["id"]: n["component_id"] for n in payload["nodes"]}
    assert comp["a1"] == comp["a2"] == comp["a3"]
    assert comp["b1"] == comp["b2"]
    assert len({comp["a1"], comp["b1"], comp["c1"]}) == 3
    assert comp["a1"] == 0  # largest component is numbered first


# -- weight domain ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_weight_domain_reflects_actual_range(circuit):
    await _add(circuit, "n1", "A")
    await _add(circuit, "n2", "B")
    await _add(circuit, "n3", "C")
    await circuit.add_synapse("n1", "n2", type=SynapseType.REQUIRES, weight=0.2)
    await circuit.add_synapse("n2", "n3", type=SynapseType.REQUIRES, weight=0.9)

    payload = await build_viz_payload(circuit)
    assert payload["meta"]["weight_domain"] == [0.2, 0.9]


# -- spike recency ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spike_recency_null_when_never_fired(circuit):
    await _add(circuit, "n1", "A")
    payload = await build_viz_payload(circuit)
    assert payload["nodes"][0]["spike_recency"] is None


@pytest.mark.asyncio
async def test_spike_recency_populated_for_recent_spike(circuit, tmp_path):
    await _add(circuit, "n1", "A")
    sched = TutorScheduler(circuit, TutorStore(tmp_path / "test.tutor.db"))
    await sched.open()
    try:
        await sched.review(Spike(neuron_id="n1", grade=Grade.FIRE))
    finally:
        await sched.close()

    payload = await build_viz_payload(circuit)
    recency = payload["nodes"][0]["spike_recency"]
    assert recency is not None
    assert 0 <= recency < 60  # just happened


@pytest.mark.asyncio
async def test_spike_recency_null_outside_window(circuit, tmp_path):
    await _add(circuit, "n1", "A")
    sched = TutorScheduler(circuit, TutorStore(tmp_path / "test.tutor.db"))
    await sched.open()
    try:
        await sched.review(Spike(neuron_id="n1", grade=Grade.FIRE))
    finally:
        await sched.close()

    # window=0 days: even a just-fired spike is already "outside" the window.
    payload = await build_viz_payload(circuit, spikes_window_days=0)
    assert payload["nodes"][0]["spike_recency"] is None
