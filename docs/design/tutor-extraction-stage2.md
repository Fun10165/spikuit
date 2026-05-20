# Tutor extraction — Stage 2 design

**Status:** Reviewed — round 1 (2026-05-20) resolved Q1–Q8 (§8).
Design only, no implementation in this doc.
**Slot:** v0.9.0 (per `roadmap.md` §6 — "Not additive, needs its own
session and migration plan"). Current version 0.7.1.
**Extends:** `tutor-extraction-stage1.md` (Stage 1, merged PR #68) and
`roadmap.md` §6. **Refines** `tutor-extraction-stage1.md` §7's
Stage-2 prediction — see §4.6.

## 1. Purpose

Stage 1 gave the app layer a curated contract (`spikuit_core.appkit`)
and an enforced import boundary. It deliberately left the database
alone: FSRS scheduling state still lives in `spikuit-core`, in the
`fsrs_state` table, managed entirely inside `Circuit`.

Stage 2 finishes the extraction. It **retires `fsrs_state` from
`spikuit-core`** and re-homes FSRS card state into a
`spikuit-tutor`-owned SQLite store, joined to the substrate by
`neuron_id`. This is the "FSRS-as-overlay" decision (context doc
decision Q-B = α: *tutor-app independent SQLite*) made concrete.

After Stage 2:

- `spikuit-core` is a knowledge-graph substrate with **no learner
  model** — it does not know what a "review" or a "due card" is.
- `spikuit-core` no longer depends on the `fsrs` package.
- FSRS scheduling — cards, ratings, retrievability, the review loop —
  is wholly owned by `spikuit-tutor`.
- The substrate keeps `Spike`/`Grade` (its plasticity pipeline is
  grade-driven) but stops *scheduling* on them.

This is **not additive and not trivially reversible**: it is a
multi-file substrate refactor plus a data migration. It needs the
care a schema migration deserves — hence this doc before any code.

## 2. Current coupling — the facts

Measured against `main` after PR #68 (Stage 1 merged). All line
numbers are `spikuit-core/src/spikuit_core/circuit.py` unless noted.

### 2.1 The `fsrs_state` table

```sql
CREATE TABLE IF NOT EXISTS fsrs_state (
    neuron_id TEXT PRIMARY KEY REFERENCES neuron(id),
    card_json TEXT NOT NULL
);
```

Core DB default path is `~/.spikuit/spikuit.db` (`db.py`
`DEFAULT_DB_PATH`). *Note: the Stage-2 kickoff guide in the context
doc said `circuit.db` — that is wrong; the real filename is
`spikuit.db`. No DB file exists on the current dev machine, so this
analysis is from code and schema, not a live DB.*

`db.py` touches the table in: `upsert_fsrs_card`, `get_fsrs_card_json`,
`get_due_neurons` (the last is dead — `Circuit` never calls it),
`delete_neuron` (`DELETE FROM fsrs_state WHERE neuron_id=?`), and the
`CREATE TABLE`. `soft_retire_neuron` deliberately *preserves* FSRS
state across a soft retire.

### 2.2 The `_cards` in-memory cache

`Circuit.__init__` builds `_scheduler = Scheduler()` and
`_cards: dict[str, Card] = {}`. `connect()` calls `_load_cards()`,
which does `SELECT neuron_id, card_json FROM fsrs_state` and
deserializes every row into `_cards`. Every FSRS read in `Circuit`
goes through this dict, not the DB.

### 2.3 Full `Circuit` FSRS-use inventory

Stage 1 §2.3 found that `spikuit-tutor` never touches `fsrs_state`
columns directly — true, and it framed the contract as "the `Circuit`
method subset." **Stage 2 reveals the deeper fact: `Circuit` itself
uses FSRS state in far more than the four `SchedulerCircuit` methods.**
Six more methods read it. Moving the table forces a decision at each
site.

| Site | What it does with FSRS | Stage-2 verdict |
|---|---|---|
| `__init__` (109–110) | builds `Scheduler` + `_cards` cache | **Remove** from core |
| `connect`→`_load_cards` (213, 237) | bulk-loads `fsrs_state` into `_cards` | **Remove** |
| `add_neuron` (318) | eager `Card()` + `upsert_fsrs_card` | **Remove** — lazy in tutor (§4.4) |
| `upsert_meta_neuron` (806) | eager `Card()` for meta-neuron | **Remove** |
| `generate_community_summaries` (1532, 1578) | eager `Card()` + stale `_cards.pop` | **Remove** |
| `remove_neuron` (400) | `_cards.pop` | **Remove** |
| `fire` (931–1020) | spike + `review_card` + propagation + pressure + STDP; returns `Card` | **Split** (§4.2) |
| `get_card` (1024) | reads `_cards` | **Move** to tutor |
| `due_neurons` / `near_due_neurons` (1036, 1053) | iterate `_cards` by `card.due` | **Move** to tutor (§4.4) |
| `retrieve` (1123) | `get_card_retrievability` as a ranking-score term | **Decouple** (§4.3) |
| `consolidate` (1612) | `card.stability` for `removable` / `forget` triage | **Decouple** (§4.3) |
| `diagnose` (1902) | `card.stability` for `dangling_prerequisites` | **Decouple** (§4.3) |
| `progress` (2234) | stability / retrievability / retention learner report | **Move** wholesale to tutor (§4.3) |
| `stats` (1886) | `cards_loaded` count | **Drop** — tutor reports its own |

`domain_audit` (2060–2233) was checked and does **not** read FSRS
state — it stays clean.

### 2.4 `compute_scaffold` — Stage 1's deferred problem

`scaffold.py`'s `compute_scaffold(circuit, neuron_id)` reads
`circuit.get_card`, `card.state`, `card.stability`, imports
`fsrs.State`, and walks graph topology (`circuit.neighbors`,
`circuit.predecessors`, raw `circuit.graph[a][b]["type"]`).

Stage 1 §2.4 kept it in core *because* it needs both FSRS state and
graph topology, and §7 predicted it would be dropped from `appkit` at
Stage 2. Stage 2 confirms the relocation but for a sharper reason:
once `fsrs_state` leaves core, `compute_scaffold` **can no longer read
FSRS state from inside core** — it has no choice but to move to
`spikuit-tutor`, where the cards now live. See §4.5.

### 2.5 CLI direct use

`spikuit-cli` is the wiring layer and is *not* under the import ban.
It uses FSRS in three places: `helpers.py` `_neuron_dict` calls
`circuit.get_card` to build an `fsrs` JSON block; `main.py` imports
`compute_scaffold` directly for the quiz command; `neuron.py:332`
does `card = await circuit.fire(spike)` for `spkt neuron fire`. All
three need rewiring once FSRS moves (§4.7).

### 2.6 The headline

The substrate today does not merely *store* the learner's memory
model — it **ranks and curates by it**. `retrieve` boosts results by
FSRS retrievability; `consolidate` and `diagnose` triage by FSRS
stability. Under the FSRS-as-overlay framing (and the AMKB principle
that the substrate "is not a learning system" — context doc §H4),
**the substrate must stop reading the learner model entirely.** That
is the real content of Stage 2, and §4.3 is where it is decided.

## 3. What the migration must achieve

1. `fsrs_state` is no longer a `spikuit-core` table. FSRS card state
   lives in a `spikuit-tutor`-owned store.
2. `spikuit-core/src/**` has **zero** `import fsrs` — verified by CI.
3. `spikuit-core` ranking (`retrieve`) and curation (`consolidate`,
   `diagnose`) compute from substrate-native signals only.
4. Existing user databases migrate cleanly, with a tested rollback.
5. `appkit` changes are deliberate and version-gated, not accidental
   (§4.6).
6. No regression in the tutor's externally-observable behaviour
   (review loop, due queue, scaffolding) beyond the documented
   `retrieve` re-ranking (§4.3).

### 3.1 Non-goals (scope guards)

- **Not** migrating `quiz_item` / `quiz_item_neuron`. Quiz items are
  arguably tutor-domain too, but that is a separate table move with
  its own join and migration — out of Stage 2.
- **Not** adopting the substrate-doc signed-weight `record_use`
  redesign. Stage 2 keeps the current `Spike`/`Grade` interface; the
  signed-weight convergence is `substrate-self-organization.md`'s
  concern (§4.2).
- **Not** building a live event-driven orphan reaper. Stage 2 ships
  reconcile-on-open; the reaper is a later refinement (§4.4).
- **Not** building tutor-populated memory-aware retrieval. Stage 2
  drops the FSRS retrieval term; *re-adding* it via `retrieval_boost`
  is a follow-up tutor feature (§4.3).
- **Not** designing per-overlay vs shared plasticity for the
  multi-overlay case (§4.1 forward note).
- **Not** touching `amkb-spec`.

## 4. Design

### 4.1 The two-database model

| | Owner | Path | Holds |
|---|---|---|---|
| Substrate DB | `spikuit-core` | `~/.spikuit/<brain>.db` | neuron, synapse, spike, retrieve_log, retrieval_boost, quiz_item*, source*, changeset, event, neuron_vec* |
| Tutor store | `spikuit-tutor` | configurable; default `<substrate-stem>.tutor.db` | `fsrs_card` |

**Why a separate DB, not extra tables in the core DB.** The decisive
reason is *plurality of overlays*. One substrate KB is meant to be
shared by several apps — `spikuit-tutor`, `spikuit-agent-rag`, even a
second tutor instance (a different learner, an experiment). If FSRS
state lived in core tables, a second overlay on the same KB would
collide on it immediately. With per-overlay DB files the substrate
does not even know overlays exist: each app instance is configured
with `(substrate DB path, its own overlay DB path)`. The overlay path
is therefore **configurable**, not a fixed sibling name — the default
`<substrate-stem>.tutor.db` only serves the common single-tutor case.

Join key is `neuron_id` (= core `neuron.id`). The overlay stores **no
graph data** — no synapse, no topology copy. `compute_scaffold` and
every topology read go to the substrate live through the contract
(§4.5). So the cross-DB "link" is a single TEXT column, not a
relational mapping; the only real integrity concern is orphaned cards,
handled by reconcile-on-open (§4.4).

**SQLite cannot enforce a cross-file foreign key.** Referential
integrity between `fsrs_card.neuron_id` and `neuron.id` is the tutor's
responsibility, via reconcile-on-open — not a live reaper.

Proposed `fsrs_card` schema (minimal — no `due` index for Stage 2;
the tutor loads all cards into memory on open, exactly as `Circuit`
does today):

```sql
CREATE TABLE fsrs_card (
    neuron_id   TEXT PRIMARY KEY,   -- logical join to core neuron.id
    card_json   TEXT NOT NULL,
    reviewed_at TEXT,               -- last review timestamp
    created_at  TEXT NOT NULL
);
```

> **Forward note (out of Stage 2 scope).** When multiple overlays
> review against one shared substrate, each `fire()` writes
> STDP/pressure back to the *shared* graph. Whether that collective
> plasticity is desirable, or whether plasticity should be
> per-overlay, is a real question for the multi-overlay milestone. It
> does not affect Stage 2, which extracts a single tutor.

### 4.2 Splitting `fire()`

`Circuit.fire` today does eight steps. They cleave cleanly:

| Steps | Belongs to | After Stage 2 |
|---|---|---|
| 1 spike insert; 5 APPNP propagation; 6 pressure reset; 7 STDP; 8 last-fire timestamp | **substrate** — plasticity, grade-driven | stays in `Circuit.fire` |
| 2 get/create card; 3 `scheduler.review_card`; 4 persist card | **tutor** — FSRS scheduling | moves to `spikuit-tutor` |

The substrate method **keeps the name `fire`** — a neuron firing is
the native spike metaphor of Spikuit (spike + circuit), and `spkt
neuron fire` is a documented CLI command. Stage 2 only shrinks its
body (drop the FSRS steps 2–4) and changes its return type: it no
longer returns a `Card`, it returns `None` or a small substrate-side
summary. It still consumes `spike.grade` — `compute_propagation` and
`compute_stdp` are both grade-driven — so `Grade` and `Spike` remain
substrate types.

**Orchestration inverts.** Today `Circuit.fire` is the orchestrator
and the tutor calls it. After Stage 2 the **tutor session is the
orchestrator**: on a review it (a) loads the card from its store,
(b) `card, log = scheduler.review_card(card, rating, at)`, (c) persists
the card, (d) calls `substrate.fire(spike)`. The substrate becomes a
callee, not the conductor.

**No rename.** An earlier draft proposed renaming the method to
`record_use` to match the AMKB verb vocabulary; review round 1
rejected that. `record_use` stays a *conceptual / protocol-level*
verb — the coarse intent-layer name in `substrate-self-organization.md`
§3 — and the `amkb.Store` adapter maps it onto `circuit.fire`. Keeping
the substrate method named `fire` preserves the clean two-layer story
(*intent verb* → *mechanism method*) and avoids CLI/doc churn. The
naming of that conceptual verb itself (`record_use` vs `feedback` vs …)
is a `substrate-self-organization.md` matter, out of Stage 2 scope —
see Q7.

### 4.3 Decoupling the substrate's own FSRS reads

Per §2.6, the substrate must stop reading the learner model. Four
sites, four recommendations:

**`retrieve` — drop the FSRS term.** Today the score is
`text_sim × (1 + retrievability + centrality + pressure + boost)`
(and a parallel semantic-path formula). Recommendation: **drop the
`retrievability` term.** The substrate ranks by its own signals —
`text_sim`, `centrality`, `pressure`, `boost`. This is a **behaviour
change to a public verb**: `spkt retrieve` results re-rank. It is the
headline risk of Stage 2.

The capability is not lost — it relocates. `retrieval_boost` already
exists as an externally-settable per-neuron weight with a clean API
(`set_retrieval_boost`, `commit_retrieval_boosts`) and is already a
term in the formula. A tutor that wants memory-aware retrieval
computes a boost from its FSRS cards and pushes it through that seam.
Stage 2 only *removes the inline coupling*; *re-adding* memory-aware
retrieval as a tutor feature over `retrieval_boost` is a follow-up,
out of Stage 2 scope (§3.1).

**`consolidate` / `diagnose` — substitute spike-table signals.** Both
triage by `card.stability` (a smooth FSRS memory-strength estimate):
`consolidate` for `removable_neurons` / `forget_candidates`,
`diagnose` for `dangling_prerequisites`. The `spike` table — every
review event with timestamp and grade — **stays in core.**
Recommendation: the substrate computes a native consolidation signal
from `spike` rows (count, recency, grade distribution) and triages on
that. This is a coarser signal than FSRS stability — flag it — but it
is directionally correct: the substrate should self-assess from its
own event log, not borrow the tutor's model. (If the substrate later
grows a native `use_count` per the AMKB roadmap, these sites can
upgrade to it; Stage 2 uses `spike`.)

**`progress` — move wholesale to the tutor.** `Circuit.progress`
builds a learner-facing retention report (stability, retrievability,
retention curves, reviewed-ratio). It is pure tutor domain. Move the
whole method to `spikuit-tutor`. It needs review history, so the
substrate must expose **`get_spikes_for(neuron_id)`** as public API
(today `get_spikes_for` lives on `Database`; `Circuit` only has the
internal `insert_spike`). Add it to the contract (§4.6).

**`stats` — drop `cards_loaded`.** It is the only FSRS-derived field
in `Circuit.stats`. Drop it; the tutor reports its own card count.

### 4.4 Lazy card creation & the "new neuron" question

Today every neuron gets an eager `Card()` at creation (`add_neuron`,
`upsert_meta_neuron`, `generate_community_summaries`). `due_neurons`
iterates `_cards`; a fresh card is due immediately, so new neurons
surface naturally in the review queue.

After Stage 2 the substrate creates no cards. The tutor creates a
card **lazily on first review**. This raises a question the eager
model hid: *how does a never-reviewed neuron surface as "due"?*

Recommendation: the tutor's due query is the union of two buckets —
**(past-due cards)** from its `fsrs_card` table, and **(neurons with
no card)** = `substrate.list_neurons(...)` minus the card table's
keys. The second bucket is the "new / unlearned" set. `list_neurons`
already exists on `Circuit` and stays on the contract.

This also retires `due_neurons` / `near_due_neurons` from the
substrate entirely — they are FSRS queries — and they are
reimplemented inside `spikuit-tutor` over the `fsrs_card` store.
`builder.py` (tutor code) repoints to the tutor's planner.

**Orphan cleanup.** When a neuron is deleted/retired the substrate
emits an `event` row (event log already exists). A full live reaper
that subscribes via `events(follow=True)` and deletes the stale card
is the right long-term shape — but it is more than Stage 2 needs.
Stage 2 ships **reconcile-on-open**: when the tutor store opens, it
prunes any `fsrs_card` row whose `neuron_id` is absent from
`substrate.list_neurons()`. The event-driven reaper is deferred (Q6).

### 4.5 `compute_scaffold` moves to the tutor

Per §2.4 `compute_scaffold` *must* move — it reads FSRS card state,
which after Stage 2 lives in the tutor. It relocates to
`spikuit-tutor` (e.g. `spikuit_tutor/scaffold.py`), taking the
`fsrs.State` import with it.

It still needs **graph topology** from the substrate: `neighbors`,
`predecessors`, and edge type. It currently reaches edge type through
raw networkx (`circuit.graph[a][b]["type"]`). To move it without
dragging networkx into the contract, Stage 2 adds a small read-only
substrate method **`edge_type(a, b) -> str`** and `compute_scaffold`
uses that. `neighbors` / `predecessors` are already public on
`Circuit`. All three go on the contract (§4.6).

`Scaffold` and `ScaffoldLevel` (the result types) move to
`spikuit-tutor` with the function.

### 4.6 `appkit` contract evolution

Stage 1 designated `appkit` public and semver-stable, and §7
predicted Stage 2 would "drop the FSRS-facing re-exports (`Grade`,
`Spike`, `compute_scaffold`)". **This Stage-2 analysis refines that
prediction:**

- `Grade` and `Spike` **stay** in core and stay in `appkit` — the
  substrate's `fire`/propagation/STDP are grade-driven (§4.2).
  Stage 1's prediction was wrong on these two.
- `compute_scaffold`, `Scaffold`, `ScaffoldLevel` **leave** — they
  move to `spikuit-tutor` (§4.5). `appkit` drops these three.
- `SchedulerCircuit` Protocol changes shape and is **renamed**. It
  **keeps `fire`** (reshaped — see §4.2), drops `due_neurons` /
  `near_due_neurons` (those are FSRS queries — §4.4), gains
  `neighbors`, `predecessors`, `edge_type`, `get_spikes_for`, and
  keeps `get_neuron`, `list_neurons`. It no longer *schedules* —
  proposed rename `SchedulerCircuit` → `SubstrateView`.

`appkit` `__all__` after Stage 2:
`Grade, Spike, NeuronView, SubstrateView`.

This is a **breaking change** to a module Stage 1 declared
semver-stable. Spikuit is pre-1.0 (0.7.1); under 0.x semantics a
minor bump may break, and Stage 2 *is* the v0.9.0 minor bump.
Recommendation: **carry the `appkit` break in v0.9.0**, document it in
the changelog, and accept it — no deprecation shim. (Alternative:
keep `compute_scaffold` etc. as deprecated re-export shims for one
release. Q4.)

Only one app consumes `appkit` today — first-party `spikuit-tutor` —
and most of the churn is *within* `spikuit-tutor` (it gains the
scaffold code it imports). So the blast radius is small and
self-contained.

### 4.7 db.py and CLI changes

**`spikuit-core/db.py`:** drop the `fsrs_state` `CREATE TABLE`;
delete `upsert_fsrs_card`, `get_fsrs_card_json`, `get_due_neurons`;
remove the `DELETE FROM fsrs_state` line from `delete_neuron`;
`soft_retire_neuron` no longer special-cases FSRS preservation. Add
public `Circuit.get_spikes_for` and `Circuit.edge_type`.

**`spikuit-cli`:** the CLI constructs the `Circuit`
(`helpers.py:34`); it must now also construct and inject the tutor
store. `helpers.py` `_neuron_dict`'s `fsrs` block, the `main.py`
quiz `compute_scaffold` import, and `neuron.py`'s `circuit.fire` call
all rewire to the tutor. `spkt neuron fire` keeps its command name
but becomes tutor-orchestrated (FSRS scheduling is inherently
tutor) — Q7. `progress` surfaces as `spkt tutor progress`.

## 5. Recommended Stage 2 plan

Ordered so the tree stays green between steps where possible.

1. **Tutor store.** Add `spikuit_tutor` FSRS store module
   (`fsrs_card` schema §4.1), with open/close, load-all-into-memory,
   upsert, and reconcile-on-open (§4.4). Unit-test in isolation.
2. **Move FSRS into the tutor.** Relocate the `Scheduler`, the
   `_GRADE_TO_RATING` map, `get_card`/`due_neurons`/`near_due_neurons`
   logic, `compute_scaffold` + `Scaffold`/`ScaffoldLevel`, and
   `Circuit.progress` into `spikuit-tutor`. The tutor session becomes
   the review orchestrator (§4.2).
3. **Split `fire`.** Reduce `Circuit.fire` to substrate steps
   1,5,6,7,8 (drop the FSRS steps 2–4); its return type changes from
   `Card`. Keep the method name. Add `Circuit.edge_type` and public
   `Circuit.get_spikes_for`.
4. **Decouple substrate ranking/curation** (§4.3): drop the
   `retrieve` retrievability term; reimplement `consolidate` /
   `diagnose` triage on `spike`-table signals; drop
   `stats.cards_loaded`.
5. **Strip FSRS from core.** Remove `_cards`/`_scheduler` from
   `Circuit`, the eager card creation, `_load_cards`, the `db.py`
   FSRS methods and the `fsrs_state` table. Drop `fsrs` from
   `spikuit-core`'s dependencies.
6. **Evolve `appkit`** (§4.6): drop the scaffold trio, rename
   `SchedulerCircuit` → `SubstrateView`, reshape the Protocol. Update
   the `appkit` conformance test.
7. **Rewire `spikuit-cli`** (§4.7): inject the tutor store; repoint
   `_neuron_dict`, the quiz command, `neuron fire`, `progress`.
8. **Migration script** (§6) and the changelog/version bump to
   v0.9.0.

## 6. Migration script & rollback

`scripts/migrate_fsrs_to_tutor.py`, mirroring the existing
`scripts/migrate_tataque.py` pattern (argparse, `--dry-run`,
`--brain` / explicit `--db-path`).

**Forward.** For a given substrate DB: open it, open (or create) the
sibling `<stem>.tutor.db`, copy every `fsrs_state` row into
`fsrs_card` (`card_json` verbatim; derive `reviewed_at`/`created_at`
from the card, or stamp `created_at = now`). Idempotent: re-running
upserts by `neuron_id` and is a no-op on an already-migrated DB.

**Two-phase table drop.** The migration script does **not** drop
`fsrs_state` — it leaves it dormant. The `DROP TABLE fsrs_state`
ships one release later (v0.9.1 / v0.10.0), once v0.9.0 has proven
out in the field. This keeps a window where rollback is pure code
revert + nothing lost (Q8).

**Rollback.** While `fsrs_state` is still present (the dormant
window), rollback is: `git revert` the v0.9.0 code, and the substrate
DB still has its `fsrs_state` rows. A `--reverse` flag on the script
copies `fsrs_card` back into `fsrs_state` for the case where reviews
happened post-migration and must not be lost.

`--dry-run` prints the row counts and the source/target paths without
writing.

## 7. CI & verification

Stage 1 added `ci.yml` (4-package pytest matrix + `import-check`).
Stage 2 extends verification:

- **`import fsrs` ban.** Extend `tools/check_app_imports.py` (or add a
  sibling check) to assert `spikuit-core/src/**` contains no
  `import fsrs` / `from fsrs import …`. This is the machine-checkable
  statement of "the substrate has no learner model."
- **`appkit` conformance test** updated for the new `__all__` and the
  `SubstrateView` shape; assert `Circuit` still satisfies it.
- **Migration test.** A fixture substrate DB with `fsrs_state` rows →
  run the script → assert `fsrs_card` parity, idempotency on
  re-run, and `--reverse` round-trips.
- **Behaviour-change test.** A focused test pinning the new
  `retrieve` ordering (FSRS term gone) and the spike-signal
  `consolidate`/`diagnose` triage, so the §4.3 change is intentional
  and locked, not silent.
- All four package suites stay green (Stage-1 baseline: core 333 /
  agents 39 / cli 34 / tutor 36 — tutor and core counts will shift as
  code moves; the *sum* of FSRS tests should not drop).

## 8. Open questions for review

Review round 1 (2026-05-20) resolved Q1–Q8; resolutions recorded
inline.

- **Q1 — Substrate fully drops FSRS reads? → RESOLVED: yes.** The
  substrate stops reading the learner model everywhere, including the
  `retrieve` re-ranking. The `spkt retrieve` ordering change (FSRS
  retrievability term dropped) is accepted; memory-aware retrieval, if
  wanted, returns later as a tutor feature over `retrieval_boost`
  (§4.3).
- **Q2 — `consolidate`/`diagnose` substitute. → RESOLVED: spike-table
  signals now.** Both triage on substrate-native `spike`-table signals
  (count, recency, grade distribution), not FSRS stability. If the
  substrate later grows a native `use_count`, these sites can upgrade.
- **Q3 — `compute_scaffold` relocation. → RESOLVED: confirmed.** Moves
  to `spikuit-tutor`; `Circuit.edge_type` is added so it need not
  touch raw networkx (§4.5).
- **Q4 — `appkit` break & version. → RESOLVED: v0.9.0 minor bump.**
  The breaking `appkit` change ships in the v0.9.0 minor bump, no
  deprecation shim. Pre-1.0 semantics allow a minor bump to break;
  document it in the changelog.
- **Q5 — Tutor store location & name. → RESOLVED: separate DB,
  configurable path.** A separate per-overlay DB, not extra core
  tables — the decisive reason is overlay plurality (one substrate KB,
  many overlays: tutor, agent-rag, a second tutor; §4.1). The overlay
  path is configurable; `<substrate-stem>.tutor.db` is only the
  single-tutor default. Minimal schema (no `due` index) confirmed.
- **Q6 — Orphan cleanup. → RESOLVED: reconcile-on-open.** Stage 2
  ships reconcile-on-open; the `events(follow=True)` reaper is
  deferred (§4.4).
- **Q7 — `fire` naming & `spkt neuron fire`. → RESOLVED: keep
  `fire`.** The split-out substrate method keeps the name `fire`
  (native spike metaphor, no CLI/doc churn — §4.2); the earlier
  `record_use` rename proposal is dropped. `record_use` stays the
  coarse conceptual verb in `substrate-self-organization.md`, and the
  `amkb.Store` adapter maps it onto `circuit.fire`. Naming *that*
  conceptual verb (current lean: **`feedback`**, since it pairs with
  the UI-layer term `retrieve` and reads as "reflecting the user's
  feedback") is deferred to that doc's own review — out of Stage 2
  scope. `spkt neuron fire` keeps its command name and becomes
  tutor-orchestrated.
- **Q8 — Two-phase table drop. → RESOLVED: confirmed.** The migration
  leaves `fsrs_state` dormant for one release; `DROP TABLE` ships in a
  later release, preserving a rollback window.

## 9. Effort & risk

| | |
|---|---|
| Diff size | **Large.** Multi-file substrate surgery (`circuit.py`, `db.py`, `scaffold.py`), new tutor store module + relocated FSRS code, `appkit` reshape, CLI rewiring, migration script. |
| Runtime risk | **Medium-high.** §4.3 changes `retrieve` ordering and `consolidate`/`diagnose` triage — observable behaviour, not just re-exports. The `fire` split inverts orchestration. |
| Data risk | **Medium.** A real schema migration. Mitigated by `--dry-run`, idempotency, `--reverse`, and the §6 dormant-table window. |
| Test risk | **High.** Every FSRS path re-tests across the core/tutor boundary; behaviour-change tests must be written, not just inherited. |
| Reversibility | Data: reversible within the dormant window (§6). Code: a genuine refactor — reversible only by `git revert`, not a toggle. |
| Blocking dependency | Stage 1 (PR #68) merged ✓. No further blocker. |

## 10. Cross-references

- `tutor-extraction-stage1.md` — Stage 1 contract; §2.3/§2.4 set up
  this doc; §7's Stage-2 prediction is refined in §4.6 here.
- `roadmap.md` §6 — extraction workstream; v0.9.x slot; "Not
  additive" flag.
- `substrate-self-organization.md` — the AMKB substrate verbs; the
  `record_use` conceptual verb whose naming Q7 defers here; the
  signed-weight redesign §4.2 keeps separate.
- `agent-workspace/contexts/active/spikuit-amkb-v03-tutor-extraction.md`
  — canonical context; decision Q-B (α: tutor-app SQLite); H3 staging.
- `scripts/migrate_tataque.py` — the migration-script pattern §6
  mirrors.
