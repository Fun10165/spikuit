"""Spikuit Core — Knowledge Graph + Spreading Activation substrate.

Two install profiles:

    pip install spikuit-core           # minimal: QABot client only
    pip install spikuit-core[engine]   # full: Circuit engine + Sessions

The minimal install ships embedder + QABot (read-only retrieval over
exported Brain bundles) with only `httpx` and `numpy` as dependencies.
The `[engine]` extras pull `networkx`, `aiosqlite`, and `sqlite-vec`
for the live Brain engine. As of Stage 2 the substrate owns no learner
model — FSRS scheduling lives wholly in ``spikuit-tutor``.

Engine symbols (`Circuit`, `Neuron`, etc.) are loaded lazily via PEP 562
`__getattr__`. Importing them without the `[engine]` extras raises a
helpful `ImportError` pointing at the install command.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

try:
    __version__ = version("spikuit-core")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0+unknown"

# -- Always available (lightweight) ---------------------------------------

from .config import BrainConfig, EmbedderConfig, find_spikuit_root
from .embedder import (
    Embedder,
    EmbeddingType,
    ModelSpec,
    NullEmbedder,
    OllamaEmbedder,
    OpenAICompatEmbedder,
    create_embedder,
)
from .rag import EmbedderConfigError, EmbedderSpec, QABot, RetrievalHit

# -- Engine symbols (lazy) ------------------------------------------------

# (export name) -> (submodule, attribute)
_ENGINE_SYMBOLS: dict[str, tuple[str, str]] = {
    # circuit
    "Circuit": ("circuit", "Circuit"),
    "ReadOnlyError": ("circuit", "ReadOnlyError"),
    "RetrievalSignals": ("circuit", "RetrievalSignals"),
    # config helpers that touch the engine
    "init_brain": ("config", "init_brain"),
    "load_config": ("config", "load_config"),
    # models
    "Grade": ("models", "Grade"),
    "Neuron": ("models", "Neuron"),
    "Plasticity": ("models", "Plasticity"),
    "QuizItem": ("models", "QuizItem"),
    "QuizItemRole": ("models", "QuizItemRole"),
    "QuizRequest": ("models", "QuizRequest"),
    "QuizResult": ("models", "QuizResult"),
    "Source": ("models", "Source"),
    "Spike": ("models", "Spike"),
    "Synapse": ("models", "Synapse"),
    "SynapseConfidence": ("models", "SynapseConfidence"),
    "SynapseType": ("models", "SynapseType"),
    "strip_frontmatter": ("models", "strip_frontmatter"),
    # session
    "IngestSession": ("session", "IngestSession"),
    "QABotSession": ("session", "QABotSession"),
    "Session": ("session", "Session"),
}


# Deprecated alias → canonical name. Removed in v1.0.
_DEPRECATED_ALIASES: dict[str, str] = {
    "LearnSession": "IngestSession",
}


def __getattr__(name: str) -> Any:
    if name in _DEPRECATED_ALIASES:
        import warnings

        canonical = _DEPRECATED_ALIASES[name]
        warnings.warn(
            f"spikuit_core.{name} is deprecated; use spikuit_core.{canonical} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return __getattr__(canonical)
    if name in _ENGINE_SYMBOLS:
        from importlib import import_module

        module_name, attr_name = _ENGINE_SYMBOLS[name]
        try:
            mod = import_module(f".{module_name}", __name__)
        except ImportError as e:
            raise ImportError(
                f"spikuit_core.{name} requires the engine extras.\n"
                f"  Install with: pip install spikuit-core[engine]\n"
                f"  (missing module: {e.name})"
            ) from e
        value = getattr(mod, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'spikuit_core' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_ENGINE_SYMBOLS))


# Static type checkers and IDEs see these names; runtime gets them via __getattr__.
if TYPE_CHECKING:
    from .circuit import Circuit, ReadOnlyError, RetrievalSignals
    from .config import init_brain, load_config
    from .models import (
        Grade,
        Neuron,
        Plasticity,
        QuizItem,
        QuizItemRole,
        QuizRequest,
        QuizResult,
        Source,
        Spike,
        Synapse,
        SynapseConfidence,
        SynapseType,
        strip_frontmatter,
    )
    from .session import IngestSession, QABotSession, Session


__all__ = [
    # Always available
    "BrainConfig",
    "Embedder",
    "EmbedderConfig",
    "EmbedderConfigError",
    "EmbedderSpec",
    "EmbeddingType",
    "ModelSpec",
    "NullEmbedder",
    "OllamaEmbedder",
    "OpenAICompatEmbedder",
    "QABot",
    "RetrievalHit",
    "create_embedder",
    "find_spikuit_root",
    # Engine (lazy)
    *sorted(_ENGINE_SYMBOLS.keys()),
]
