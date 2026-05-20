"""Neuron management commands: spkt neuron {add,list,inspect,remove,merge,due,fire}."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from spikuit_core import Grade, Neuron, Source, Spike

from ..helpers import (
    _GRADE_MAP,
    _extract_title,
    _get_circuit,
    _get_scheduler,
    _neuron_dict,
    _out,
    _run,
)

neuron_app = typer.Typer(help="Manage neurons.")


@neuron_app.command(name="add")
def neuron_add(
    content: str = typer.Argument(..., help="Markdown content for the neuron"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Neuron type"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain tag"),
    source_url: Optional[str] = typer.Option(None, "--source-url", help="Source URL for citation"),
    source_title: Optional[str] = typer.Option(None, "--source-title", help="Source title"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Add a new Neuron to the circuit."""

    async def _add():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            real_content = content.encode().decode("unicode_escape")
            neuron = Neuron.create(real_content, type=type, domain=domain)
            await circuit.add_neuron(neuron)

            # Attach source if URL provided
            source_attached = None
            if source_url:
                existing = await circuit.find_source_by_url(source_url)
                if existing:
                    await circuit.attach_source(neuron.id, existing.id)
                    source_attached = existing
                else:
                    src = Source(url=source_url, title=source_title)
                    await circuit.add_source(src)
                    await circuit.attach_source(neuron.id, src.id)
                    source_attached = src

            if as_json:
                d = _neuron_dict(neuron, circuit)
                if source_attached:
                    d["source_id"] = source_attached.id
                    d["source_url"] = source_attached.url
                _out(d, use_json=True)
            else:
                typer.echo(f"Added neuron {neuron.id}")
                if source_attached:
                    typer.echo(f"  source: {source_attached.id} ({source_attached.url})")
        finally:
            await circuit.close()

    _run(_add())


@neuron_app.command(name="list")
def neuron_list(
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max neurons to show"),
    meta_keys: bool = typer.Option(False, "--meta-keys", help="List filterable/searchable metadata keys"),
    meta_values: Optional[str] = typer.Option(None, "--meta-values", help="List distinct values for a metadata key"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """List neurons, or query metadata keys/values."""

    async def _list():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            # Meta-key discovery mode
            if meta_keys:
                keys = await circuit.get_meta_keys()
                if as_json:
                    _out(keys, use_json=True)
                else:
                    if not keys:
                        typer.echo("No metadata keys found.")
                        return
                    typer.echo("Metadata keys:")
                    for k in keys:
                        samples = ", ".join(k["sample_values"][:3])
                        typer.echo(f"  {k['key']}  [{k['layer']}]  ({k['count']} sources)  e.g. {samples}")
                return

            # Meta-values mode
            if meta_values:
                values = await circuit.get_meta_values(meta_values)
                if as_json:
                    _out(values, use_json=True)
                else:
                    if not values:
                        typer.echo(f"No values found for key '{meta_values}'.")
                        return
                    typer.echo(f"Values for '{meta_values}':")
                    for v in values:
                        typer.echo(f"  {v['value']}  [{v['layer']}]  ({v['count']})")
                return

            # Default: list neurons
            kwargs = {"limit": limit}
            if type:
                kwargs["type"] = type
            if domain:
                kwargs["domain"] = domain
            neurons = await circuit.list_neurons(**kwargs)
            if as_json:
                _out([_neuron_dict(n, circuit) for n in neurons], use_json=True)
            else:
                if not neurons:
                    typer.echo("No neurons found.")
                    return
                typer.echo(f"{len(neurons)} neuron(s):")
                for n in neurons:
                    title = _extract_title(n.content)
                    meta = ""
                    if n.type:
                        meta += f"  [{n.type}]"
                    if n.domain:
                        meta += f"  @{n.domain}"
                    typer.echo(f"  {n.id}  {title}{meta}")
        finally:
            await circuit.close()

    _run(_list())


@neuron_app.command(name="inspect")
def neuron_inspect(
    neuron_id: str = typer.Argument(..., help="Neuron ID to inspect"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Inspect a neuron: content, FSRS state, pressure, neighbors."""

    async def _inspect():
        circuit = _get_circuit(brain)
        await circuit.connect()
        scheduler = _get_scheduler(circuit, brain)
        await scheduler.open()
        try:
            neuron = await circuit.get_neuron(neuron_id)
            if neuron is None:
                typer.echo(f"Neuron {neuron_id} not found", err=True)
                raise typer.Exit(1)

            sources = await circuit.get_sources_for_neuron(neuron_id)
            community_id = circuit.get_community(neuron_id)
            card = scheduler.get_card(neuron_id)

            if as_json:
                d = _neuron_dict(neuron, circuit, card=card)
                d["neighbors_out"] = circuit.neighbors(neuron_id)
                d["neighbors_in"] = circuit.predecessors(neuron_id)
                d["community_id"] = community_id
                d["sources"] = [
                    {"id": s.id, "url": s.url, "title": s.title}
                    for s in sources
                ]
                _out(d, use_json=True)
            else:
                typer.echo(f"ID:       {neuron.id}")
                typer.echo(f"Type:     {neuron.type or '-'}")
                typer.echo(f"Domain:   {neuron.domain or '-'}")
                typer.echo(f"Created:  {neuron.created_at}")

                if card:
                    stab = f"{card.stability:.2f}" if card.stability is not None else "-"
                    diff = f"{card.difficulty:.2f}" if card.difficulty is not None else "-"
                    typer.echo(f"FSRS:     stability={stab}  difficulty={diff}  state={card.state.name}  due={card.due}")

                pressure = circuit.get_pressure(neuron_id)
                typer.echo(f"Pressure: {pressure:.4f}")

                if community_id is not None:
                    typer.echo(f"Community: {community_id}")

                if sources:
                    typer.echo(f"Sources ({len(sources)}):")
                    for s in sources:
                        label = s.title or s.url or s.id
                        typer.echo(f"  {s.id}  {label}")

                neighbors = circuit.neighbors(neuron_id)
                preds = circuit.predecessors(neuron_id)
                if neighbors:
                    typer.echo(f"Out ({len(neighbors)}): {', '.join(neighbors)}")
                if preds:
                    typer.echo(f"In  ({len(preds)}):  {', '.join(preds)}")

                typer.echo(f"\n{neuron.content}")
        finally:
            await scheduler.close()
            await circuit.close()

    _run(_inspect())


@neuron_app.command(name="remove")
def neuron_remove(
    neuron_id: str = typer.Argument(..., help="Neuron ID to remove"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Remove a neuron and its synapses."""

    async def _remove():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            neuron = await circuit.get_neuron(neuron_id)
            if neuron is None:
                typer.echo(f"Neuron {neuron_id} not found", err=True)
                raise typer.Exit(1)
            await circuit.remove_neuron(neuron_id)
            if as_json:
                _out({"removed": neuron_id}, use_json=True)
            else:
                typer.echo(f"Removed neuron {neuron_id}")
        finally:
            await circuit.close()

    _run(_remove())


@neuron_app.command(name="merge")
def neuron_merge(
    source_ids: list[str] = typer.Argument(..., help="Neuron IDs to merge (absorbed)"),
    into: str = typer.Option(..., "--into", help="Target neuron ID (kept)"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Merge multiple neurons into one target neuron.

    Source neurons are absorbed: their content is appended,
    synapses redirected, and source attachments transferred.
    """

    async def _merge():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            result = await circuit.merge_neurons(source_ids, into)
            if as_json:
                _out(result, use_json=True)
            else:
                typer.echo(f"Merged {result['merged']} neuron(s) into {result['into']}")
                typer.echo(f"  synapses redirected: {result['synapses_redirected']}")
                typer.echo(f"  sources transferred: {result['sources_transferred']}")
        finally:
            await circuit.close()

    _run(_merge())


@neuron_app.command(name="due")
def neuron_due(
    limit: int = typer.Option(20, "--limit", "-n", help="Max neurons to show"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Show neurons due for review."""

    async def _due():
        circuit = _get_circuit(brain)
        await circuit.connect()
        scheduler = _get_scheduler(circuit, brain)
        await scheduler.open()
        try:
            ids = await scheduler.due_neurons(limit=limit)
            if as_json:
                items = []
                for nid in ids:
                    neuron = await circuit.get_neuron(nid)
                    if neuron:
                        items.append(
                            _neuron_dict(neuron, circuit, card=scheduler.get_card(nid))
                        )
                _out(items, use_json=True)
            else:
                if not ids:
                    typer.echo("No neurons due for review.")
                    return
                typer.echo(f"{len(ids)} neuron(s) due:")
                for nid in ids:
                    neuron = await circuit.get_neuron(nid)
                    pressure = circuit.get_pressure(nid)
                    title = _extract_title(neuron.content) if neuron else nid
                    p_indicator = f"  pressure={pressure:.2f}" if pressure > 0 else ""
                    typer.echo(f"  {nid}  {title}{p_indicator}")
        finally:
            await scheduler.close()
            await circuit.close()

    _run(_due())


@neuron_app.command(name="fire")
def neuron_fire(
    neuron_id: str = typer.Argument(..., help="Neuron ID to fire"),
    grade: str = typer.Option("fire", "--grade", "-g", help="Grade: miss|weak|fire|strong"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Fire a spike (record a review) on a Neuron.

    Tutor-orchestrated since Stage 2 (``tutor-extraction-stage2.md``
    §4.2, §4.7): the tutor schedules the FSRS card and then calls the
    substrate's ``fire`` for grade-driven plasticity.
    """
    g = _GRADE_MAP.get(grade.lower())
    if g is None:
        typer.echo(f"Invalid grade: {grade}. Use: miss, weak, fire, strong", err=True)
        raise typer.Exit(1)

    async def _fire():
        circuit = _get_circuit(brain)
        await circuit.connect()
        scheduler = _get_scheduler(circuit, brain)
        await scheduler.open()
        try:
            neuron = await circuit.get_neuron(neuron_id)
            if neuron is None:
                typer.echo(f"Neuron {neuron_id} not found", err=True)
                raise typer.Exit(1)
            now = datetime.now(timezone.utc)
            spike = Spike(neuron_id=neuron_id, grade=g, fired_at=now)
            card = await scheduler.review(spike)
            if as_json:
                _out({
                    "neuron_id": neuron_id,
                    "grade": grade,
                    "stability": card.stability,
                    "difficulty": card.difficulty,
                    "due": str(card.due),
                    "state": card.state.name,
                }, use_json=True)
            else:
                typer.echo(f"Fired {grade} on {neuron_id}")
                typer.echo(f"  stability={card.stability:.2f}  difficulty={card.difficulty:.2f}  due={card.due}")
        finally:
            await scheduler.close()
            await circuit.close()

    _run(_fire())
