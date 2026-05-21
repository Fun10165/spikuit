"""Command modules for the spkt CLI."""

from .brain import brain_app
from .community import community_app
from .domain import domain_app
from .extractor import extractor_app
from .git import branch_app, history_app, undo_cmd
from .neuron import neuron_app
from .skills import skills_app
from .source import source_app
from .synapse import synapse_app

skills_app.add_typer(extractor_app, name="extractor")

__all__ = [
    "brain_app",
    "branch_app",
    "community_app",
    "domain_app",
    "extractor_app",
    "history_app",
    "neuron_app",
    "skills_app",
    "source_app",
    "synapse_app",
    "undo_cmd",
]
