# Spikuit

[English](README.md) | [日本語](docs/index.ja.md)

**A knowledge base that gets smarter the more you use it.**

<p align="center">
  <a href="https://pypi.org/project/spikuit/"><img src="https://img.shields.io/pypi/v/spikuit.svg?label=spikuit" alt="spikuit on PyPI"></a>
  <a href="https://pypi.org/project/spikuit-core/"><img src="https://img.shields.io/pypi/v/spikuit-core.svg?label=spikuit-core" alt="spikuit-core on PyPI"></a>
  <a href="https://pypi.org/project/spikuit/"><img src="https://img.shields.io/pypi/pyversions/spikuit.svg" alt="Supported Python versions"></a>
  <a href="https://github.com/takyone/spikuit/blob/main/LICENSE"><img src="https://img.shields.io/github/license/takyone/spikuit.svg" alt="License"></a>
  <a href="https://github.com/takyone/spikuit/actions/workflows/publish.yml"><img src="https://img.shields.io/github/actions/workflow/status/takyone/spikuit/publish.yml?label=publish" alt="Publish status"></a>
</p>

**Documentation**: <https://takyone.github.io/spikuit/>

**Source Code**: <https://github.com/takyone/spikuit>

> ⚠️ **Pre-1.0 / under active development.** Spikuit is moving fast toward
> v1.0.0 (Daily Use Ready). Expect frequent breaking changes to the CLI,
> data schema, and Python API until then. Pin exact versions and read the
> release notes before upgrading.

---

## What is Spikuit?

Spikuit (spike + circuit, pronounced /spaɪ.kɪt/) is a personal knowledge system
built around one idea: **your knowledge base should learn from you, not just store things.**

Every time you search, review, or ask a question, Spikuit quietly adapts —
boosting what's useful, connecting related ideas, and surfacing what
you're about to forget.

It works as:

- **A self-improving knowledge base** — search quality gets better through usage, not re-indexing
- **A study partner** — an AI tutor that teaches, quizzes, and coaches based on what you actually know
- **An agent's brain** — a knowledge graph that AI agents can read, write, and learn from

### What makes it different?

| | Anki | Obsidian + SRS | Spikuit |
|---|---|---|---|
| Scheduling | Per-card | Per-note | Per-concept, connected |
| Knowledge structure | Flat deck | Manual links | Emergent graph (no up-front taxonomy) |
| Tagging / domain | Required | Manual, up-front | Optional, filled in later from structure |
| Search | Keyword | Keyword + tags | Semantic + graph-weighted |
| Retrieval quality | Static | Static | Improves with usage |
| AI integration | Limited | Plugins | Built-in (agent-native) |

Spikuit doesn't replace these tools — it explores what becomes possible when
you combine a knowledge graph, spaced repetition, and AI agents into one system.

### Structure emerges

You do not pick a folder tree, tag scheme, or taxonomy before you start.
Drop Neurons in with or without a domain label; Spikuit discovers clusters
from the Synapse structure itself. When a blank domain has enough evidence,
`spkt domain audit` fills it in — with your approval on anything ambiguous.

This matters because curation is where knowledge bases usually fail: the
cost of keeping taxonomy consistent grows faster than the value of having
one. Spikuit keeps that cost sub-linear by letting structure self-assemble,
and surfacing disagreements only when they are load-bearing.

For the full picture, see [Emergent Structure](docs/appendix/emergent-structure.md)
and the [Cognitive Retrieval model](docs/appendix/cognitive-retrieval.md).

## Quick Start

### 1. Install

```bash
pip install spikuit
```

### 2. Create a Brain

A "Brain" is Spikuit's workspace — like a `.git/` directory for your knowledge.
Run `spkt init` where you want to set one up:

```bash
mkdir my-brain && cd my-brain
spkt init
```

The interactive wizard will ask about embedding settings. If you're just
trying things out, choose "none" for embeddings — you can configure them later.

### 3. Add some knowledge

```bash
# Add a concept
spkt neuron add "# Ownership in Rust\n\nEach value has exactly one owner. When the owner goes out of scope, the value is dropped." \
  -t concept -d rust

# Add from a URL
spkt source ingest "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html" -d rust

# Connect related concepts
spkt synapse add <id-1> <id-2> -t relates_to
```

### 4. Set up Agent CLI skills (recommended)

Spikuit's interactive skills — tutoring, knowledge curation, and Q&A —
run inside **Agent CLIs** like [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
Cursor, or Codex. To use them, install the skill definitions:

```bash
spkt skills install                    # defaults to .claude/skills/
spkt skills install -t .cursor/skills  # or specify your agent
```

This copies the skill files (`SKILL.md`) and an agent context file
(`SPIKUIT.md`) that gives the agent a complete command reference.

### 5. Start using it

**From your Agent CLI:**

```
You: /spkt-ingest
     I'm studying category theory. A Functor maps between categories
     preserving structure. A Monad is a monoid in the category of endofunctors.

Agent: Added 2 neurons, 1 synapse (Monad --requires--> Functor).

You: /spkt-qabot
     What's the relationship between Functors and Monads?

Agent: A Monad is built on top of a Functor...
       Sources: n-abc123 (Functor), n-def456 (Monad)

You: /spkt-tutor

Tutor: Let's start with Functor — it's a prerequisite for Monad.
       [teaches, quizzes, gives feedback]

You: /spkt-curator

Curator: Your "math" domain spans 2 communities (algebra vs. analysis).
         Split into sub-domains? [Y/n]
```

**Or use `spkt` commands directly:**

```bash
spkt retrieve "ownership borrow"           # search your knowledge graph
spkt neuron due                            # what needs reviewing?
spkt neuron fire <id> -g fire              # record a review
spkt diagnose                              # brain health check
spkt consolidate                           # optimize graph structure
spkt visualize                             # interactive HTML graph
```

All commands support `--json` for machine-readable output.

## Use Cases

### /spkt-ingest + /spkt-qabot : Self-improving RAG

Feed sources into your brain, then query it. Retrieval quality improves
with every conversation — no re-indexing needed.

```
You: /spkt-ingest
     Here's an article on attention mechanisms: https://arxiv.org/abs/1706.03762

Agent: Added 8 neurons (Multi-Head Attention, Scaled Dot-Product, ...).
       6 synapses created, source linked for citation.

You: /spkt-qabot
     How does multi-head attention differ from single-head?

Agent: Multi-head attention runs multiple attention functions in parallel,
       each with different learned projections...

       Sources:
       - [Attention Is All You Need](https://arxiv.org/abs/1706.03762) (via n-a1b2c3)

You: What about computational cost?

Agent: [prior results auto-penalized, new neurons retrieved]
```

### /spkt-ingest + /spkt-tutor : AI study partner

Build a knowledge graph from your study material, then let an AI tutor
teach, quiz, and coach you based on what you actually know.

```
You: /spkt-ingest
     I'm studying category theory. Key concepts:
     - A Functor maps between categories preserving structure
     - A Natural Transformation is a morphism between functors
     - A Monad is a monoid in the category of endofunctors

Agent: Added 3 neurons, 2 synapses (Monad/NatTrans --requires--> Functor).

You: /spkt-tutor

Tutor: You have 3 new concepts. Let's start with Functor —
       it's a prerequisite for the other two.
       [teaches, then quizzes]

You: It's like... a mapping that keeps the structure?

Tutor: Right direction, but incomplete. A functor maps both objects
       AND morphisms, and must preserve composition and identity.
       Can you give an example of a functor between two concrete categories?
```

## How It Works

Spikuit organizes knowledge as a **graph** — concepts are nodes,
relationships are edges. When you interact with the graph, three
things happen automatically:

1. **Smart scheduling** — each concept has its own review timing based on
   how well you know it (powered by [FSRS](https://github.com/open-spaced-repetition/fsrs4anki))
2. **Activation spreading** — reviewing one concept nudges related concepts
   closer to their review time. Connections that are used together get stronger.
3. **Search optimization** — results are ranked by relevance × how well you know
   each concept × how central it is in your graph. Feedback from conversations
   continuously improves ranking.

For the technical details behind these mechanisms, see
[Appendix: Algorithms](docs/appendix.md).

## Documentation

- [Getting Started](docs/getting-started.md) — install, init, first commands
- [How to Use](docs/how-to-use.md) — use cases, agent skills, Python API
- [Concepts](docs/concepts.md) — brain, graph model, how things connect
- [CLI Reference](docs/cli.md) — all `spkt` commands
- [Appendix: Algorithms](docs/appendix.md) — FSRS, graph propagation, technical details
- [API Reference](https://takyone.github.io/spikuit/reference/) — Python API docs

## Architecture

```
spikuit-core/     # Pure engine (no LLM dependency)
spikuit-cli/      # spkt command
spikuit-agents/   # Agent skills and adapters
```

The core engine is LLM-independent — `spkt` commands work standalone.
Agent skills (`/spkt-tutor`, `/spkt-ingest`, `/spkt-qabot`, `/spkt-curator`)
add LLM-powered interactions on top, designed for Agent CLIs like Claude Code.

## Development

```bash
git clone https://github.com/takyone/spikuit.git
cd spikuit
uv sync --package spikuit-core --extra dev
uv run --package spikuit-core pytest spikuit-core/tests/ -v
```

## License

Apache-2.0
