"""Skills management commands: spkt skills {install,list}."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

skills_app = typer.Typer(help="Manage Spikuit skills for Agent CLIs.")


def _discover_skills() -> list[str]:
    """Return sorted list of skill directory names bundled in this package."""
    import importlib.resources

    skills_pkg = importlib.resources.files("spikuit_cli") / "skills"
    names = []
    for item in skills_pkg.iterdir():
        if item.is_dir() and (item / "SKILL.md").is_file():
            names.append(item.name)
    return sorted(names)


def _skill_display_name(name: str) -> str:
    """Convert directory name to slash-command name: spkt-tutor → /spkt-tutor."""
    return f"/{name}"


def _generate_agent_context() -> str:
    """Generate SPIKUIT.md — agent-facing context with overview and commands."""
    return """\
# Spikuit — Agent Context

Spikuit is a neural knowledge graph with spaced repetition.
The `spkt` CLI is the primary interface. All commands support `--json` for
machine-readable output and `--brain <path>` to target a specific Brain.

## Commands

### Root

| Command | Purpose |
|---------|---------|
| `spkt init` | Initialize a new Brain |
| `spkt config` | Show brain configuration |
| `spkt embed-all` | Backfill embeddings for existing neurons |
| `spkt retrieve "<query>"` | Graph-weighted search (keyword + semantic + memory + centrality) |
| `spkt stats` | Circuit statistics |
| `spkt diagnose` | Brain health diagnostics |
| `spkt manual` | Auto-generated user guide from brain contents |
| `spkt consolidate` | Sleep-inspired graph optimization (dry-run) |
| `spkt consolidate apply` | Apply consolidation plan |
| `spkt visualize` | Generate interactive HTML graph |
| `spkt export` | Export brain (tar/json/qabot) |
| `spkt import` | Import brain from archive |

### Neuron

| Command | Purpose |
|---------|---------|
| `spkt neuron add "<content>" -t <type> -d <domain>` | Add a neuron |
| `spkt neuron list` | List neurons (filter by type/domain) |
| `spkt neuron inspect <id>` | Neuron detail (content, FSRS state, neighbors, sources) |
| `spkt neuron remove <id>` | Remove a neuron and its synapses |
| `spkt neuron merge <id1> <id2> --into <target>` | Merge neurons |
| `spkt neuron fire <id> -g <grade>` | Record a review (fire a spike) |

### Synapse

| Command | Purpose |
|---------|---------|
| `spkt synapse add <pre> <post> -t <type>` | Create a synapse |
| `spkt synapse remove <pre> <post>` | Remove a synapse |
| `spkt synapse weight <pre> <post> <weight>` | Set synapse weight |
| `spkt synapse list` | List synapses (filter by neuron/type) |

### Source

| Command | Purpose |
|---------|---------|
| `spkt source ingest "<url-or-path>" -d <domain>` | Ingest URL/file/directory |
| `spkt source list` | List sources with neuron counts |
| `spkt source inspect <id>` | Source detail + attached neurons |
| `spkt source update <id>` | Update source metadata |
| `spkt source refresh` | Re-fetch URL sources |

### Domain

| Command | Purpose |
|---------|---------|
| `spkt domain list` | List domains with counts |
| `spkt domain rename <old> <new>` | Rename a domain |
| `spkt domain merge <d1> <d2> --into <target>` | Merge domains |
| `spkt domain audit` | Domain ↔ community alignment analysis |

### Community

| Command | Purpose |
|---------|---------|
| `spkt community detect` | Run Louvain community detection |
| `spkt community list` | Show community assignments |

### Tutor

| Command | Purpose |
|---------|---------|
| `spkt tutor due` | List neurons due for review |
| `spkt tutor quiz` | Interactive flashcard review session |
| `spkt tutor progress` | Learning progress report |

## Grade Scale

| Grade | Meaning | FSRS Rating |
|-------|---------|-------------|
| `miss` | Failed recall | Again |
| `weak` | Uncertain | Hard |
| `fire` | Correct | Good |
| `strong` | Perfect | Easy |

## Synapse Types

| Type | Direction | Use |
|------|-----------|-----|
| `requires` | Directed | A requires understanding B |
| `extends` | Directed | A extends B |
| `contrasts` | Bidirectional | A contrasts with B |
| `relates_to` | Bidirectional | General association |
| `summarizes` | Directed | Community summary → member |

## Typical Workflows

### Add knowledge
```bash
spkt neuron add "<content>" -t concept -d math --json
spkt retrieve "<related query>" --json
spkt synapse add <new-id> <related-id> -t relates_to
```

### Review
```bash
spkt tutor due --json
spkt neuron inspect <id> --json
spkt neuron fire <id> -g fire
```

### Search
```bash
spkt retrieve "query" --json
spkt retrieve "query" --filter domain=math --filter year=2024 --json
```
"""


@skills_app.command(name="install")
def skills_install(
    target: Optional[Path] = typer.Option(None, "--target", "-t", help="Target directory (default: .claude/skills/)"),
) -> None:
    """Install Spikuit skills (SKILL.md) for Agent CLIs.

    Copies skill definitions and agent context into the target directory
    so they can be invoked from Agent CLIs like Claude Code, Cursor, or Codex.
    """
    import importlib.resources

    skills_pkg = importlib.resources.files("spikuit_cli") / "skills"
    skill_names = _discover_skills()

    if target is None:
        target = Path.cwd() / ".claude" / "skills"

    target = Path(target)

    installed = 0
    for name in skill_names:
        src = skills_pkg / name / "SKILL.md"
        if not src.is_file():
            continue

        dest_dir = target / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "SKILL.md"

        content = src.read_text(encoding="utf-8")
        dest_file.write_text(content, encoding="utf-8")
        installed += 1

    # Write agent context file alongside skills
    context_file = target.parent / "SPIKUIT.md"
    context_file.write_text(_generate_agent_context(), encoding="utf-8")

    if installed > 0:
        typer.echo(f"Installed {installed} skill(s) to {target}/")
        for name in skill_names:
            if (target / name / "SKILL.md").exists():
                typer.echo(f"  {_skill_display_name(name)}")
        typer.echo(f"\nAgent context written to {context_file}")
    else:
        typer.echo("No skills found in package.", err=True)
        raise typer.Exit(1)


@skills_app.command(name="list")
def skills_list() -> None:
    """List available Spikuit skills."""
    import importlib.resources

    skills_pkg = importlib.resources.files("spikuit_cli") / "skills"
    skill_names = _discover_skills()

    if not skill_names:
        typer.echo("No skills found.")
        return

    typer.echo("Available skills:")
    for name in skill_names:
        src = skills_pkg / name / "SKILL.md"
        if src.is_file():
            content = src.read_text(encoding="utf-8")
            desc = ""
            in_frontmatter = False
            for line in content.splitlines():
                if line.strip() == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if in_frontmatter and line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()[:80]
                    break
            typer.echo(f"  {_skill_display_name(name):20s} {desc}")


def install_agent_skills(brain_root: Path) -> None:
    """Interactive Agent CLI selection and skills installation."""
    import importlib.resources

    agents = {
        "1": ("Claude Code", ".claude/skills"),
        "2": ("Cursor", ".cursor/skills"),
        "3": ("Codex", ".codex/skills"),
    }

    typer.echo("Which Agent CLI do you use?")
    for key, (name, _) in agents.items():
        typer.echo(f"  {key}) {name}")

    choice = typer.prompt("Select", default="1")
    if choice not in agents:
        typer.echo(f"Invalid choice: {choice}", err=True)
        return

    agent_name, skills_rel = agents[choice]
    target = brain_root / skills_rel

    skills_pkg = importlib.resources.files("spikuit_cli") / "skills"
    skill_names = _discover_skills()

    installed = 0
    for name in skill_names:
        src = skills_pkg / name / "SKILL.md"
        if not src.is_file():
            continue
        dest_dir = target / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8")
        (dest_dir / "SKILL.md").write_text(content, encoding="utf-8")
        installed += 1

    # Write agent context file
    context_file = target.parent / "SPIKUIT.md"
    context_file.write_text(_generate_agent_context(), encoding="utf-8")

    if installed > 0:
        typer.echo(f"\nInstalled {installed} skill(s) for {agent_name} at {target}/")
        for name in skill_names:
            if (target / name / "SKILL.md").exists():
                typer.echo(f"  {_skill_display_name(name)}")
        typer.echo(f"Agent context: {context_file}")
    else:
        typer.echo("No skills installed.", err=True)
