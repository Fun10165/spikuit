"""Brain selection commands: spkt brain {set-default,current}.

The default Brain lets ``spkt`` be run from anywhere — when no
``.spikuit/`` is found by walking up from the current directory, the CLI
falls back to the configured default instead of failing. It is stored in
the user-global config (``~/.config/spikuit/config.toml``), separate from
any per-vault ``.spikuit/config.toml``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from spikuit_core.config import (
    SPIKUIT_DIR,
    find_spikuit_root,
    get_default_brain,
    global_config_path,
    load_config,
    set_default_brain,
)

from ..helpers import _out

brain_app = typer.Typer(help="Select which Brain spkt uses.")


@brain_app.command(name="set-default")
def brain_set_default(
    path: Path = typer.Argument(..., help="Brain root directory (contains .spikuit/)"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Set the default Brain used by spkt when run outside any Brain.

    With a default set, ``spkt`` works from any directory: a local
    ``.spikuit/`` (found by walking up) still wins, but otherwise the
    default is used. Replaces the old ``~/.spikuit`` symlink trick.
    """
    try:
        stored = set_default_brain(path)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    if as_json:
        _out({"default_brain": str(stored)}, use_json=True)
    else:
        typer.echo(f"Default Brain set: {stored}")


@brain_app.command(name="current")
def brain_current(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show which Brain spkt resolves to here, and the configured default."""
    local = find_spikuit_root()
    default = get_default_brain()
    config = load_config()
    resolved = config.root
    has_brain = (resolved / SPIKUIT_DIR).is_dir()

    if local is not None:
        source = "cwd"  # walked up from the current directory
    elif default is not None and (default / SPIKUIT_DIR).is_dir():
        source = "default"
    else:
        source = "fallback"  # ~/ — no Brain found anywhere

    if as_json:
        _out(
            {
                "resolved": str(resolved),
                "source": source,
                "has_brain": has_brain,
                "name": config.name if has_brain else None,
                "default_brain": str(default) if default else None,
                "global_config": str(global_config_path()),
            },
            use_json=True,
        )
        return

    if has_brain:
        typer.echo(f"Resolved Brain: {resolved}  ({config.name})")
        typer.echo(f"  found via:    {source}")
    else:
        typer.echo("Resolved Brain: none")
        typer.echo("  spkt would fall back to ~/ — run 'spkt brain set-default <path>'")

    if default:
        marker = "" if (default / SPIKUIT_DIR).is_dir() else "  [missing .spikuit/]"
        typer.echo(f"Default Brain:  {default}{marker}")
    else:
        typer.echo("Default Brain:  (unset)")
