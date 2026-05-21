"""Config — project-local Brain configuration.

Manages .spikuit/ directory discovery and config.toml parsing.
Walks up from CWD to find .spikuit/ (like .git/).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SPIKUIT_DIR = ".spikuit"
CONFIG_FILE = "config.toml"
DB_FILE = "circuit.db"
CACHE_DIR = "cache"

# User-global config — distinct from a Brain's per-vault .spikuit/config.toml.
# Holds cross-Brain preferences such as the default Brain.
GLOBAL_CONFIG_FILE = "config.toml"

# Default config template
DEFAULT_CONFIG = """\
[brain]
name = "{name}"

[embedder]
# provider: "openai-compat" | "ollama" | "none"
# openai-compat works with LM Studio, Ollama /v1, vLLM, OpenAI, etc.
provider = "none"

# Task-type prefix style for embedding models.
# "nomic"  → "search_document: " / "search_query: "
# "cohere" → "search_document: " / "search_query: "
# "none"   → no prefix (default)
# prefix_style = "none"

# Uncomment and configure for local embeddings (LM Studio):
# provider = "openai-compat"
# base_url = "http://localhost:1234/v1"
# model = "text-embedding-nomic-embed-text-v1.5"
# dimension = 768
# prefix_style = "nomic"

# Uncomment for Ollama native API:
# provider = "ollama"
# base_url = "http://localhost:11434"
# model = "nomic-embed-text"
# dimension = 768
# prefix_style = "nomic"

[database]
# SQLite journal mode.
# "WAL"    → fastest on a single machine (default).
# "DELETE" → single-file database, no -wal/-shm sidecars. Use this when the
#            Brain vault is synced across machines (Syncthing, Dropbox, ...):
#            WAL sidecars are per-machine and syncing them risks corruption.
# journal_mode = "WAL"
"""


@dataclass
class EmbedderConfig:
    """Embedder configuration parsed from ``config.toml``.

    Attributes:
        provider: ``"openai-compat"``, ``"ollama"``, or ``"none"``.
        base_url: API base URL.
        model: Model identifier.
        dimension: Embedding vector dimension.
        api_key: Bearer token (OpenAI-compat only).
        timeout: HTTP request timeout in seconds.
    """

    provider: str = "none"
    base_url: str = ""
    model: str = ""
    dimension: int = 768
    api_key: str = "not-needed"
    timeout: float = 30.0
    prefix_style: str = "none"
    max_searchable_chars: int = 500


@dataclass
class DatabaseConfig:
    """SQLite storage options parsed from ``config.toml``.

    Attributes:
        journal_mode: SQLite journal mode. ``"WAL"`` (default) is fastest
            on a single machine. ``"DELETE"`` keeps the whole database in
            one file with no ``-wal`` / ``-shm`` sidecars — required for a
            Brain vault synced across machines (e.g. via Syncthing), where
            the per-machine WAL sidecars cannot safely travel.
    """

    journal_mode: str = "WAL"


@dataclass
class GitConfig:
    """Git-backed Brain versioning options.

    Attributes:
        auto_commit: When True (default), agents are expected to commit
            Brain mutations and enforce the branch policy. Set False to
            opt out and manage git yourself.
    """

    auto_commit: bool = True


@dataclass
class BrainConfig:
    """Full Brain configuration — parsed from ``.spikuit/config.toml``.

    Attributes:
        name: Brain name (defaults to directory name).
        root: Directory containing ``.spikuit/``.
        embedder: Embedder settings.
        database: SQLite storage settings.
        git: Git versioning settings.
    """

    name: str = "default"
    root: Path = field(default_factory=lambda: Path.cwd())
    embedder: EmbedderConfig = field(default_factory=EmbedderConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    git: GitConfig = field(default_factory=GitConfig)

    @property
    def spikuit_dir(self) -> Path:
        """Path to the ``.spikuit/`` directory."""
        return self.root / SPIKUIT_DIR

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self.spikuit_dir / DB_FILE

    @property
    def config_path(self) -> Path:
        """Path to ``config.toml``."""
        return self.spikuit_dir / CONFIG_FILE

    @property
    def cache_path(self) -> Path:
        """Path to the cache directory."""
        return self.spikuit_dir / CACHE_DIR


def find_spikuit_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` to find a directory containing ``.spikuit/``.

    Behaves like ``git``'s root discovery — walks parent directories
    until ``.spikuit/`` is found or the filesystem root is reached.

    Args:
        start: Starting directory (defaults to CWD).

    Returns:
        The directory containing ``.spikuit/``, or ``None`` if not found.
    """
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / SPIKUIT_DIR).is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def global_config_dir() -> Path:
    """Directory holding the user-global Spikuit config.

    Honors ``XDG_CONFIG_HOME``; defaults to ``~/.config/spikuit``.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "spikuit"


def global_config_path() -> Path:
    """Path to the user-global ``config.toml``."""
    return global_config_dir() / GLOBAL_CONFIG_FILE


def get_default_brain() -> Path | None:
    """Read the configured default Brain root, if any.

    The default Brain is what ``spkt`` falls back to when no ``.spikuit/``
    is found by walking up from the current directory — it lets the CLI
    be run from anywhere. Set it with ``spkt brain set-default``.

    The path is returned verbatim (``~`` expanded) and is *not* validated
    here; callers that need a usable Brain should check that
    ``<path>/.spikuit/`` exists.

    Returns:
        The configured default Brain root, or ``None`` if unset.
    """
    path = global_config_path()
    if not path.exists():
        return None
    with open(path, "rb") as f:
        data = tomllib.load(f)
    raw = data.get("default_brain")
    if not raw:
        return None
    return Path(raw).expanduser()


def set_default_brain(root: Path) -> Path:
    """Persist ``root`` as the user-global default Brain.

    Writes ``~/.config/spikuit/config.toml`` (honoring ``XDG_CONFIG_HOME``).

    Args:
        root: Brain root directory — must contain a ``.spikuit/``.

    Returns:
        The resolved absolute path that was stored.

    Raises:
        FileNotFoundError: If ``root`` has no ``.spikuit/`` directory.
    """
    resolved = root.expanduser().resolve()
    if not (resolved / SPIKUIT_DIR).is_dir():
        raise FileNotFoundError(f"no {SPIKUIT_DIR}/ directory found at {resolved}")

    cfg_dir = global_config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / GLOBAL_CONFIG_FILE).write_text(
        "# Spikuit user-global config.\n"
        "#\n"
        "# default_brain: the Brain `spkt` uses when no .spikuit/ is found by\n"
        "# walking up from the current directory. Lets `spkt` run from anywhere.\n"
        "# Manage it with `spkt brain set-default` / `spkt brain current`.\n"
        f'default_brain = "{resolved}"\n'
    )
    return resolved


def load_config(root: Path | None = None) -> BrainConfig:
    """Load BrainConfig from .spikuit/config.toml.

    When ``root`` is None, the Brain is discovered in this order:

    1. Walk up from CWD for a ``.spikuit/`` directory (like ``git``).
    2. The user-global default Brain (``spkt brain set-default``).
    3. ``~/`` as a last-resort fallback (yields an empty BrainConfig).
    """
    if root is None:
        found = find_spikuit_root()
        if found is not None:
            root = found
        else:
            default = get_default_brain()
            if default is not None and (default / SPIKUIT_DIR).is_dir():
                root = default
            else:
                # Last-resort fallback — no Brain found anywhere.
                root = Path.home()

    config_path = root / SPIKUIT_DIR / CONFIG_FILE
    config = BrainConfig(root=root)

    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        _apply_config(config, data)

    return config


def init_brain(
    path: Path | None = None,
    *,
    name: str | None = None,
    embedder_provider: str = "none",
    embedder_base_url: str = "",
    embedder_model: str = "",
    embedder_dimension: int = 768,
    embedder_prefix_style: str = "none",
) -> BrainConfig:
    """Initialize a new ``.spikuit/`` directory with ``config.toml``.

    Creates the directory structure and writes a config file.
    Equivalent to ``spkt init``.

    Args:
        path: Target directory (defaults to CWD).
        name: Brain name (defaults to directory name).
        embedder_provider: ``"openai-compat"``, ``"ollama"``, or ``"none"``.
        embedder_base_url: API base URL for embedder.
        embedder_model: Model identifier for embedder.
        embedder_dimension: Embedding vector dimension.

    Returns:
        The BrainConfig for the initialized brain.

    Raises:
        FileExistsError: If ``.spikuit/`` already exists.
    """
    root = (path or Path.cwd()).resolve()
    spikuit_dir = root / SPIKUIT_DIR

    if spikuit_dir.exists():
        raise FileExistsError(f".spikuit/ already exists at {root}")

    brain_name = name or root.name

    # Create directory structure
    spikuit_dir.mkdir(parents=True)
    (spikuit_dir / CACHE_DIR).mkdir()

    # Write config
    config_content = DEFAULT_CONFIG.format(name=brain_name)

    # Override defaults if embedder settings provided
    if embedder_provider != "none":
        config_content = _build_config(
            brain_name, embedder_provider, embedder_base_url,
            embedder_model, embedder_dimension, embedder_prefix_style,
        )

    (spikuit_dir / CONFIG_FILE).write_text(config_content)

    return load_config(root)


def _apply_config(config: BrainConfig, data: dict[str, Any]) -> None:
    """Apply parsed TOML data to a BrainConfig."""
    brain = data.get("brain", {})
    if "name" in brain:
        config.name = brain["name"]

    emb = data.get("embedder", {})
    if emb:
        config.embedder = EmbedderConfig(
            provider=emb.get("provider", "none"),
            base_url=emb.get("base_url", ""),
            model=emb.get("model", ""),
            dimension=emb.get("dimension", 768),
            api_key=emb.get("api_key", "not-needed"),
            timeout=emb.get("timeout", 30.0),
            prefix_style=emb.get("prefix_style", "none"),
            max_searchable_chars=emb.get("max_searchable_chars", 500),
        )

    database = data.get("database", {})
    if database:
        config.database = DatabaseConfig(
            journal_mode=database.get("journal_mode", "WAL"),
        )

    git = data.get("git", {})
    if git:
        config.git = GitConfig(
            auto_commit=bool(git.get("auto_commit", True)),
        )


def _build_config(
    name: str,
    provider: str,
    base_url: str,
    model: str,
    dimension: int,
    prefix_style: str = "none",
) -> str:
    """Build a config.toml string with active embedder settings."""
    lines = [
        f'[brain]',
        f'name = "{name}"',
        f'',
        f'[embedder]',
        f'provider = "{provider}"',
    ]
    if base_url:
        lines.append(f'base_url = "{base_url}"')
    if model:
        lines.append(f'model = "{model}"')
    lines.append(f'dimension = {dimension}')
    if prefix_style != "none":
        lines.append(f'prefix_style = "{prefix_style}"')
    return "\n".join(lines) + "\n"
