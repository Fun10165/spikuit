# Spikuit — Development Guide

## Overview

Spikuit (spike + circuit) is a neural knowledge graph with spaced repetition.
Core engine is LLM-independent. CLI (`spkt`) is the primary interface.

## Repository Structure

```
spikuit/
├── spikuit-core/      # Pure engine (FSRS + NetworkX + APPNP + STDP + LIF)
│   ├── src/spikuit_core/
│   │   ├── models.py      # Neuron, Synapse, Spike, Plasticity (msgspec)
│   │   ├── circuit.py     # Public API: fire, retrieve, ensemble, due
│   │   ├── propagation.py # APPNP spreading + STDP + LIF decay
│   │   └── db.py          # Async SQLite persistence
│   └── tests/             # pytest-asyncio tests
├── spikuit-cli/       # spkt command (Typer)
│   └── src/spikuit_cli/
│       ├── main.py        # Root commands + deprecation wrappers
│       ├── helpers.py     # Shared helpers (_get_circuit, _out, etc.)
│       └── commands/      # Resource-oriented subcommands
│           ├── neuron.py  # spkt neuron {add,list,inspect,remove,merge,due,fire}
│           ├── synapse.py # spkt synapse {add,remove,weight,list}
│           ├── source.py  # spkt source {learn,list,inspect,update,refresh}
│           ├── domain.py  # spkt domain {list,rename,merge}
│           ├── community.py # spkt community {detect,list}
│           └── skills.py  # spkt skills {install,list}
└── spikuit-agents/    # Future: SDK / adapters
```

## Development Commands

```bash
# Run all tests
uv run --package spikuit-core pytest spikuit-core/tests/ -v

# Run CLI
uv run --package spikuit-cli spkt --help

# Run specific test file
uv run --package spikuit-core pytest spikuit-core/tests/test_propagation.py -v
```

## Conventions

- **Models**: msgspec.Struct with type annotations. No dataclasses.
- **Async**: All DB operations are async (aiosqlite). Circuit methods are async.
- **TDD**: Write tests first, then implement. Tests use pytest-asyncio.
- **Naming**: Neuroscience-inspired (Neuron, Synapse, Spike, Circuit, Plasticity).
- **Language**: Code, comments, docs, skills — all in English.
- **Responses**: Match the user's language when speaking to them.

## Brain Setup

A Brain is a `.spikuit/` directory — like an Obsidian vault or `.git/`.
Each Brain has its own graph, config, and review schedule. `spkt` auto-discovers
`.spikuit/` by walking up from CWD. Use `--brain <path>` to target another Brain.

By default `spkt init` also runs `git init` at the Brain root and writes a
`.gitignore`. The agent uses git for version control of Brain state — see
"Brain Version Control" below.

```bash
spkt init                              # Interactive wizard
spkt init -p openai-compat \           # Non-interactive with LM Studio
  --base-url http://localhost:1234/v1 \
  --model text-embedding-nomic-embed-text-v1.5
spkt config                            # Show current brain config
spkt embed-all                         # Backfill embeddings for existing neurons
```

Config lives in `.spikuit/config.toml`.

## Brain Version Control (mandatory branching for batch ops)

Spikuit uses git for Brain versioning — no in-engine snapshots or transactions.
The engine stays simple; the policy lives in this runbook so agents enforce it
consistently.

### The rule

**Any batch operation MUST run on a feature branch.** The agent is not
permitted to commit batches directly to `main`. The user can always interrupt
or reject before the merge — that's the whole point.

| Operation | Branch required? |
|---|---|
| `spkt source ingest` (any input — single file or batch) | **yes** |
| `spkt consolidate apply` | **yes** |
| `spkt domain rename` / `domain merge` | **yes** |
| `spkt neuron merge` | **yes** |
| `spkt neuron remove` with `--ingest-tag` or N>1 | **yes** |
| `spkt neuron add` (single) | no — direct to main |
| `spkt neuron fire` (single) | no — direct to main |
| `spkt neuron remove <id>` (single) | no — direct to main |

### The flow

```bash
# 1. Cut a branch
spkt branch start <tag>          # e.g. papers-2026-04, monad-deep-dive

# 2. Do the batch work (commits land on the branch, NOT on main)
spkt source ingest ./papers/ -d math --json
spkt neuron add "..." ...
git -C <brain-root> commit -m "ingest(<tag>): N neurons from <source-summary>"

# 3. Show the user a summary, ask to confirm
#    "12 neurons added, 4 sources, 8 synapses on ingest/<tag>. Merge to main?"

# 4a. User approves → fast-forward merge
spkt branch finish

# 4b. User rejects → discard branch, main untouched
spkt branch abandon
```

### Commit message conventions

Use these prefixes so `spkt history --grep` and `spkt undo --ingest-tag` work:

```
ingest(<tag>): <N> neurons from <source-summary>
consolidate: <summary of merges/splits>
review(<YYYY-MM-DD>): <N> neurons fired (<correct>/<total>)
manual: <user-supplied summary>
```

### Undo

If the user says "戻したい / undo / take it back":

```bash
spkt history -n 20                   # show recent Brain commits
spkt undo                            # revert HEAD (with confirmation)
spkt undo --ingest-tag <tag>         # revert all commits matching ingest(<tag>)
spkt undo --to <sha>                 # revert everything since <sha>
```

These are `git revert` wrappers — history is preserved, never rewritten.

### When git is not present

If `spkt history` returns an error, the Brain has no `.git/`. Either the user
ran `spkt init --no-git`, or the Brain pre-dates this feature. Don't try to
auto-init — ask the user whether they want git versioning enabled.

## spkt CLI

All commands support `--json` for machine-readable output and `--brain` to target a specific Brain.

### Root commands

| Command | Purpose |
|---------|---------|
| `spkt init` | Initialize .spikuit/ brain |
| `spkt config` | Show brain configuration |
| `spkt embed-all` | Backfill embeddings |
| `spkt retrieve` | Graph-weighted search |
| `spkt stats` | Circuit statistics |
| `spkt diagnose` | Brain health diagnostics |
| `spkt manual` | Auto-generated user guide |
| `spkt consolidate` | Sleep-inspired knowledge consolidation (dry-run) |
| `spkt consolidate apply` | Apply consolidation plan |
| `spkt visualize` | Interactive graph visualization (HTML) |
| `spkt export` | Export brain (tar/json/qabot) |
| `spkt import` | Import brain from archive |

### Resource subcommands

| Command | Purpose |
|---------|---------|
| `spkt neuron add` | Add a Neuron |
| `spkt neuron list` | List neurons (filter by type/domain) |
| `spkt neuron inspect` | Neuron detail (content, FSRS, neighbors) |
| `spkt neuron remove` | Remove a neuron and its synapses |
| `spkt neuron merge` | Merge neurons (content + synapses + sources) |
| `spkt neuron fire` | Fire a Spike (FSRS + APPNP + STDP) |
| `spkt synapse add` | Create a Synapse |
| `spkt synapse remove` | Remove a Synapse |
| `spkt synapse weight` | Set synapse weight |
| `spkt synapse list` | List synapses (filter by neuron/type) |
| `spkt source ingest` | Ingest URL/file/directory |
| `spkt source list` | List sources with neuron counts |
| `spkt source inspect` | Source detail + attached neurons |
| `spkt source update` | Update source metadata |
| `spkt source refresh` | Re-fetch URL sources |
| `spkt domain list` | List domains with counts |
| `spkt domain rename` | Rename a domain |
| `spkt domain merge` | Merge domains |
| `spkt domain audit` | Domain ↔ community alignment analysis |
| `spkt community detect` | Run community detection |
| `spkt community list` | Show community assignments |
| `spkt tutor due` | List neurons due for review |
| `spkt tutor quiz` | Interactive flashcard review session |
| `spkt tutor progress` | Learning progress report |
| `spkt brain set-default` | Set the fallback Brain used outside any `.spikuit/` |
| `spkt brain current` | Show which Brain resolves here + the default |
| `spkt skills install` | Install SKILL.md for Agent CLIs |
| `spkt skills list` | List available skills |
| `spkt skills extractor list` | List ingestion extractors (system + brain tier) |
| `spkt skills extractor status` | Check extractor runtime requirements |
| `spkt skills extractor show <name>` | Print extractor manifest + SKILL.md |
| `spkt skills extractor fork <name>` | Copy system extractor → brain (shadcn-style) |
| `spkt skills extractor add <path>` | Install external extractor directory into brain |
| `spkt skills extractor remove <name>` | Delete brain-local extractor |
| `spkt skills extractor refresh` | Regenerate brain `_registry.toml` |

Old flat commands (`spkt add`, `spkt fire`, etc.) still work with deprecation warnings. Use the resource-oriented form above.

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

## Architecture

### Core layer (LLM-free)
- **Circuit**: Knowledge graph engine (FSRS + NetworkX + propagation + sqlite-vec)
- **Embedder**: Pluggable text embedding (OpenAICompat, Ollama, Null). Auto-embeds on add/update.
- **Scaffold**: ZPD-inspired support levels (FULL/GUIDED/MINIMAL/NONE) from FSRS state + graph neighbors
- **Flashcard**: Self-grade quiz, no LLM required

### Session layer (LLM-powered)
- **QABotSession**: RAG chat — LLM generates answers from retrieval results (negative feedback, accept, dedup, persistent/ephemeral)
- **LearnSession**: Knowledge curation — add neurons, discover relations, merge duplicates through dialogue
- **TutorSession**: 1-on-1 tutoring — scaffolded teaching, hint progression, gap detection, error explanation

### Quiz (evaluation tools used by Sessions)
- **Flashcard** (core): Self-grade, no LLM
- **AutoQuiz**: LLM-generated questions, programmatic grading
- **1 Quiz : N Neurons**: QuizRequest has primary + supporting neurons, QuizResult has per-neuron grades

## Roadmap & Planning

Plans are persisted as **GitHub Milestones + Issues**, not local files.

- Each version milestone contains all issues for that release
- Issues have labels (`core`, `cli`, `agent`, `docs`) and dependency notes
- Check current roadmap: `gh issue list --milestone "<milestone>"`
- When planning a new version, create a Milestone and break it into Issues
- Close issues as work is completed; Milestone progress bar tracks overall status

This ensures plans survive across sessions and are always queryable via `gh`.

## Key Algorithms

- **APPNP**: Personalized PageRank propagation. Activation flows along outgoing edges.
- **STDP**: Edge weights update based on co-fire timing (tau_stdp = 7 days).
- **LIF**: Pressure accumulates from neighbor fires, decays exponentially (tau_m = 14 days).
- **FSRS**: Per-neuron spaced repetition. Propagation only affects pressure, never stability/difficulty.
