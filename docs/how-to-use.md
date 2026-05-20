# How to Use

Use-case-driven guide. For the full command list, see [CLI Reference](cli.md).
For Python API details, see [API Reference](reference/index.md).

## CLI Recipes

### Add Knowledge

```bash
# Simple concept
spkt neuron add "# Functor\n\nA mapping between categories." -t concept -d math

# With frontmatter
spkt neuron add "---
type: concept
domain: french
---
# Subjonctif
Used for doubt, emotion, necessity."

# From a file
cat notes.md | spkt neuron add -t note -d physics
```

### Connect Concepts

```bash
# "Monad requires Functor"
spkt synapse add <monad-id> <functor-id> -t requires

# "HTTP contrasts gRPC" (creates edges in both directions)
spkt synapse add <http-id> <grpc-id> -t contrasts
```

### Review (Flashcard)

```bash
# What's due?
spkt neuron due

# Interactive flashcard session (Textual TUI)
# Keys: Space=flip, 1-4=grade, n=note, q=quit
spkt quiz

# Agent-facing: batch-dump all due quiz payloads
spkt quiz --json

# Manual fire (after external review)
spkt neuron fire <neuron-id> -g fire
```

### Search & Explore

```bash
# Graph-weighted search (keyword + semantic + memory strength + centrality)
spkt retrieve "functor"

# List by type/domain
spkt neuron list -t concept -d math

# Inspect a neuron (review state, neighbors)
spkt neuron inspect <neuron-id>

# Circuit statistics
spkt stats
```

### Ingest a Directory

```bash
# Ingest all text files with metadata
spkt source ingest ./papers/ -d cs --json

# With a metadata.jsonl sidecar
echo '{"file_name": "paper1.md", "filterable": {"year": "2024"}, "searchable": {"abstract": "..."}}' > papers/metadata.jsonl
spkt source ingest ./papers/ -d cs --json
```

### Filtered Retrieval

```bash
# Filter by source metadata
spkt retrieve "attention mechanism" --filter year=2017

# Combine multiple filters (AND logic)
spkt retrieve "GNN" --filter domain=cs --filter venue=NeurIPS

# Discover available filter keys
spkt neuron list --meta-keys --json
spkt neuron list --meta-values year --json
spkt domain list --json
```

### Source Management

```bash
# List all sources
spkt source list --json

# Inspect a source (details + attached neurons)
spkt source inspect <source-id> --json

# Fix a wrong URL
spkt source update <source-id> --url "https://correct-url.com"

# Rename or merge domains
spkt domain rename ml machine-learning
spkt domain merge ai ml --into machine-learning
```

### Source Freshness

```bash
# Re-fetch stale URL sources
spkt source refresh --stale 30

# Re-fetch a specific source
spkt source refresh <source-id>
```

### Brain Health & Maintenance

```bash
# Diagnose issues (orphans, weak synapses, overdue reviews)
spkt diagnose

# Domain ↔ community alignment analysis
spkt domain audit

# Learning progress report
spkt progress
spkt progress --format html -o progress.html

# Auto-generated user guide from brain contents
spkt manual

# Sleep-inspired consolidation (dry-run, then apply)
spkt consolidate
spkt consolidate apply
```

### Export & Import

```bash
# Full backup
spkt export -o backup.tar.gz
spkt import backup.tar.gz

# JSON for sharing or inspection
spkt export --format json -o brain.json

# Portable QABot bundle (read-only, with embeddings)
spkt export --format qabot -o qa-bundle.db
```

### Extractors

Spikuit ships pluggable ingestion extractors for common source formats.
`spkt source ingest` routes input to the matching extractor; you can list,
inspect, and check what's installed:

```bash
spkt skills extractor list
spkt skills extractor status              # which extractors are runnable here?
spkt skills extractor show python-code    # full SKILL.md for one
```

Bundled with v0.6.1:

| Extractor | Picks up | Requires |
|---|---|---|
| `default` | anything (fallback) | — |
| `python-code` | `*.py`, `pyproject.toml` | `python3` |
| `pdf-paper` | `*.pdf`, `arxiv.org/...` | `pymupdf` |
| `github-repo` | `github.com/...` | `gh` |

To customize a system extractor for your brain (shadcn-style copy-to-own):

```bash
spkt skills extractor fork python-code             # shadow the system version
spkt skills extractor fork _template my-format     # start from the skeleton
spkt skills extractor refresh
```

Brain-local extractors live at `<brain>/.spikuit/extractors/<name>/` and
override the system tier on name collision.

### Versioning & Undo

`spkt init` creates a git repository inside your brain so every change is
tracked. Agents are expected to cut a short-lived branch before any batch
work, then fast-forward into `main` once you've reviewed the result.

```bash
# Cut a branch before batch ingestion or curation
spkt branch start papers-2026-04        # → ingest/papers-2026-04
spkt source ingest ./papers/ -d math
# ...review the diff...
spkt branch finish                      # ff-merge into main
spkt branch abandon                     # or throw the branch away
```

Branch prefixes by intent:

- `ingest/<tag>` — adding knowledge from a source or batch
- `consolidate/<date>` — structural cleanup (merges, prunes, consolidation)

Commit messages follow conventions so history filters work:

```
ingest(<tag>): N neurons from <source>
consolidate: <summary>
review(<YYYY-MM-DD>): N fired (<correct>/<total>)
manual: <user-supplied summary>
```

Inspecting and rolling back:

```bash
spkt history -n 20                      # recent brain commits
spkt history --grep ingest              # filter by message
spkt undo                               # revert HEAD (asks first)
spkt undo --to <sha>                    # revert everything since <sha>
spkt undo --ingest-tag papers-2026-04   # revert a tagged batch
```

`spkt undo` is a `git revert` wrapper — history is preserved, never rewritten,
so a bad undo can itself be undone.

If you'd rather manage git yourself, init without it:

```bash
spkt init --no-git
```

### Visualize

```bash
# Generate interactive HTML graph
spkt visualize -o graph.html
```

## Agent Skills

Skills are LLM-powered interaction modes designed to run inside
**Agent CLIs** — tools like [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
or similar coding agents that combine LLM reasoning with shell access.

The core engine is LLM-independent — `spkt` commands work standalone.
Skills add conversational interactions on top: tutoring, curation, and Q&A.

```
┌──────────────────────────────────────────┐
│  Agent CLI (Claude Code, Codex, etc.)    │
│  ┌────────────────┐  ┌───────────────┐   │
│  │  LLM reasoning │  │  Shell access │   │
│  └───────┬────────┘  └───────┬───────┘   │
│          │    Skills / Tools │            │
│          └────────┬──────────┘            │
│                   ▼                      │
│        spikuit-core Python API           │
│   (Circuit, Sessions, Learn)             │
│                   │                      │
│              spkt CLI                    │
└──────────────────────────────────────────┘
```

### `/spkt-tutor` — AI Tutor

A 1-on-1 tutor that teaches, quizzes, and coaches — not just a quiz machine.

The tutor decides what to do based on your state: teach a concept you're weak on,
quiz you to check understanding, give feedback on mistakes, or answer your questions.

**Example session:**

```
> /spkt-tutor

Tutor: You have 5 concepts due. Functor has low stability and is
       a prerequisite for Monad, so let's start there.

       [LECTURE] A Functor is a mapping between categories that
       preserves structure. Think of it as a box you can map over...
       (explains with examples, using concepts you already know)

       Let me check your understanding.

       [QUIZ] What must a Functor preserve when mapping?

You:   The structure of the category?

Tutor: [FEEDBACK] That's on the right track, but let's be more precise.
       A Functor must preserve identity morphisms and composition.
       So fmap id = id, and fmap (f . g) = fmap f . fmap g.

       Let me try a different angle.

       [QUIZ] In Haskell, why is `fmap` different from `map`?

You:   map only works on lists, fmap works on any Functor?

Tutor: [FEEDBACK] Exactly! `map` is specialized to lists, while `fmap`
       is the generalized version for any Functor instance. ✅ fire
       Stability: 3.2 → 8.1 days

       Now let's move to Monad, which builds on what you just learned...
```

**What the tutor can do:**

| Action | When | Example |
|--------|------|---------|
| Diagnose | Session start | "Functor is weak and blocks Monad — start there" |
| Lecture | New or weak concept | Structured explanation using known concepts as anchors |
| Quiz | After teaching | Varied questions (not just "what is X?") |
| Feedback | After your answer | Explains why right/wrong, what was missing |
| Q&A | You ask a question | Pedagogical answer using your brain's knowledge |
| Drill | Persistent weakness | Focused repetition with varied question angles |

### `/spkt-ingest` — Knowledge Curation

Add knowledge through conversation. The agent structures your input,
discovers related concepts, and creates connections.

**Example session:**

```
> /spkt-ingest

What would you like to add?

> Monads in Haskell use bind (>>=) to chain computations.
  IO and Maybe are common examples.

I'll create a neuron:

── Monad ──
# モナド (Monad)
bind (>>=) で計算を連鎖させる。
Examples: IO (side effects), Maybe (failure handling)

Found 2 related concepts:
  1. Functor (0.82) → requires
  2. Applicative (0.78) → requires

Create with these connections? [Y/n]

✅ Added n-abc123, linked to Functor and Applicative
```

**What the agent does:**

- Structures raw input into well-formed Markdown neurons
- Splits multi-concept input into atomic neurons
- Checks for duplicates before adding
- Discovers related existing knowledge and suggests connections
- Proposes types and domains based on existing patterns

### `/spkt-qabot` — Knowledge Q&A

Ask questions and get answers from your brain. Retrieval quality
improves through the conversation.

**Example session:**

```
> /spkt-qabot

Ask me anything about your brain.

> What's the difference between Functor and Applicative?

A Functor lets you map a function over a wrapped value (fmap).
An Applicative extends this — it lets you apply a wrapped function
to a wrapped value (<*>). Every Applicative is a Functor, but
Applicative adds the ability to combine independent effects...

Sources: n-abc123 (Functor), n-def456 (Applicative), n-ghi789 (Monad)

> Can you go deeper on how Applicative relates to Monad?

[Previous results automatically penalized — retrieves new material]

Over-smoothing occurs when node representations converge as
GCN layers increase. After ~5 layers, all nodes have nearly
identical features...

Sources: n-jkl012 (Deep GNN analysis), n-mno345 (Spectral theory)

> Great, thanks

✅ Accepted: sources boosted for future retrieval
```

**How feedback works:**

- **Similar follow-up** → prior results weren't enough → they get penalized
- **"Thanks" / acceptance** → results were helpful → they get boosted
- **Topic change** → session resets, starts fresh
- **Persistent mode** → feedback survives across sessions

### `/spkt-curator` — Brain Curator

Conversational brain maintenance. Analyzes domain-community alignment,
resolves orphans, cleans up weak synapses, and runs consolidation — all
through dialogue.

```
> /spkt-curator

Curator: Your "math" domain spans 2 communities:
  c0: algebra, rings, fields (12 neurons)
  c3: calculus, limits, derivatives (8 neurons)

Split into "math-algebra" and "math-analysis"? [Y/n]

> y

✅ Renamed 8 neurons to "math-analysis".

3 orphan neurons found. Connect "Set Theory basics" to "math-algebra"? [Y/n]
```

## Python API

For building custom integrations, agents, or LLM adapters.

### Quiz v2 — Flashcard and FreeResponse

```python
from spikuit_core import Circuit, Grade
from spikuit_core.scaffold import compute_scaffold
from spikuit_tutor.quiz import Flashcard, FreeResponseQuiz, QuizResponse

neuron = await circuit.get_neuron("n1")
scaffold = compute_scaffold(circuit, "n1")

# Self-graded — no LLM
fc = Flashcard(neuron, scaffold)
result = fc.grade(QuizResponse(self_grade=Grade.FIRE))

# Free-response — needs an LLMGrader
fr = FreeResponseQuiz(neuron, scaffold)
raw = fr.grade(QuizResponse(answer="my answer"))
assert raw.needs_tutor_grading
```

### TutorSession + ExamPlan

```python
from spikuit_tutor.tutor import plan_exam, TutorSession

plan = await plan_exam(
    circuit,
    neuron_ids=["n1", "n2"],
    elaborate_on_correct=True,
    require_mastery=True,
)
sess = TutorSession(circuit, plan)
step = await sess.teach()
tr = await sess.record_response(QuizResponse(self_grade=Grade.FIRE))
await sess.advance()
```

### LLMGrader (free-response grading)

```python
from spikuit_agents.tutor import AgentLLMGrader

async def my_grade_fn(prompt: str) -> str:
    # call any LLM backend; return JSON string
    return '{"grade": 3, "correctness": 0.8, "feedback": "ok"}'

grader = AgentLLMGrader(my_grade_fn)
final = await grader.grade_free_response(
    question=q, rubric=r, canonical_answer=c, student_response=s,
)
await sess.record_llm_graded(final)
```

### QABotSession

```python
from spikuit_core import QABotSession

session = QABotSession(circuit, persist=True)

# Ask — returns scored, deduplicated results
results = await session.ask("What is a functor?")

# Positive feedback — boost helpful neurons
await session.accept([results[0].neuron_id])

# Follow-up — auto-penalizes prior results if similar
results = await session.ask("functor examples in Haskell?")

await session.close()  # commits boosts to DB
```

### IngestSession

```python
from spikuit_core import IngestSession, SynapseType

session = IngestSession(circuit)

# Add knowledge — auto-discovers related concepts
neuron, related = await session.ingest(
    "# Functor\n\nA mapping between categories.",
    type="concept", domain="math",
)

# Create connections
if related:
    await session.relate(neuron.id, related[0].id, SynapseType.REQUIRES)

# Merge duplicates
await session.merge(["n-old1", "n-old2"], into_id="n-keep")

await session.close()
```
