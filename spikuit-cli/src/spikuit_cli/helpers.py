"""Shared helpers for spkt CLI commands."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from spikuit_core import Circuit, Grade, Neuron
from spikuit_core.config import BrainConfig, load_config
from spikuit_core.embedder import create_embedder
from spikuit_tutor import TutorScheduler, TutorStore, default_overlay_path

if TYPE_CHECKING:
    from fsrs import Card


def _load_brain_config(brain: Path | None = None) -> BrainConfig:
    """Load config from .spikuit/ or use explicit brain root."""
    return load_config(brain)


def _get_circuit(brain: Path | None = None) -> Circuit:
    """Create a Circuit from brain config."""
    config = load_config(brain)
    embedder = create_embedder(
        config.embedder.provider,
        base_url=config.embedder.base_url,
        model=config.embedder.model,
        dimension=config.embedder.dimension,
        api_key=config.embedder.api_key,
        timeout=config.embedder.timeout,
        prefix_style=config.embedder.prefix_style,
    )
    return Circuit(
        db_path=config.db_path,
        embedder=embedder,
        journal_mode=config.database.journal_mode,
    )


def _get_scheduler(circuit: Circuit, brain: Path | None = None) -> TutorScheduler:
    """Build a TutorScheduler over a Circuit and its FSRS overlay store.

    Stage 2 (``tutor-extraction-stage2.md`` §4.7) moved FSRS card state
    out of ``spikuit-core`` into a ``spikuit-tutor``-owned overlay DB.
    The overlay defaults to ``<substrate-stem>.tutor.db`` beside the
    substrate DB (§4.1). The returned scheduler is *unopened*: the
    caller must ``await scheduler.open()`` once the circuit is connected,
    and ``await scheduler.close()`` when done.
    """
    config = load_config(brain)
    store = TutorStore(
        default_overlay_path(config.db_path),
        journal_mode=config.database.journal_mode,
    )
    return TutorScheduler(circuit, store)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _out(data: object, *, use_json: bool) -> None:
    """Output data as JSON or human-readable text."""
    if use_json:
        typer.echo(json.dumps(data, ensure_ascii=False, default=str))
    elif isinstance(data, str):
        typer.echo(data)
    elif isinstance(data, list):
        for item in data:
            typer.echo(item)
    elif isinstance(data, dict):
        for k, v in data.items():
            typer.echo(f"{k}: {v}")


def _extract_title(content: str) -> str:
    """Extract first heading or first line as title."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if line and not line.startswith("---"):
            return line[:60]
    return "(untitled)"


def _neuron_dict(n: Neuron, circuit: Circuit, *, card: "Card | None" = None) -> dict:
    """Serialize a Neuron + its graph state to a dict.

    ``pressure`` is a substrate signal and is always present. The
    ``fsrs`` block is the tutor's overlay card state (Stage 2 §4.7):
    callers holding a scheduler pass the neuron's ``card``;
    substrate-only commands (``neuron list``, ``retrieve``) pass nothing
    and emit no ``fsrs`` block — a never-reviewed neuron has no card
    anyway under the lazy-card model (§4.4).
    """
    pressure = circuit.get_pressure(n.id)
    d: dict = {
        "id": n.id,
        "title": _extract_title(n.content),
        "content": n.content,
        "type": n.type,
        "domain": n.domain,
        "pressure": pressure,
    }
    if card:
        d["fsrs"] = {
            "stability": card.stability,
            "difficulty": card.difficulty,
            "state": card.state.name,
            "due": str(card.due),
        }
    return d


_GRADE_MAP = {
    "miss": Grade.MISS,
    "weak": Grade.WEAK,
    "fire": Grade.FIRE,
    "strong": Grade.STRONG,
}


# -- Git integration --------------------------------------------------------


def _brain_root(brain: Path | None = None) -> Path:
    """Resolve the Brain root directory (parent of .spikuit/)."""
    return _load_brain_config(brain).root


def _is_git_repo(brain: Path | None = None) -> bool:
    """Whether the Brain root has a git repository initialized."""
    root = _brain_root(brain)
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def _git(
    *args: str,
    brain: Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a git command in the Brain root.

    Raises typer.Exit on failure when ``check`` is True.
    """
    root = _brain_root(brain)
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=capture,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        typer.echo(f"git not found on PATH: {e}", err=True)
        raise typer.Exit(1) from e
    if check and result.returncode != 0:
        if capture and result.stderr:
            typer.echo(result.stderr, err=True)
        raise typer.Exit(result.returncode)
    return result


def _git_auto_commit_enabled(brain: Path | None = None) -> bool:
    """Whether the Brain has [git] auto_commit = true (default)."""
    config = _load_brain_config(brain)
    git_cfg = getattr(config, "git", None)
    if git_cfg is None:
        return True
    return bool(getattr(git_cfg, "auto_commit", True))


def _current_branch(brain: Path | None = None) -> str:
    """Return the current git branch name."""
    result = _git("rev-parse", "--abbrev-ref", "HEAD", brain=brain, capture=True)
    return result.stdout.strip()


GITIGNORE_TEMPLATE = """\
# Spikuit Brain — recommended .gitignore
# Track: circuit.db, config.toml
# Ignore: ephemeral cache, lockfiles, exports

.spikuit/cache/
.spikuit/*.lock
.spikuit/*.tmp

# Exports are portable archives — regenerate with `spkt export`
exports/
*.tar.gz
"""
