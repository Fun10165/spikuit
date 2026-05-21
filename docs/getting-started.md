# Getting Started

## Installation

```bash
git clone https://github.com/takyone/spikuit.git
cd spikuit
uv sync --package spikuit-cli
```

## Initialize a Brain

A **Brain** is a self-contained knowledge space — like an Obsidian vault
or a git repository. Each Brain has its own knowledge graph, configuration,
and review schedule. You can have multiple Brains for different domains
or projects.

Run `spkt init` to start the interactive wizard:

```
$ spkt init

Brain name [my-project]: math
Configure embeddings? [y/N]: y
  Providers: openai-compat, ollama
  Provider [openai-compat]:
  Base URL [http://localhost:1234/v1]:
  Model [text-embedding-nomic-embed-text-v1.5]:
  Dimension [768]:

--- Summary ---
Brain:    math
Location: /home/user/math/.spikuit/
Embedder: openai-compat
  URL:    http://localhost:1234/v1
  Model:  text-embedding-nomic-embed-text-v1.5
  Dim:    768

Create brain? [Y/n]:

Initialized brain 'math' at /home/user/math/.spikuit/
```

You can also use flags for non-interactive setup:

```bash
spkt init -p openai-compat \
  --base-url http://localhost:1234/v1 \
  --model text-embedding-nomic-embed-text-v1.5
```

This creates:

```
.spikuit/
├── config.toml    # Brain configuration
├── circuit.db     # SQLite database
└── cache/         # Embedding cache
```

Like git, `spkt` auto-discovers `.spikuit/` by walking up from the current
directory. To operate on a different Brain, use `--brain <path>`.

## Add Knowledge

```bash
# Add a concept
spkt neuron add "# Functor\n\nA mapping between categories that preserves structure." \
  -t concept -d math

# Add another
spkt neuron add "# Monad\n\nA monoid in the category of endofunctors." \
  -t concept -d math
```

## Connect Concepts

```bash
# Monad requires understanding Functor
spkt synapse add <monad-id> <functor-id> --type requires

# See the connection
spkt neuron inspect <monad-id>
```

## Review

```bash
# What's due for review?
spkt tutor due

# Review a concept (grade: miss/weak/fire/strong)
spkt neuron fire <neuron-id> --grade fire

# Interactive quiz session
spkt tutor quiz
```

## Search

```bash
# Graph-weighted search
spkt retrieve "category theory"

# Backfill embeddings for semantic search
spkt embed-all
```

## Ingest Sources

```bash
# Ingest a URL
spkt source ingest "https://example.com/article" -d cs --json

# Ingest a directory of files
spkt source ingest ./papers/ -d cs --json
```

## Visualize

```bash
# Generate interactive HTML graph
spkt visualize
```

## Export

```bash
# Full backup
spkt export -o backup.tar.gz

# Portable QABot bundle
spkt export --format qabot -o qa-bundle.db
```

## Grade Scale

| Grade | Meaning |
|-------|---------|
| `miss` | Didn't remember |
| `weak` | Uncertain |
| `fire` | Got it right |
| `strong` | Perfect recall |

## Synapse Types

| Type | Direction | Use |
|------|-----------|-----|
| `requires` | Directed | A requires understanding B |
| `extends` | Directed | A extends B |
| `contrasts` | Bidirectional | A contrasts with B |
| `relates_to` | Bidirectional | General association |
| `summarizes` | Directed | Community summary → member |
