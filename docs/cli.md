# CLI Reference

All commands support `--json` for machine-readable output.

## Global Options

Most commands accept these flags:

| Option | Description |
|--------|-------------|
| `--brain`, `-b` | Brain root directory (overrides auto-discovery) |
| `--json` | Machine-readable JSON output |

## Brain Management

### `spkt init`

Initialize a new Brain in the current directory. Without flags, starts an
interactive wizard. With `--json` or explicit `--provider`, runs non-interactively.

```
$ spkt init

Brain name [my-project]:
Configure embeddings? [y/N]: y
  Providers: openai-compat, ollama
  Provider [openai-compat]:
  Base URL [http://localhost:1234/v1]:
  Model [text-embedding-nomic-embed-text-v1.5]:
  Dimension [768]:

--- Summary ---
...
Create brain? [Y/n]:
```

Non-interactive (for scripts and agents):

```bash
spkt init -p none                      # No embeddings
spkt init --name my-brain -p openai-compat \
  --base-url http://localhost:1234/v1 \
  --model text-embedding-nomic-embed-text-v1.5
spkt init -p ollama --json             # JSON output for agents
```

### `spkt config`

Show the current brain configuration.

```bash
spkt config
spkt config --json
```

### `spkt brain set-default` / `spkt brain current`

Pick which Brain `spkt` uses. A local `.spikuit/` (found by walking up
from the current directory) always wins; the default Brain is the
fallback so `spkt` can be run from anywhere. The default is stored in
the user-global config (`~/.config/spikuit/config.toml`).

```bash
spkt brain set-default ~/vaults/my-brain   # set the fallback Brain
spkt brain current                         # show what resolves here + the default
spkt brain current --json
```

### `spkt embed-all`

Backfill embeddings for existing neurons that don't have one yet.
Shows a plan (neuron count + estimated tokens) before proceeding.

```bash
spkt embed-all              # Interactive — shows plan, asks for confirmation
spkt embed-all --yes        # Skip confirmation
```

## Neuron Commands

### `spkt neuron add`

Add a new Neuron to the circuit.

```bash
spkt neuron add "# Functor\n\nA mapping between categories." -t concept -d math
spkt neuron add "Content here" --type fact --domain physics
spkt neuron add "Content" -t concept --source-url "https://example.com/paper.pdf" --source-title "A Paper"
```

| Option | Description |
|--------|-------------|
| `-t`, `--type` | Neuron type (e.g. `concept`, `fact`, `procedure`) |
| `-d`, `--domain` | Knowledge domain (e.g. `math`, `french`) |
| `--source-url` | Source URL for citation tracking |
| `--source-title` | Source title (used with `--source-url`) |

### `spkt neuron list`

List neurons with optional filters. Also supports metadata discovery.

```bash
spkt neuron list
spkt neuron list -t concept -d math
spkt neuron list --limit 50

# Metadata discovery
spkt neuron list --meta-keys --json          # All filterable/searchable keys across sources
spkt neuron list --meta-values year --json   # Distinct values for a key (with counts)
```

| Option | Description |
|--------|-------------|
| `-t`, `--type` | Filter by neuron type |
| `-d`, `--domain` | Filter by domain |
| `--limit` | Max results |
| `--meta-keys` | List all metadata keys (filterable + searchable) |
| `--meta-values KEY` | List distinct values for a metadata key |

### `spkt neuron inspect`

Show detailed information about a neuron: content, FSRS state,
pressure, sources, community, and connected synapses.

```bash
spkt neuron inspect <neuron-id>
spkt neuron inspect <neuron-id> --json    # includes sources[] and community_id
```

### `spkt neuron remove`

Remove a neuron and all its synapses.

```bash
spkt neuron remove <neuron-id>
spkt neuron remove <neuron-id> --json
```

### `spkt neuron merge`

Merge multiple neurons into one. Content is concatenated, synapses are
redirected to the target, source attachments are transferred, and the
target is re-embedded.

```bash
spkt neuron merge <source-id-1> <source-id-2> --into <target-id>
spkt neuron merge <id1> <id2> <id3> --into <target-id> --json
```

### `spkt neuron fire`

Record a review event (fire a spike). Cannot be used on auto-generated neurons.

```bash
spkt neuron fire <neuron-id> --grade fire
spkt neuron fire <neuron-id> -g strong
```

| Grade | Meaning | FSRS Rating |
|-------|---------|-------------|
| `miss` | Failed recall | Again |
| `weak` | Uncertain | Hard |
| `fire` | Correct | Good |
| `strong` | Perfect | Easy |

## Synapse Commands

### `spkt synapse add`

Create a synapse between two neurons.

```bash
spkt synapse add <pre-id> <post-id> --type requires
spkt synapse add <a-id> <b-id> --type relates_to
```

| Type | Direction | Use |
|------|-----------|-----|
| `requires` | Directed | A requires understanding B |
| `extends` | Directed | A extends B |
| `contrasts` | Bidirectional | A contrasts with B |
| `relates_to` | Bidirectional | General association |
| `summarizes` | Directed | Community summary → member |

### `spkt synapse list`

List synapses with optional filters.

```bash
spkt synapse list
spkt synapse list --neuron <neuron-id>     # Synapses connected to a neuron
spkt synapse list --type requires          # Filter by type
spkt synapse list --json
```

Output includes confidence tags (`[inferred]`, `[ambiguous]`) when applicable.

### `spkt synapse weight`

Set the weight of an existing synapse.

```bash
spkt synapse weight <pre-id> <post-id> 0.8
spkt synapse weight <pre-id> <post-id> 0.5 --json
```

### `spkt synapse remove`

Remove a synapse between two neurons.

```bash
spkt synapse remove <pre-id> <post-id>
spkt synapse remove <pre-id> <post-id> --json
```

## Source Commands

### `spkt source ingest`

Ingest a URL, file, or directory. Creates Source records, extracts content,
and outputs it for agent-driven chunking.

```bash
# Single URL
spkt source ingest "https://example.com/article" -d cs --json

# Single file
spkt source ingest ./notes.md -d math --json

# Directory (batch ingestion)
spkt source ingest ./papers/ -d cs --json
```

| Option | Description |
|--------|-------------|
| `-d`, `--domain` | Domain tag for ingested content |
| `--title` | Override source title (single file/URL only) |
| `--force` | Truncate oversized searchable metadata instead of aborting |

**Directory ingestion** reads all text files (`.md`, `.txt`, `.rst`, `.html`, etc.)
from the directory. Place a `metadata.jsonl` sidecar file to attach metadata:

```jsonl
{"file_name": "paper1.md", "title": "Paper One", "filterable": {"year": "2024", "venue": "NeurIPS"}, "searchable": {"abstract": "We propose..."}}
{"file_name": "paper2.md", "filterable": {"year": "2023"}}
```

If any file's searchable metadata exceeds `max_searchable_chars` (default: 500),
the command aborts with a per-file report. Use `--force` to truncate instead.

### `spkt source list`

List all sources with neuron counts.

```bash
spkt source list
spkt source list --json
```

### `spkt source inspect`

Show source details and attached neurons.

```bash
spkt source inspect <source-id>
spkt source inspect <source-id> --json
```

### `spkt source update`

Update source metadata (URL, title, author).

```bash
spkt source update <source-id> --url "https://new-url.com"
spkt source update <source-id> --title "New Title" --author "Author Name"
```

### `spkt source refresh`

Re-fetch URL sources to check for content changes. Uses conditional GET
(ETag / Last-Modified) to minimize bandwidth. Updated content triggers
re-embedding of affected neurons.

```bash
spkt source refresh <source-id>          # Refresh a specific source
spkt source refresh --stale 30           # Refresh sources not fetched in 30+ days
spkt source refresh --all                # Refresh all URL sources
```

Sources returning 404 are flagged as `unreachable`.

## Domain Commands

### `spkt domain list`

List all domains with neuron counts.

```bash
spkt domain list
spkt domain list --json
```

### `spkt domain rename`

Rename a domain across all neurons.

```bash
spkt domain rename old-name new-name
```

### `spkt domain merge`

Merge multiple domains into one.

```bash
spkt domain merge domain1 domain2 --into target-domain
```

### `spkt domain audit`

Analyze domain ↔ community alignment. Compares user-assigned domain labels
against the graph's natural community structure to find mismatches:

- **Split**: a domain spans multiple communities (suggest sub-domains)
- **Merge**: multiple domains converge in one community (suggest merging)

Includes TF-IDF keyword extraction per community for naming hints.

```bash
spkt domain audit
spkt domain audit --json
```

## Community Commands

### `spkt community detect`

Run community detection using the Louvain algorithm.

```bash
spkt community detect
spkt community detect -r 2.0              # Higher resolution = more communities
spkt community detect --summarize          # Also generate summary neurons per community
spkt community detect --json
```

### `spkt community list`

Show current community assignments.

```bash
spkt community list
spkt community list --json
```

## Search

### `spkt retrieve`

Graph-weighted search combining keyword matching, semantic similarity,
FSRS retrievability, graph centrality, and review pressure.

```bash
spkt retrieve "category theory"
spkt retrieve "functor" --limit 5

# Filtered retrieval
spkt retrieve "attention" --filter year=2017
spkt retrieve "GNN" --filter domain=cs --filter venue=NeurIPS
```

| Option | Description |
|--------|-------------|
| `--limit`, `-n` | Max results (default: 10) |
| `--filter KEY=VALUE` | Filter by neuron field (`type`, `domain`) or source filterable metadata. Repeatable. Strict: missing key = excluded. |

## Tutor

FSRS-scheduled review and learning progress.

### `spkt tutor due`

Show neurons due for review. Excludes auto-generated neurons
(`_meta` domain and `community_summary` type).

```bash
spkt tutor due
spkt tutor due -n 20
spkt tutor due --json
```

### `spkt tutor quiz`

Interactive flashcard review session. Presents due neurons with
scaffold-adaptive content and accepts self-grading via a Textual TUI.

```bash
spkt tutor quiz                 # Textual TUI (default)
spkt tutor quiz --limit 10
spkt tutor quiz --json          # Batch-dump all due quiz render payloads, then exit
spkt tutor quiz --no-tui        # stdin/stdout JSON loop (one response per line)
```

**TUI keys**

| Key | Action |
|-----|--------|
| `Space` | Flip card (front ↔ back) |
| `1` | Grade: Forgot (MISS) |
| `2` | Grade: Uncertain (WEAK) |
| `3` | Grade: Got it (FIRE) |
| `4` | Grade: Perfect (STRONG) |
| `n` | Add a note to the current card |
| `q` | Quit session |

Notes typed with `n` are persisted to `spike.notes` and unlock
future features like conflict detection and feedback queues.

**Agent-facing modes**

- `--json` dumps `{status, count, items: [RenderResponse...]}` for all
  due cards at once. Use this when the agent renders the UI itself.
- `--no-tui` streams one `RenderResponse` JSON line per card to stdout
  and reads one `QuizResponse` line from stdin (shape:
  `{"self_grade": "FIRE", "notes": "..."}`). Send `{"action": "quit"}`
  to stop early.

## Brain Health & Insights

### `spkt stats`

Show circuit statistics: neuron count, synapse count, graph density.

```bash
spkt stats
spkt stats --json
```

### `spkt diagnose`

Run brain health diagnostics. Detects orphan neurons, weak synapses,
overdue reviews, and other potential issues.

```bash
spkt diagnose
spkt diagnose --json
```

### `spkt tutor progress`

Generate a learning progress report. Shows review activity, retention rates,
domain coverage, and growth trends.

```bash
spkt tutor progress
spkt tutor progress --format html -o progress.html
spkt tutor progress --json
```

### `spkt manual`

Auto-generate a user guide from the brain's contents: domains, topics,
review cutoffs, and sources.

```bash
spkt manual
spkt manual --format html -o manual.html
spkt manual --write-meta                   # Also write guide as _meta neurons
spkt manual --json
```

## Consolidation

### `spkt consolidate`

Sleep-inspired knowledge consolidation. Analyzes the brain and generates
a plan to prune weak synapses, decay unused connections, and tighten the graph.

```bash
spkt consolidate                           # Dry-run — shows the plan
spkt consolidate --domain math             # Limit to a domain
spkt consolidate --json
```

### `spkt consolidate apply`

Apply a consolidation plan. Validates the plan against the current graph
state (hash check) to ensure nothing has changed since the plan was generated.

```bash
spkt consolidate apply                     # Apply after reviewing the dry-run
spkt consolidate apply --json
```

## Visualization

### `spkt visualize`

Generate an interactive HTML graph visualization.

```bash
spkt visualize
spkt visualize -o my-graph.html
```

## Export / Import

### `spkt export`

Export a Brain for backup, sharing, or deployment.

```bash
# Tarball (full backup)
spkt export -o backup.tar.gz

# JSON bundle (portable, human-readable)
spkt export --format json -o brain.json
spkt export --format json --include-embeddings -o brain-full.json

# QABot bundle (read-only SQLite for deployment)
spkt export --format qabot -o qa-bundle.db
```

| Format | Contents | Use case |
|--------|----------|----------|
| `tar` (default) | Full `.spikuit/` directory | Backup, migration |
| `json` | Neurons, synapses, sources as JSON | Sharing, inspection |
| `qabot` | Minimal SQLite with embeddings | Portable RAG deployment |

The **QABot bundle** is a self-contained SQLite file that includes neurons,
synapses, embeddings, and source citations — but excludes FSRS state,
review history, and raw source files. Load it with `Circuit(read_only=True)`.

### `spkt import`

Import a tarball backup.

```bash
spkt import backup.tar.gz
```

## Extractors (`spkt skills extractor`)

Extractors are pluggable ingestion strategies — each is a `SKILL.md` +
`manifest.toml` bundle that an Agent CLI invokes during `spkt source ingest`.
They live in two tiers, with brain-local shadowing system on name collision
(shadcn-style):

```
1. <BRAIN>/.spikuit/extractors/<name>/                       (brain, wins)
2. <spkt-install>/skills/spkt-ingest/extractors/<name>/      (system)
```

Spikuit ships with a `default` extractor (generic markdown chunker) and a
`_template/` skeleton for new extractors.

### `spkt skills extractor list`

Show all resolved extractors and which tier they came from.

```bash
spkt skills extractor list
spkt skills extractor list --json
```

### `spkt skills extractor status`

Probe each extractor's `[requires]` section against the host environment
(commands on PATH, importable Python packages). Use this to decide whether
an extractor can run, or whether the user needs to install something first.

```bash
spkt skills extractor status              # all extractors
spkt skills extractor status pdf-paper    # one
spkt skills extractor status --json
```

JSON output:

```json
[
  {"name": "default", "available": true, "missing_commands": [], "missing_python_packages": []},
  {"name": "pdf-paper", "available": false, "missing_commands": [], "missing_python_packages": ["pymupdf"]}
]
```

### `spkt skills extractor show <name>`

Print the manifest plus the full SKILL.md for one extractor.

### `spkt skills extractor fork <name> [<new-name>]`

Copy a system extractor into the brain so you can edit it. Omit `<new-name>`
to keep the same name and shadow the system version.

```bash
spkt skills extractor fork default               # shadow system default
spkt skills extractor fork default my-default    # new brain-local name
```

### `spkt skills extractor add <path>`

Install an external extractor directory (must contain `manifest.toml` +
`SKILL.md`) into the brain.

### `spkt skills extractor remove <name>`

Delete a brain-local extractor. System extractors cannot be removed.

### `spkt skills extractor refresh`

Regenerate `<brain>/.spikuit/extractors/_registry.toml` after manual edits.

## Versioning (Git-backed)

`spkt init` creates a git repository inside the brain so every change is
tracked. Agents are expected to cut a short-lived branch before any batch
work, then fast-forward into `main` once the result is reviewed.

### `spkt branch start`

Cut a new ingest/consolidate branch from `main`.

```bash
spkt branch start papers-2026-04        # → ingest/papers-2026-04
spkt branch start consolidate-2026-04   # → consolidate/2026-04
```

### `spkt branch finish`

Fast-forward merge the current branch into `main` and delete it. Refuses
to operate on `main` or any non-`ingest/`/`consolidate/` branch.

### `spkt branch abandon`

Discard the current branch and switch back to `main`. Same guardrail as
`finish`.

### `spkt history`

List recent brain commits (a `git log` wrapper).

```bash
spkt history -n 20
spkt history --grep ingest
spkt history --json
```

### `spkt undo`

Revert commits via `git revert` — history is preserved, never rewritten.

```bash
spkt undo                               # revert HEAD (asks first)
spkt undo --to <sha>                    # revert everything since <sha>
spkt undo --ingest-tag papers-2026-04   # revert all commits matching ingest(papers-2026-04)
spkt undo -y                            # skip confirmation
```

To opt out of git-backed versioning, run `spkt init --no-git` or set
`[git] auto_commit = false` in `.spikuit/config.toml`.

## Deprecated Commands

Old flat commands still work but show deprecation warnings on stderr.
Use the resource-oriented form above.

| Old command | New command |
|-------------|------------|
| `spkt add` | `spkt neuron add` |
| `spkt list` | `spkt neuron list` |
| `spkt inspect` | `spkt neuron inspect` |
| `spkt fire` | `spkt neuron fire` |
| `spkt due` | `spkt tutor due` |
| `spkt quiz` | `spkt tutor quiz` |
| `spkt neuron due` | `spkt tutor due` |
| `spkt link` | `spkt synapse add` |
| `spkt learn` | `spkt source ingest` |
| `spkt refresh` | `spkt source refresh` |
| `spkt communities` | `spkt community list` / `spkt community detect` |
