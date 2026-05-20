"""Entry point for the spkt CLI."""

from __future__ import annotations

import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from spikuit_core import Circuit, Grade, Neuron, Source, SynapseType
from spikuit_core.config import BrainConfig, find_spikuit_root, init_brain, load_config
from spikuit_core.embedder import create_embedder

from .commands import (
    branch_app,
    community_app,
    domain_app,
    history_app,
    neuron_app,
    skills_app,
    source_app,
    synapse_app,
    undo_cmd,
)
from .commands.git import write_gitignore
from .commands.skills import install_agent_skills
from .helpers import (
    _GRADE_MAP,
    _extract_title,
    _get_circuit,
    _get_scheduler,
    _load_brain_config,
    _neuron_dict,
    _out,
    _run,
)

app = typer.Typer(
    name="spkt",
    help="Spikuit — neural knowledge graph with spaced repetition.",
    no_args_is_help=True,
)

# Register resource sub-apps
app.add_typer(neuron_app, name="neuron")
app.add_typer(synapse_app, name="synapse")
app.add_typer(source_app, name="source")
app.add_typer(domain_app, name="domain")
app.add_typer(community_app, name="community")
app.add_typer(skills_app, name="skills")
app.add_typer(branch_app, name="branch")
app.add_typer(history_app, name="history")
app.command(name="undo")(undo_cmd)


# -------------------------------------------------------------------
# init
# -------------------------------------------------------------------


_VALID_PROVIDERS = ("openai-compat", "ollama")
_VALID_MODES = ("study", "rag")

_STUDY_NEXT_STEPS = """\
Next steps for study mode:
  1. Open your Agent CLI in this directory
  2. Run /spkt-tutor — the tutor will ask "What are you studying?" and
     build a starter roadmap, then drop into review.
  3. As you learn, add neurons with: spkt neuron add "<markdown>" -t concept -d <domain>
"""

_RAG_NEXT_STEPS = """\
Next steps for RAG mode:
  1. Ingest sources:
       spkt source ingest https://example.com/article -d <domain>
       spkt source ingest ./paper.pdf -d <domain>
  2. Backfill embeddings if you skipped the embedder above:
       spkt embed-all
  3. Query the brain:
       spkt retrieve "<question>"
  4. Export a read-only bundle for a server:
       spkt export qabot --output ./brain.db
"""

_PROVIDER_DEFAULTS = {
    "openai-compat": {
        "base_url": "http://localhost:1234/v1",
        "model": "text-embedding-nomic-embed-text-v1.5",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "nomic-embed-text",
    },
}


@app.command()
def init(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Brain name (defaults to directory name)"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Embedder: none|openai-compat|ollama"),
    base_url: str = typer.Option("", "--base-url", help="Embedder API base URL"),
    model: str = typer.Option("", "--model", "-m", help="Embedding model name"),
    dimension: int = typer.Option(768, "--dimension", "-d", help="Embedding dimension"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Onboarding mode: study|rag (affects next-step guidance only)"),
    git: bool = typer.Option(True, "--git/--no-git", help="Initialize a git repository for Brain version control (default: yes)"),
    as_json: bool = typer.Option(False, "--json", help="Non-interactive JSON output"),
) -> None:
    """Initialize a new brain in the current directory.

    Without flags, starts an interactive wizard.
    With --json or explicit --provider, runs non-interactively.

    The brain layout is identical for study and RAG modes; the choice only
    changes the onboarding guidance printed at the end.
    """
    interactive = not as_json and provider is None

    if mode is not None and mode not in _VALID_MODES:
        typer.echo(f"Invalid mode '{mode}'. Choose from: {', '.join(_VALID_MODES)}", err=True)
        raise typer.Exit(1)

    if interactive:
        default_name = Path.cwd().name
        name = typer.prompt("Brain name", default=default_name)

        if typer.confirm("Configure embeddings?", default=False):
            typer.echo(f"  Providers: {', '.join(_VALID_PROVIDERS)}")
            while True:
                emb_provider = typer.prompt("  Provider", default="openai-compat")
                if emb_provider in _VALID_PROVIDERS:
                    break
                typer.echo(f"  Invalid provider. Choose from: {', '.join(_VALID_PROVIDERS)}")

            defaults = _PROVIDER_DEFAULTS[emb_provider]
            base_url = typer.prompt("  Base URL", default=defaults["base_url"])
            model = typer.prompt("  Model", default=defaults["model"])
            dimension = int(typer.prompt("  Dimension", default="768"))
            provider = emb_provider
        else:
            provider = "none"

        if mode is None:
            typer.echo("")
            typer.echo("How will you use this brain?")
            typer.echo("  study — review with /spkt-tutor (FSRS, scaffolded teaching)")
            typer.echo("  rag   — ingest sources and query with /spkt-qabot")
            while True:
                mode_input = typer.prompt("  Mode", default="study")
                if mode_input in _VALID_MODES:
                    mode = mode_input
                    break
                typer.echo(f"  Invalid mode. Choose from: {', '.join(_VALID_MODES)}")

        typer.echo("")
        typer.echo("--- Summary ---")
        typer.echo(f"Brain:    {name}")
        typer.echo(f"Location: {Path.cwd() / '.spikuit/'}")
        typer.echo(f"Mode:     {mode}")
        typer.echo(f"Embedder: {provider}")
        if provider != "none":
            typer.echo(f"  URL:    {base_url}")
            typer.echo(f"  Model:  {model}")
            typer.echo(f"  Dim:    {dimension}")

        if not typer.confirm("\nCreate brain?", default=True):
            raise typer.Abort()
    else:
        if provider is None:
            provider = "none"

    try:
        config = init_brain(
            name=name,
            embedder_provider=provider,
            embedder_base_url=base_url,
            embedder_model=model,
            embedder_dimension=dimension,
        )
    except FileExistsError:
        typer.echo(".spikuit/ already exists in this directory.", err=True)
        raise typer.Exit(1)

    git_initialized = False
    if git:
        import subprocess

        write_gitignore(config.root)
        existing = subprocess.run(
            ["git", "-C", str(config.root), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
        if existing.returncode != 0:
            try:
                subprocess.run(
                    ["git", "-C", str(config.root), "init", "-q", "-b", "main"],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(config.root), "add", ".gitignore", ".spikuit/config.toml"],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(config.root),
                        "commit",
                        "-q",
                        "-m",
                        f"manual: init brain '{config.name}'",
                    ],
                    check=True,
                )
                git_initialized = True
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                typer.echo(f"  warning: git init skipped ({e})", err=True)

    if as_json:
        _out({
            "root": str(config.root),
            "db": str(config.db_path),
            "config": str(config.config_path),
            "embedder": config.embedder.provider,
            "name": config.name,
            "mode": mode,
            "git": git_initialized,
        }, use_json=True)
    else:
        typer.echo(f"\nInitialized brain '{config.name}' at {config.spikuit_dir}/")
        typer.echo(f"  config: {config.config_path}")
        typer.echo(f"  db:     {config.db_path}")
        if config.embedder.provider != "none":
            typer.echo(f"  embedder: {config.embedder.provider} ({config.embedder.model})")
        else:
            typer.echo(f"  embedder: none (edit config.toml to enable)")
        if git_initialized:
            typer.echo("  git:      initialized (.gitignore + initial commit)")
        elif git:
            typer.echo("  git:      already present")

        if mode is not None:
            typer.echo("")
            typer.echo(_STUDY_NEXT_STEPS if mode == "study" else _RAG_NEXT_STEPS)

        # Agent CLI skills installation
        if interactive:
            typer.echo("")
            if typer.confirm("Install skills for an Agent CLI? (/tutor, /learn, /qabot)", default=False):
                install_agent_skills(config.root)


# -------------------------------------------------------------------
# config
# -------------------------------------------------------------------


@app.command()
def config(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show current brain configuration."""
    cfg = load_config()
    root = find_spikuit_root()

    if as_json:
        _out({
            "root": str(cfg.root),
            "name": cfg.name,
            "db": str(cfg.db_path),
            "found": root is not None,
            "embedder": {
                "provider": cfg.embedder.provider,
                "base_url": cfg.embedder.base_url,
                "model": cfg.embedder.model,
                "dimension": cfg.embedder.dimension,
            },
        }, use_json=True)
    else:
        if root is None:
            typer.echo("No .spikuit/ found (using ~/.spikuit/ fallback)")
        else:
            typer.echo(f"Brain: {cfg.name}")
            typer.echo(f"Root:  {cfg.root}")
        typer.echo(f"DB:    {cfg.db_path}")
        typer.echo(f"Embedder: {cfg.embedder.provider}")
        if cfg.embedder.provider != "none":
            typer.echo(f"  url:   {cfg.embedder.base_url}")
            typer.echo(f"  model: {cfg.embedder.model}")
            typer.echo(f"  dim:   {cfg.embedder.dimension}")


# -------------------------------------------------------------------
# embed-all
# -------------------------------------------------------------------


@app.command(name="embed-all")
def embed_all(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Embed all neurons that don't have embeddings yet (backfill).

    Shows a plan (neuron count, estimated tokens) before proceeding.
    Use ``--yes`` to skip the confirmation prompt.
    """

    async def _embed_all():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            if circuit._embedder is None:
                typer.echo("No embedder configured. Edit .spikuit/config.toml to enable.", err=True)
                raise typer.Exit(1)

            # Calculate plan: how many neurons need embedding
            all_neurons = await circuit.list_neurons(limit=100_000)
            to_embed = []
            for n in all_neurons:
                rows = await circuit._db.conn.execute_fetchall(
                    "SELECT 1 FROM neuron_vec_map WHERE neuron_id = ?", (n.id,)
                )
                if not rows:
                    to_embed.append(n)

            if not to_embed:
                if as_json:
                    _out({"embedded": 0, "message": "All neurons already have embeddings"}, use_json=True)
                else:
                    typer.echo("All neurons already have embeddings.")
                return

            total_chars = sum(len(n.content) for n in to_embed)
            est_tokens = total_chars // 4

            if as_json and not yes:
                _out({
                    "plan": {
                        "total_neurons": len(all_neurons),
                        "to_embed": len(to_embed),
                        "estimated_chars": total_chars,
                        "estimated_tokens": est_tokens,
                    }
                }, use_json=True)
                return

            if not yes:
                typer.echo("Embed-all plan:")
                typer.echo(f"  Total neurons:    {len(all_neurons)}")
                typer.echo(f"  To embed:         {len(to_embed)}")
                typer.echo(f"  Estimated chars:  {total_chars:,}")
                typer.echo(f"  Estimated tokens: ~{est_tokens:,}")
                if not typer.confirm("Proceed?", default=True):
                    typer.echo("Aborted.")
                    return

            count = await circuit.embed_all()
            if as_json:
                _out({"embedded": count}, use_json=True)
            else:
                typer.echo(f"Embedded {count} neuron(s).")
        finally:
            await circuit.close()

    _run(_embed_all())


# -------------------------------------------------------------------
# retrieve
# -------------------------------------------------------------------


@app.command()
def retrieve(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter as key=value (repeatable)"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Retrieve neurons matching a query (graph-weighted scoring).

    Use --filter to restrict results by neuron fields (type, domain)
    or source filterable metadata. Example: --filter domain=math --filter year=2020
    """

    async def _retrieve():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            # Parse filters
            filters: dict[str, str] | None = None
            if filter:
                filters = {}
                for f in filter:
                    if "=" not in f:
                        typer.echo(f"Invalid filter format: {f} (expected key=value)", err=True)
                        raise typer.Exit(1)
                    k, v = f.split("=", 1)
                    filters[k] = v
            results = await circuit.retrieve(query, limit=limit, filters=filters)
            if as_json:
                _out([_neuron_dict(n, circuit) for n in results], use_json=True)
            else:
                if not results:
                    typer.echo("No matching neurons found.")
                    return
                typer.echo(f"{len(results)} result(s):")
                for n in results:
                    pressure = circuit.get_pressure(n.id)
                    title = _extract_title(n.content)
                    p_str = f"  p={pressure:.2f}" if pressure > 0 else ""
                    typer.echo(f"  {n.id}  {title}{p_str}")
        finally:
            await circuit.close()

    _run(_retrieve())


# -------------------------------------------------------------------
# stats
# -------------------------------------------------------------------


@app.command()
def stats(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Show circuit statistics."""

    async def _stats():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            s = await circuit.stats()
            if as_json:
                _out(s, use_json=True)
            else:
                typer.echo(f"Neurons:      {s['neurons']}")
                typer.echo(f"Synapses:     {s['synapses']}")
                typer.echo(f"Density:      {s['graph_density']:.4f}")
                typer.echo(f"Communities:  {s['communities']}")
        finally:
            await circuit.close()

    _run(_stats())


# -------------------------------------------------------------------
# diagnose
# -------------------------------------------------------------------


@app.command()
def diagnose(
    weak_threshold: float = typer.Option(0.2, "--weak-threshold", help="Weight threshold for weak synapses"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text, json, html"),
    as_json: bool = typer.Option(False, "--json", help="Shorthand for --format json"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Run brain health diagnostics.

    Analyzes orphan neurons, weak synapses, domain balance,
    community cohesion, bridge gaps, dangling prerequisites,
    source freshness, and surprise bridges.
    """

    async def _diagnose():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            result = await circuit.diagnose(
                weak_synapse_threshold=weak_threshold,
            )

            fmt = "json" if as_json else format

            if fmt == "json":
                _out(result, use_json=True)
            elif fmt == "html":
                html = _diagnose_html(result)
                typer.echo(html)
            else:
                _diagnose_text(result)
        finally:
            await circuit.close()

    _run(_diagnose())


def _diagnose_text(d: dict) -> None:
    """Render diagnose result as human-readable text."""
    # Orphans
    orphans = d["orphans"]
    typer.echo(f"Orphan neurons: {len(orphans)}")
    if orphans:
        for nid in orphans[:10]:
            typer.echo(f"  {nid}")
        if len(orphans) > 10:
            typer.echo(f"  ... and {len(orphans) - 10} more")

    # Weak synapses
    weak = d["weak_synapses"]
    typer.echo(f"\nWeak synapses: {len(weak)}")
    for s in weak[:10]:
        typer.echo(f"  {s['pre']} --{s['type']}--> {s['post']}  w={s['weight']:.2f}")

    # Domain balance
    db = d["domain_balance"]
    typer.echo(f"\nDomain balance ({db['total']} neurons):")
    for domain, count in sorted(db["counts"].items(), key=lambda x: -x[1]):
        typer.echo(f"  {domain:20s}  {count}")
    typer.echo(f"  Imbalance ratio: {db['imbalance_ratio']:.1f}")

    # Community cohesion
    cc = d["community_cohesion"]
    typer.echo(f"\nCommunity cohesion ({cc['communities']} communities):")
    typer.echo(f"  Intra-community edges: {cc['intra_edges']}")
    typer.echo(f"  Inter-community edges: {cc['inter_edges']}")
    typer.echo(f"  Cohesion ratio: {cc['cohesion_ratio']:.2f}")

    # Isolated communities
    iso = d["isolated_communities"]
    if iso:
        typer.echo(f"\nIsolated communities (no bridges): {iso}")

    # Dangling prerequisites
    dangling = d["dangling_prerequisites"]
    typer.echo(f"\nDangling prerequisites: {len(dangling)}")
    for dp in dangling[:10]:
        typer.echo(f"  {dp['neuron']} requires {dp['requires']} ({dp['reason']})")

    # Source freshness
    sf = d["source_freshness"]
    typer.echo(f"\nSources: {sf['total']} total, {sf['url_sources']} URL")
    if sf["unreachable"]:
        typer.echo(f"  Unreachable: {sf['unreachable']}")
    if sf["never_fetched"]:
        typer.echo(f"  Never fetched: {sf['never_fetched']}")

    # Surprise bridges
    bridges = d["surprise_bridges"]
    if bridges:
        typer.echo(f"\nSurprise bridges (top {len(bridges)}):")
        for b in bridges[:5]:
            typer.echo(f"  {b['pre']} --{b['type']}--> {b['post']}  communities={b['communities']}  score={b['surprise_score']}")


def _diagnose_html(d: dict) -> str:
    """Render diagnose result as a self-contained HTML report."""
    sections = []

    # Orphans
    orphans = d["orphans"]
    rows = "".join(f"<li><code>{nid}</code></li>" for nid in orphans[:20])
    if len(orphans) > 20:
        rows += f"<li>... and {len(orphans) - 20} more</li>"
    sections.append(f"<h2>Orphan Neurons ({len(orphans)})</h2><ul>{rows}</ul>" if orphans else f"<h2>Orphan Neurons (0)</h2><p>None</p>")

    # Weak synapses
    weak = d["weak_synapses"]
    if weak:
        ws_rows = "".join(
            f"<tr><td><code>{s['pre']}</code></td><td>{s['type']}</td><td><code>{s['post']}</code></td><td>{s['weight']:.2f}</td></tr>"
            for s in weak[:20]
        )
        sections.append(f"<h2>Weak Synapses ({len(weak)})</h2><table><tr><th>Pre</th><th>Type</th><th>Post</th><th>Weight</th></tr>{ws_rows}</table>")
    else:
        sections.append("<h2>Weak Synapses (0)</h2><p>None</p>")

    # Domain balance
    db = d["domain_balance"]
    db_rows = "".join(
        f"<tr><td>{domain}</td><td>{count}</td></tr>"
        for domain, count in sorted(db["counts"].items(), key=lambda x: -x[1])
    )
    sections.append(f"<h2>Domain Balance</h2><table><tr><th>Domain</th><th>Count</th></tr>{db_rows}</table><p>Imbalance ratio: {db['imbalance_ratio']:.1f}</p>")

    # Community cohesion
    cc = d["community_cohesion"]
    sections.append(
        f"<h2>Community Cohesion</h2>"
        f"<p>{cc['communities']} communities | "
        f"Intra: {cc['intra_edges']} | Inter: {cc['inter_edges']} | "
        f"Cohesion: {cc['cohesion_ratio']:.2f}</p>"
    )

    # Isolated communities
    iso = d["isolated_communities"]
    if iso:
        sections.append(f"<h2>Isolated Communities</h2><p>{', '.join(str(c) for c in iso)}</p>")

    # Dangling prerequisites
    dangling = d["dangling_prerequisites"]
    if dangling:
        dp_rows = "".join(
            f"<tr><td><code>{dp['neuron']}</code></td><td><code>{dp['requires']}</code></td><td>{dp['reason']}</td></tr>"
            for dp in dangling[:20]
        )
        sections.append(f"<h2>Dangling Prerequisites ({len(dangling)})</h2><table><tr><th>Neuron</th><th>Requires</th><th>Reason</th></tr>{dp_rows}</table>")

    # Source freshness
    sf = d["source_freshness"]
    sections.append(f"<h2>Source Freshness</h2><p>{sf['total']} total, {sf['url_sources']} URL, {sf['unreachable']} unreachable, {sf['never_fetched']} never fetched</p>")

    # Surprise bridges
    bridges = d["surprise_bridges"]
    if bridges:
        br_rows = "".join(
            f"<tr><td><code>{b['pre']}</code></td><td>{b['type']}</td><td><code>{b['post']}</code></td><td>{b['communities']}</td><td>{b['surprise_score']}</td></tr>"
            for b in bridges[:10]
        )
        sections.append(f"<h2>Surprise Bridges (top {min(len(bridges), 10)})</h2><table><tr><th>Pre</th><th>Type</th><th>Post</th><th>Communities</th><th>Score</th></tr>{br_rows}</table>")

    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Brain Diagnostics</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #333; }}
h1 {{ border-bottom: 2px solid #e0e0e0; padding-bottom: 0.5rem; }}
h2 {{ color: #555; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f5f5f5; }}
code {{ background: #f0f0f0; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }}
</style></head>
<body><h1>Brain Diagnostics</h1>{body}</body></html>"""


# -------------------------------------------------------------------
# tutor — FSRS-scheduled review and progress
# -------------------------------------------------------------------

tutor_app = typer.Typer(help="Tutor — FSRS-scheduled review and learning progress.")
app.add_typer(tutor_app, name="tutor")


@tutor_app.command(name="progress")
def progress(
    domain_filter: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text, json, html"),
    as_json: bool = typer.Option(False, "--json", help="Shorthand for --format json"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Show learning progress report.

    Mastery levels, retention rate, learning velocity, weak spots,
    and review adherence. Optionally filter by domain.

    Stage 2 (``tutor-extraction-stage2.md`` §4.7) moved this report out
    of the substrate into ``spikuit-tutor`` — it reads FSRS card state,
    which now lives in the tutor's overlay store — so it surfaces under
    ``spkt tutor`` rather than as a top-level command.
    """

    async def _progress():
        from spikuit_tutor import compute_progress

        circuit = _get_circuit(brain)
        await circuit.connect()
        scheduler = _get_scheduler(circuit, brain)
        await scheduler.open()
        try:
            result = await compute_progress(scheduler, domain=domain_filter)

            fmt = "json" if as_json else format

            if fmt == "json":
                _out(result, use_json=True)
            elif fmt == "html":
                html = _progress_html(result)
                typer.echo(html)
            else:
                _progress_text(result)
        finally:
            await scheduler.close()
            await circuit.close()

    _run(_progress())


def _progress_text(d: dict) -> None:
    """Render progress result as human-readable text."""
    if d["domain_filter"]:
        typer.echo(f"Progress report (domain: {d['domain_filter']})\n")
    else:
        typer.echo("Progress report\n")

    # Mastery
    mastery = d["mastery"]
    if mastery:
        typer.echo("Mastery by domain:")
        for domain, m in sorted(mastery.items()):
            stab = f"{m['avg_stability']:.1f}d" if m["avg_stability"] is not None else "-"
            ret = f"{m['avg_retrievability']:.0%}" if m["avg_retrievability"] is not None else "-"
            typer.echo(f"  {domain:20s}  {m['neuron_count']} neurons  stability={stab}  retrievability={ret}  ({m['reviewed_count']} reviewed)")
    else:
        typer.echo("No neurons found.")

    # Retention
    r = d["retention"]
    typer.echo(f"\nRetention rate: {r['overall']:.0%} ({r['total_reviews']} reviews)" if r["overall"] is not None else "\nRetention rate: - (no reviews)")
    if r["per_domain"]:
        for domain, rate in sorted(r["per_domain"].items()):
            if rate is not None:
                typer.echo(f"  {domain:20s}  {rate:.0%}")

    # Velocity
    v = d["velocity"]
    typer.echo(f"\nLearning velocity ({v['total_neurons']} total neurons):")
    for w in v["weekly"]:
        bar = "\u2588" * w["added"] if w["added"] > 0 else "-"
        typer.echo(f"  {w['week_of']}  +{w['added']:3d}  {bar}")

    # Weak spots
    ws = d["weak_spots"]
    if ws:
        typer.echo(f"\nWeak spots (important but not mastered):")
        for w in ws[:10]:
            stab = f"{w['stability']:.1f}d" if w["stability"] is not None else "never"
            typer.echo(f"  {w['id']}  @{w['domain'] or '-'}  stability={stab}  centrality={w['centrality']}")

    # Adherence
    a = d["adherence"]
    rate = f"{a['adherence_rate']:.0%}" if a["adherence_rate"] is not None else "-"
    typer.echo(f"\nReview adherence: {rate} ({a['reviewed_at_least_once']}/{a['total_neurons']} reviewed, {a['currently_overdue']} overdue)")


def _progress_html(d: dict) -> str:
    """Render progress result as HTML report."""
    title = f"Progress Report — {d['domain_filter']}" if d["domain_filter"] else "Progress Report"
    sections = []

    # Mastery
    mastery = d["mastery"]
    if mastery:
        rows = ""
        for domain, m in sorted(mastery.items()):
            stab = f"{m['avg_stability']:.1f}" if m["avg_stability"] is not None else "-"
            ret = f"{m['avg_retrievability']:.0%}" if m["avg_retrievability"] is not None else "-"
            rows += f"<tr><td>{domain}</td><td>{m['neuron_count']}</td><td>{stab}</td><td>{ret}</td><td>{m['reviewed_count']}</td></tr>"
        sections.append(f"<h2>Mastery</h2><table><tr><th>Domain</th><th>Neurons</th><th>Avg Stability (days)</th><th>Avg Retrievability</th><th>Reviewed</th></tr>{rows}</table>")

    # Retention
    r = d["retention"]
    overall = f"{r['overall']:.0%}" if r["overall"] is not None else "-"
    sections.append(f"<h2>Retention</h2><p>Overall: {overall} ({r['total_reviews']} reviews)</p>")

    # Velocity
    v = d["velocity"]
    v_rows = "".join(f"<tr><td>{w['week_of']}</td><td>{w['added']}</td></tr>" for w in v["weekly"])
    sections.append(f"<h2>Learning Velocity</h2><p>{v['total_neurons']} total neurons</p><table><tr><th>Week</th><th>Added</th></tr>{v_rows}</table>")

    # Weak spots
    ws = d["weak_spots"]
    if ws:
        ws_rows = "".join(
            f"<tr><td><code>{w['id']}</code></td><td>{w['domain'] or '-'}</td><td>{w['stability'] if w['stability'] is not None else 'never'}</td><td>{w['centrality']}</td></tr>"
            for w in ws[:10]
        )
        sections.append(f"<h2>Weak Spots</h2><table><tr><th>ID</th><th>Domain</th><th>Stability</th><th>Centrality</th></tr>{ws_rows}</table>")

    # Adherence
    a = d["adherence"]
    rate = f"{a['adherence_rate']:.0%}" if a["adherence_rate"] is not None else "-"
    sections.append(f"<h2>Review Adherence</h2><p>{rate} ({a['reviewed_at_least_once']}/{a['total_neurons']} reviewed, {a['currently_overdue']} overdue)</p>")

    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #333; }}
h1 {{ border-bottom: 2px solid #e0e0e0; padding-bottom: 0.5rem; }}
h2 {{ color: #555; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f5f5f5; }}
code {{ background: #f0f0f0; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }}
</style></head>
<body><h1>{title}</h1>{body}</body></html>"""


# -------------------------------------------------------------------
# consolidate (sleep-inspired knowledge consolidation)
# -------------------------------------------------------------------

consolidate_app = typer.Typer(help="Sleep-inspired knowledge consolidation.")
app.add_typer(consolidate_app, name="consolidate")


@consolidate_app.callback(invoke_without_command=True)
def consolidate_plan(
    ctx: typer.Context,
    domain_filter: Optional[str] = typer.Option(None, "--domain", "-d", help="Target specific domain (TMR)"),
    decay_factor: float = typer.Option(0.8, "--decay", help="Weight decay factor (SHY phase)"),
    similarity: float = typer.Option(0.85, "--similarity", help="Similarity threshold for latent synapses"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    export_file: Optional[Path] = typer.Option(None, "--export", "-o", help="Export plan to JSON file"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Generate a consolidation plan (dry-run).

    Shows what would happen: weight decays, prunable synapses,
    latent connections, near-duplicates, and forget candidates.
    Use 'spkt consolidate apply' to execute the plan.
    """
    if ctx.invoked_subcommand is not None:
        return

    import json as json_mod

    async def _plan():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            plan = await circuit.consolidate(
                decay_factor=decay_factor,
                similarity_threshold=similarity,
                domain=domain_filter,
            )
            if export_file:
                export_file.write_text(json_mod.dumps(plan, indent=2, default=str))
                typer.echo(f"Plan exported to {export_file}")
            if as_json:
                _out(plan, use_json=True)
            else:
                _consolidate_text(plan)
        finally:
            await circuit.close()

    _run(_plan())


@consolidate_app.command(name="apply")
def consolidate_apply(
    plan_file: Optional[Path] = typer.Argument(None, help="Plan JSON file (or uses most recent dry-run)"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Apply a consolidation plan.

    Validates that the Brain hasn't changed since the plan was generated
    (state hash check). If no plan file is given, generates and applies
    a fresh plan in one step.
    """
    import json as json_mod

    async def _apply():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            if plan_file:
                plan = json_mod.loads(plan_file.read_text())
            else:
                plan = await circuit.consolidate()
            result = await circuit.apply_consolidation(plan)
            if as_json:
                _out(result, use_json=True)
            else:
                typer.echo("Consolidation applied:")
                typer.echo(f"  Synapses added:  {result['synapses_added']}")
                typer.echo(f"  Weights decayed: {result['weights_decayed']}")
                typer.echo(f"  Synapses pruned: {result['synapses_pruned']}")
                typer.echo(f"  Neurons removed: {result['neurons_removed']}")
        finally:
            await circuit.close()

    _run(_apply())


def _consolidate_text(plan: dict) -> None:
    s = plan["summary"]
    domain = plan.get("domain")
    header = f"Consolidation plan"
    if domain:
        header += f" (domain: {domain})"
    typer.echo(f"{header}  [hash: {plan['state_hash']}]\n")

    typer.echo("Summary:")
    typer.echo(f"  Latent synapses to add:   {s['latent_synapses']}")
    typer.echo(f"  Weights to decay:         {s['weight_decays']}")
    typer.echo(f"  Synapses to prune:        {s['prunable_synapses']}")
    typer.echo(f"  Neurons to remove:        {s['removable_neurons']}")
    typer.echo(f"  Near-duplicates found:    {s['near_duplicates']}")
    typer.echo(f"  Forget candidates:        {s['forget_candidates']}")

    if plan["shy"]["prunable"]:
        typer.echo(f"\nPrunable synapses ({len(plan['shy']['prunable'])}):")
        for p in plan["shy"]["prunable"][:10]:
            typer.echo(f"  {p['pre']} --{p['type']}--> {p['post']}  w={p['old_weight']:.3f}→{p['new_weight']:.3f}")

    if plan["sws"]["latent_synapses"]:
        typer.echo(f"\nLatent synapses ({len(plan['sws']['latent_synapses'])}):")
        for ls in plan["sws"]["latent_synapses"][:10]:
            typer.echo(f"  {ls['pre']} ↔ {ls['post']}  sim={ls['similarity']:.3f}")

    if plan["rem"]["near_duplicates"]:
        typer.echo(f"\nNear-duplicates ({len(plan['rem']['near_duplicates'])}):")
        for nd in plan["rem"]["near_duplicates"][:10]:
            typer.echo(f"  {nd['neuron_a']} ↔ {nd['neuron_b']}  sim={nd['similarity']:.3f}  [{nd['action']}]")

    if plan["triage"]["forget_candidates"]:
        typer.echo(f"\nForget candidates ({len(plan['triage']['forget_candidates'])}):")
        for fc in plan["triage"]["forget_candidates"][:10]:
            typer.echo(f"  {fc['id']}  stability={fc['stability']}  centrality={fc['centrality']}  age={fc['age_days']}d")

    typer.echo(f"\nTo apply: spkt consolidate apply")


# -------------------------------------------------------------------
# manual (auto-generated user guide)
# -------------------------------------------------------------------


@app.command()
def manual(
    format: str = typer.Option("text", "--format", "-f", help="Output format: text, json, html"),
    as_json: bool = typer.Option(False, "--json", help="Shorthand for --format json"),
    write_meta: bool = typer.Option(False, "--write-meta", help="Write _meta neurons to the brain"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Generate a user guide for this Brain.

    Shows domain overview, representative topics, knowledge cutoff,
    coverage notes, and source attribution. Use --write-meta to
    store the guide as _meta neurons for RAG retrieval.
    """

    async def _manual():
        circuit = _get_circuit(brain)
        await circuit.connect()
        try:
            data = await circuit.generate_manual(write_meta=write_meta)
            fmt = "json" if as_json else format
            if fmt == "json":
                _out(data, use_json=True)
            elif fmt == "html":
                typer.echo(_manual_html(data))
            else:
                _manual_text(data)
                if write_meta:
                    typer.echo("\n_meta neurons written to brain.")
        finally:
            await circuit.close()

    _run(_manual())


def _manual_text(d: dict) -> None:
    typer.echo(f"Brain Manual — {d['neuron_count']} neurons\n")

    if d["domains"]:
        typer.echo("Domains:")
        for dom in d["domains"]:
            coverage = " (limited)" if dom["limited_coverage"] else ""
            typer.echo(f"  {dom['name']:20s} {dom['neuron_count']:>4d} neurons{coverage}")
            if dom["topics"]:
                typer.echo(f"    Topics: {', '.join(dom['topics'])}")
        typer.echo()

    cutoff = d["cutoff"] or "no sources fetched"
    typer.echo(f"Knowledge cutoff: {cutoff}")

    if d["sources"]:
        typer.echo(f"\nSources ({len(d['sources'])}):")
        for src in d["sources"]:
            title = src["title"] or "untitled"
            typer.echo(f"  - {title}")


def _manual_html(d: dict) -> str:
    lines = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8"><title>Brain Manual</title>',
        '<style>',
        'body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #333; }',
        'h1 { border-bottom: 2px solid #e0e0e0; padding-bottom: 0.5rem; }',
        'h2 { color: #555; margin-top: 2rem; }',
        'table { border-collapse: collapse; width: 100%; margin: 0.5rem 0; }',
        'th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }',
        'th { background: #f5f5f5; }',
        '.limited { color: #c0392b; font-size: 0.85em; }',
        '</style></head>',
        f'<body><h1>Brain Manual</h1><p>{d["neuron_count"]} neurons</p>',
    ]

    if d["domains"]:
        lines.append('<h2>Domains</h2><table><tr><th>Domain</th><th>Neurons</th><th>Topics</th><th>Coverage</th></tr>')
        for dom in d["domains"]:
            topics = ", ".join(dom["topics"]) if dom["topics"] else "-"
            cov = '<span class="limited">limited</span>' if dom["limited_coverage"] else "good"
            lines.append(f'<tr><td>{dom["name"]}</td><td>{dom["neuron_count"]}</td><td>{topics}</td><td>{cov}</td></tr>')
        lines.append('</table>')

    cutoff = d["cutoff"] or "no sources fetched"
    lines.append(f'<h2>Knowledge Cutoff</h2><p>{cutoff}</p>')

    if d["sources"]:
        lines.append(f'<h2>Sources ({len(d["sources"])})</h2><ul>')
        for src in d["sources"]:
            title = src["title"] or "untitled"
            if src["url"]:
                lines.append(f'<li><a href="{src["url"]}">{title}</a></li>')
            else:
                lines.append(f'<li>{title}</li>')
        lines.append('</ul>')

    lines.append('</body></html>')
    return "\n".join(lines)


# -------------------------------------------------------------------
# quiz (interactive flashcard session)
# -------------------------------------------------------------------


@app.command()
def quiz(
    limit: int = typer.Option(10, "--limit", "-n", help="Max neurons per session"),
    as_json: bool = typer.Option(False, "--json", help="Non-interactive JSON dump of all due quiz render payloads"),
    no_tui: bool = typer.Option(False, "--no-tui", help="Drive the session via stdin/stdout JSON (one QuizResponse per line)"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Run an interactive flashcard review session.

    Default: Textual TUI with flip, 1-4 grading, and optional notes.
    --json:  Dump all due quiz render payloads at once, then exit.
    --no-tui: Stream one RenderResponse per line to stdout, read one
              QuizResponse per line from stdin, grade and record.
    """
    from spikuit_tutor.quiz import Flashcard as NewFlashcard
    from spikuit_tutor.quiz.models import QuizResponse as NewQuizResponse
    from spikuit_tutor import compute_scaffold
    from spikuit_core import Spike
    import dataclasses as _dc

    async def _quiz():
        circuit = _get_circuit(brain)
        await circuit.connect()
        scheduler = _get_scheduler(circuit, brain)
        await scheduler.open()
        try:
            due_ids = await scheduler.due_neurons(limit=limit)

            if not due_ids:
                if as_json or no_tui:
                    _out({"status": "no_due", "reviewed": 0}, use_json=True)
                else:
                    typer.echo("No neurons due for review.")
                return

            # Build flashcard queue
            queue: list[tuple[str, NewFlashcard]] = []
            for nid in due_ids:
                neuron = await circuit.get_neuron(nid)
                if neuron is None:
                    continue
                scaffold = compute_scaffold(scheduler, nid)
                queue.append((nid, NewFlashcard(neuron, scaffold)))

            def _render_payload(nid: str, fc: NewFlashcard) -> dict:
                rr = fc.render()
                return {
                    "neuron_id": nid,
                    "quiz_type": rr.quiz_type,
                    "mode": rr.mode,
                    "scaffold_level": fc.scaffold.level.value,
                    "front": _dc.asdict(rr.front),
                    "back": _dc.asdict(rr.back),
                    "grade_choices": [
                        {"key": c.key, "grade": c.grade.name, "label": c.label}
                        for c in rr.grade_choices
                    ],
                    "accepts_notes": rr.accepts_notes,
                    "context": list(fc.scaffold.context),
                    "gaps": list(fc.scaffold.gaps),
                }

            # --json: batch dump
            if as_json:
                items = [_render_payload(nid, fc) for nid, fc in queue]
                _out(
                    {"status": "due", "count": len(items), "items": items},
                    use_json=True,
                )
                return

            # --no-tui: interactive stdin/stdout JSON loop
            if no_tui:
                import json as _json

                reviewed = 0
                grades = {"miss": 0, "weak": 0, "fire": 0, "strong": 0}
                notes: list[dict] = []
                for nid, fc in queue:
                    payload = _render_payload(nid, fc)
                    print(_json.dumps(payload), flush=True)
                    line = sys.stdin.readline()
                    if not line:
                        break
                    try:
                        data = _json.loads(line)
                    except _json.JSONDecodeError:
                        typer.echo(f"invalid json: {line!r}", err=True)
                        break
                    if data.get("action") == "quit":
                        break
                    self_grade_name = data.get("self_grade")
                    if self_grade_name is None:
                        typer.echo("missing self_grade in response", err=True)
                        continue
                    try:
                        grade = Grade[self_grade_name.upper()]
                    except KeyError:
                        typer.echo(f"unknown grade: {self_grade_name}", err=True)
                        continue
                    note = data.get("notes")
                    response = NewQuizResponse(self_grade=grade, notes=note)
                    result = fc.grade(response)
                    final_grade = result.grade or grade
                    await scheduler.review(
                        Spike(neuron_id=nid, grade=final_grade, notes=note)
                    )
                    reviewed += 1
                    grades[final_grade.name.lower()] += 1
                    if note:
                        notes.append({"neuron_id": nid, "note": note})
                _out(
                    {
                        "status": "done",
                        "reviewed": reviewed,
                        "grades": grades,
                        "notes": notes,
                    },
                    use_json=True,
                )
                return

            # Default: Textual TUI
            from spikuit_tutor.quiz.tui import QuizApp

            recorded: list[tuple[str, Grade, Optional[str]]] = []

            def _record(neuron_id: str, grade: Grade, note: Optional[str]) -> None:
                recorded.append((neuron_id, grade, note))

            tui_app = QuizApp(queue=queue, record=_record)
            result = await tui_app.run_async()

            # Flush recorded grades through the tutor scheduler
            for neuron_id, grade, note in recorded:
                await scheduler.review(Spike(neuron_id=neuron_id, grade=grade, notes=note))

            # Summary
            if result is None:
                typer.echo("Session ended.")
                return
            typer.echo(f"\nSession complete: {result.reviewed} reviewed")
            for g, count in result.grades.items():
                if count > 0:
                    typer.echo(f"  {g}: {count}")
            if result.notes:
                typer.echo(f"\n{len(result.notes)} note(s) captured:")
                for nid, note in result.notes:
                    typer.echo(f"  {nid}: {note}")

        finally:
            await scheduler.close()
            await circuit.close()

    _run(_quiz())


# -------------------------------------------------------------------
# visualize
# -------------------------------------------------------------------


@app.command()
def visualize(
    output: Path = typer.Option("circuit.html", "--output", "-o", help="Output HTML path"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open in browser"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Generate an interactive graph visualization (HTML)."""
    from pyvis.network import Network as PyvisNetwork

    async def _visualize():
        circuit = _get_circuit(brain)
        await circuit.connect()
        scheduler = _get_scheduler(circuit, brain)
        await scheduler.open()
        try:
            graph = circuit.graph
            if graph.number_of_nodes() == 0:
                typer.echo("Circuit is empty — nothing to visualize.")
                return

            net = PyvisNetwork(
                height="100vh",
                width="100%",
                directed=True,
                bgcolor="#1a1a2e",
                font_color="#e0e0e0",
                select_menu=True,
                cdn_resources="in_line",
            )

            net.set_options("""{
                "physics": {
                    "forceAtlas2Based": {
                        "gravitationalConstant": -80,
                        "centralGravity": 0.01,
                        "springLength": 120,
                        "springConstant": 0.08,
                        "damping": 0.4
                    },
                    "solver": "forceAtlas2Based",
                    "stabilization": {"iterations": 150}
                },
                "edges": {
                    "arrows": {"to": {"enabled": true, "scaleFactor": 0.6}},
                    "smooth": {"type": "curvedCW", "roundness": 0.15},
                    "color": {"inherit": false}
                },
                "interaction": {
                    "hover": true,
                    "tooltipDelay": 100,
                    "multiselect": true
                }
            }""")

            _DOMAIN_COLORS = {
                "math": "#e74c3c",
                "cs": "#3498db",
                "language": "#2ecc71",
                "philosophy": "#9b59b6",
            }
            _COMMUNITY_PALETTE = [
                "#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#f39c12",
                "#1abc9c", "#e67e22", "#e91e63", "#00bcd4", "#8bc34a",
                "#ff5722", "#607d8b", "#cddc39", "#795548", "#03a9f4",
            ]
            _DEFAULT_NODE_COLOR = "#5dade2"

            # Determine coloring strategy: communities first, fallback to domain
            cmap = circuit.community_map()
            use_community_colors = len(cmap) > 0

            # Compute degree centrality for node sizing
            centrality_map: dict[str, float] = {}
            if graph.number_of_nodes() > 1:
                import networkx as nx_local
                centrality_map = nx_local.degree_centrality(graph)

            for nid in graph.nodes:
                node_data = graph.nodes[nid]
                neuron = await circuit.get_neuron(nid)
                title = _extract_title(neuron.content) if neuron else nid
                domain = node_data.get("domain")
                pressure = node_data.get("pressure", 0.0)
                community_id = node_data.get("community_id")

                # Size: base + stability + centrality (not just pressure)
                card = scheduler.get_card(nid)
                stability = card.stability if card and card.stability else 0.0
                centrality = centrality_map.get(nid, 0.0)
                size = 12 + stability * 3 + centrality * 20 + min(pressure, 1.0) * 10

                # Color: community-based or domain-based
                if use_community_colors and community_id is not None:
                    color = _COMMUNITY_PALETTE[community_id % len(_COMMUNITY_PALETTE)]
                    group = community_id  # pyvis physics clustering
                elif domain:
                    color = _DOMAIN_COLORS.get(domain, _DEFAULT_NODE_COLOR)
                    group = None
                else:
                    color = _DEFAULT_NODE_COLOR
                    group = None

                tooltip = f"<b>{title}</b><br>ID: {nid}"
                if community_id is not None:
                    tooltip += f"<br>community: {community_id}"
                if card:
                    if card.stability is not None:
                        tooltip += f"<br>stability: {card.stability:.1f}"
                    if card.difficulty is not None:
                        tooltip += f"<br>difficulty: {card.difficulty:.1f}"
                    tooltip += f"<br>state: {card.state.name}"
                if pressure > 0:
                    tooltip += f"<br>pressure: {pressure:.3f}"

                kwargs = {"label": title, "title": tooltip, "size": size, "color": color, "font": {"size": 12}}
                if group is not None:
                    kwargs["group"] = group
                net.add_node(nid, **kwargs)

            _EDGE_STYLES = {
                "requires": {"color": "#e74c3c", "dashes": False},
                "extends": {"color": "#f39c12", "dashes": False},
                "contrasts": {"color": "#9b59b6", "dashes": [5, 5]},
                "relates_to": {"color": "#95a5a6", "dashes": [2, 4]},
            }

            for u, v, data in graph.edges(data=True):
                syn_type = data.get("type", "relates_to")
                weight = data.get("weight", 0.5)
                co_fires = data.get("co_fires", 0)
                style = _EDGE_STYLES.get(syn_type, _EDGE_STYLES["relates_to"])
                edge_width = 1 + weight * 4
                tooltip = f"{syn_type}<br>weight: {weight:.2f}<br>co_fires: {co_fires}"
                net.add_edge(u, v, title=tooltip, width=edge_width, color=style["color"], dashes=style.get("dashes", False))

            net.save_graph(str(output))

            html = output.read_text()
            css_inject = "<style>html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; }</style>"

            # Build legend HTML
            legend_items = ""
            if use_community_colors:
                groups: dict[int, int] = {}
                for nid, cid in cmap.items():
                    groups[cid] = groups.get(cid, 0) + 1
                for cid in sorted(groups):
                    c = _COMMUNITY_PALETTE[cid % len(_COMMUNITY_PALETTE)]
                    legend_items += (
                        f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0">'
                        f'<span style="width:12px;height:12px;border-radius:50%;background:{c};display:inline-block"></span>'
                        f'<span>Community {cid} ({groups[cid]})</span></div>'
                    )
            else:
                for domain_name, c in _DOMAIN_COLORS.items():
                    legend_items += (
                        f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0">'
                        f'<span style="width:12px;height:12px;border-radius:50%;background:{c};display:inline-block"></span>'
                        f'<span>{domain_name}</span></div>'
                    )

            legend_html = (
                '<div id="legend" style="position:fixed;top:10px;right:10px;background:rgba(26,26,46,0.9);'
                'padding:12px 16px;border-radius:8px;color:#e0e0e0;font:13px monospace;z-index:1000;'
                f'max-height:50vh;overflow-y:auto">{legend_items}</div>'
            )

            html = html.replace("<head>", f"<head>{css_inject}", 1)
            html = html.replace("</body>", f"{legend_html}</body>", 1)
            output.write_text(html)

            typer.echo(f"Saved to {output} ({graph.number_of_nodes()} neurons, {graph.number_of_edges()} synapses)")

            if open_browser:
                import webbrowser
                webbrowser.open(f"file://{output.resolve()}")
        finally:
            await scheduler.close()
            await circuit.close()

    _run(_visualize())


# -------------------------------------------------------------------
# export / import
# -------------------------------------------------------------------


@app.command(name="export")
def export_cmd(
    output: Path = typer.Option(..., "--output", "-o", help="Output file path"),
    format: str = typer.Option("tar", "--format", help="Export format: tar, json, qabot"),
    include_embeddings: bool = typer.Option(False, "--include-embeddings", help="Include embeddings in JSON export"),
    as_json: bool = typer.Option(False, "--json", help="Output result as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """Export the brain for backup or deployment.

    Formats:
      tar   — Full .spikuit/ archive (default)
      json  — Portable JSON bundle (neurons, synapses, sources)
      qabot — Read-only SQLite for QABot deployment
    """

    async def _export():
        config = _load_brain_config(brain)

        if format == "tar":
            _export_tar(config, output)
        elif format == "json":
            await _export_json(config, output, include_embeddings, brain)
        elif format == "qabot":
            await _export_qabot(config, output, brain)
        else:
            typer.echo(f"Unknown format: {format}", err=True)
            raise typer.Exit(1)

        if as_json:
            _out({"format": format, "output": str(output), "size": output.stat().st_size}, use_json=True)
        else:
            size_kb = output.stat().st_size / 1024
            typer.echo(f"Exported ({format}) \u2192 {output} ({size_kb:.1f} KB)")

    _run(_export())


def _export_tar(config: BrainConfig, output: Path) -> None:
    """Export .spikuit/ as a tar.gz archive."""
    import tarfile

    spikuit_dir = config.spikuit_dir
    if not spikuit_dir.exists():
        typer.echo(f".spikuit/ not found at {config.root}", err=True)
        raise typer.Exit(1)

    with tarfile.open(output, "w:gz") as tar:
        tar.add(spikuit_dir, arcname=".spikuit")


async def _export_json(config: BrainConfig, output: Path, include_embeddings: bool, brain_path: Path | None) -> None:
    """Export brain as a JSON bundle."""
    circuit = _get_circuit(brain_path)
    await circuit.connect()
    try:
        neurons = await circuit.list_neurons(limit=100_000)
        sources = await circuit.list_sources(limit=100_000)

        # Collect synapses from graph
        synapses = []
        for u, v, data in circuit.graph.edges(data=True):
            synapses.append({
                "pre_id": u,
                "post_id": v,
                "type": data.get("type", "relates_to"),
                "weight": data.get("weight", 0.5),
                "co_fires": data.get("co_fires", 0),
            })

        # Collect neuron-source links
        neuron_sources = []
        for n in neurons:
            nsources = await circuit.get_sources_for_neuron(n.id)
            for s in nsources:
                neuron_sources.append({"neuron_id": n.id, "source_id": s.id})

        bundle: dict = {
            "version": "0.4.0",
            "brain_name": config.name,
            "neurons": [
                {
                    "id": n.id,
                    "content": n.content,
                    "type": n.type,
                    "domain": n.domain,
                    "created_at": str(n.created_at),
                    "updated_at": str(n.updated_at),
                }
                for n in neurons
            ],
            "synapses": synapses,
            "sources": [
                {
                    "id": s.id,
                    "url": s.url,
                    "title": s.title,
                    "author": s.author,
                    "content_hash": s.content_hash,
                    "filterable": s.filterable,
                    "searchable": s.searchable,
                    "status": s.status,
                    "created_at": str(s.created_at),
                }
                for s in sources
            ],
            "neuron_sources": neuron_sources,
            "communities": circuit.community_map(),
        }

        if include_embeddings:
            emb_map = {}
            for n in neurons:
                rows = await circuit._db.conn.execute_fetchall(
                    "SELECT vec FROM neuron_vec WHERE rowid IN (SELECT rowid FROM neuron_vec_map WHERE neuron_id = ?)",
                    (n.id,),
                )
                if rows:
                    blob = rows[0]["vec"]
                    dim = len(blob) // 4
                    vec = list(struct.unpack(f"{dim}f", blob))
                    emb_map[n.id] = vec
            bundle["embeddings"] = emb_map

        output.write_text(json.dumps(bundle, ensure_ascii=False, default=str, indent=2))
    finally:
        await circuit.close()


async def _export_qabot(config: BrainConfig, output: Path, brain_path: Path | None) -> None:
    """Export a read-only QABot SQLite bundle."""
    from spikuit_core.export import export_qabot_bundle

    circuit = _get_circuit(brain_path)
    await circuit.connect()
    try:
        await export_qabot_bundle(circuit, config, output)
    finally:
        await circuit.close()


@app.command(name="import")
def import_cmd(
    input_path: Path = typer.Argument(..., help="Archive file to import (.tar.gz)"),
    target: Optional[Path] = typer.Option(None, "--target", help="Target directory (default: CWD)"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Import a brain from a tar.gz archive."""
    import tarfile

    if not input_path.exists():
        typer.echo(f"File not found: {input_path}", err=True)
        raise typer.Exit(1)

    dest = target or Path.cwd()
    spikuit_dir = dest / ".spikuit"

    if spikuit_dir.exists():
        typer.echo(f".spikuit/ already exists at {dest}. Remove it first or use a different target.", err=True)
        raise typer.Exit(1)

    with tarfile.open(input_path, "r:gz") as tar:
        tar.extractall(path=dest)

    if as_json:
        _out({"imported": str(input_path), "target": str(dest)}, use_json=True)
    else:
        typer.echo(f"Imported {input_path} \u2192 {dest}/.spikuit/")


# -------------------------------------------------------------------
# Deprecation wrappers (hidden, removed in v0.6.0)
# -------------------------------------------------------------------

_DEPRECATION_MAP = {
    "add": "neuron add",
    "fire": "neuron fire",
    "due": "neuron due",
    "list": "neuron list",
    "link": "synapse add",
    "inspect": "neuron inspect",
    "communities": "community list/detect",
    "learn": "source ingest",
    "refresh": "source refresh",
}


def _deprecation_warning(old: str) -> None:
    new = _DEPRECATION_MAP[old]
    typer.echo(f"DeprecationWarning: 'spkt {old}' is deprecated. Use 'spkt {new}' instead.", err=True)


from .commands.neuron import (
    neuron_add,
    neuron_due,
    neuron_fire,
    neuron_inspect,
    neuron_list,
)
from .commands.source import source_ingest, source_refresh
from .commands.synapse import synapse_add


@app.command(name="add", hidden=True)
def add_deprecated(
    content: str = typer.Argument(..., help="Markdown content for the neuron"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Neuron type"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain tag"),
    source_url: Optional[str] = typer.Option(None, "--source-url", help="Source URL for citation"),
    source_title: Optional[str] = typer.Option(None, "--source-title", help="Source title"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt neuron add' instead."""
    _deprecation_warning("add")
    neuron_add(content=content, type=type, domain=domain, source_url=source_url, source_title=source_title, as_json=as_json, brain=brain)


@app.command(name="fire", hidden=True)
def fire_deprecated(
    neuron_id: str = typer.Argument(..., help="Neuron ID to fire"),
    grade: str = typer.Option("fire", "--grade", "-g", help="Grade: miss|weak|fire|strong"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt neuron fire' instead."""
    _deprecation_warning("fire")
    neuron_fire(neuron_id=neuron_id, grade=grade, as_json=as_json, brain=brain)


@app.command(name="due", hidden=True)
def due_deprecated(
    limit: int = typer.Option(20, "--limit", "-n", help="Max neurons to show"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt neuron due' instead."""
    _deprecation_warning("due")
    neuron_due(limit=limit, as_json=as_json, brain=brain)


@app.command(name="list", hidden=True)
def list_deprecated(
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max neurons to show"),
    meta_keys: bool = typer.Option(False, "--meta-keys", help="List filterable/searchable metadata keys"),
    meta_values: Optional[str] = typer.Option(None, "--meta-values", help="List distinct values for a metadata key"),
    domains: bool = typer.Option(False, "--domains", help="List domains with neuron counts"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt neuron list' or 'spkt domain list' instead."""
    if domains:
        _deprecation_warning("list")
        typer.echo("Hint: use 'spkt domain list' for domain listing.", err=True)
        from .commands.domain import domain_list
        domain_list(as_json=as_json, brain=brain)
    else:
        _deprecation_warning("list")
        neuron_list(type=type, domain=domain, limit=limit, meta_keys=meta_keys, meta_values=meta_values, as_json=as_json, brain=brain)


@app.command(name="link", hidden=True)
def link_deprecated(
    pre: str = typer.Argument(..., help="Source neuron ID"),
    post: str = typer.Argument(..., help="Target neuron ID"),
    type: str = typer.Option("relates_to", "--type", "-t", help="Synapse type"),
    weight: float = typer.Option(0.5, "--weight", "-w", help="Initial weight"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt synapse add' instead."""
    _deprecation_warning("link")
    synapse_add(pre=pre, post=post, type=type, weight=weight, as_json=as_json, brain=brain)


@app.command(name="inspect", hidden=True)
def inspect_deprecated(
    neuron_id: str = typer.Argument(..., help="Neuron ID to inspect"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt neuron inspect' instead."""
    _deprecation_warning("inspect")
    neuron_inspect(neuron_id=neuron_id, as_json=as_json, brain=brain)


@app.command(name="communities", hidden=True)
def communities_deprecated(
    detect: bool = typer.Option(False, "--detect", help="Force re-detection"),
    resolution: float = typer.Option(1.0, "--resolution", "-r", help="Louvain resolution"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt community detect' or 'spkt community list' instead."""
    _deprecation_warning("communities")
    if detect:
        from .commands.community import community_detect
        community_detect(resolution=resolution, as_json=as_json, brain=brain)
    else:
        from .commands.community import community_list
        community_list(as_json=as_json, brain=brain)


@app.command(name="learn", hidden=True)
def learn_deprecated(
    path_or_url: str = typer.Argument(..., help="File path, directory, or URL to ingest"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain tag"),
    title: Optional[str] = typer.Option(None, "--title", help="Source title override"),
    force: bool = typer.Option(False, "--force", help="Force ingest"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt source ingest' instead."""
    _deprecation_warning("learn")
    source_ingest(path_or_url=path_or_url, domain=domain, title=title, force=force, as_json=as_json, brain=brain)


@app.command(name="refresh", hidden=True)
def refresh_deprecated(
    source_id: Optional[str] = typer.Argument(None, help="Source ID to refresh"),
    stale: Optional[int] = typer.Option(None, "--stale", help="Refresh sources older than N days"),
    all_sources: bool = typer.Option(False, "--all", help="Refresh all URL sources"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    brain: Optional[Path] = typer.Option(None, "--brain", "-b", help="Brain root directory"),
) -> None:
    """[Deprecated] Use 'spkt source refresh' instead."""
    _deprecation_warning("refresh")
    source_refresh(source_id=source_id, stale=stale, all_sources=all_sources, as_json=as_json, brain=brain)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
