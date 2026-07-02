# AMKB Integration Plan — Spikuit v0.7.x

**Status.** **Shipped.** v0.7.0 released 2026-04-13 (core plumbing);
v0.7.1 released 2026-04-13 (adapter + conformance). This plan is now
a reference record — further AMKB work is tracked under
`v0.7.2`+ milestones. Written against `amkb-spec` v0.2.0 and
`amkb-sdk` (consumed as a git dependency pinned to an exact rev in
`pyproject.toml`; switches to a PyPI pin once `amkb>=0.1.0` ships).

**Goal.** Let any AMKB-aware consumer drive a Spikuit brain through
the `amkb.Store` Protocol — without changing what existing
`spkt` users see, what the engine computes, or the shape of
existing DB rows.

## Constraints (non-negotiable)

1. **No core-logic leakage into AMKB surface.** APPNP, FSRS,
   pressure dynamics, community detection, and embedder internals
   MUST NOT appear in any type, method, or event that the adapter
   exposes. AMKB consumers see Nodes/Edges/Events only.
2. **No existing feature may regress.** `spkt` CLI behavior, DB
   compatibility (existing columns keep existing semantics), and
   every current test case must still pass on the
   `amkb-integration` branch before merge. New AMKB behavior is
   opt-in — triggered only when the caller goes through the
   adapter.
3. **Dependency direction is one-way.** `spikuit-agents/amkb/`
   depends on `spikuit-core`. `spikuit-core` MUST NOT depend on
   `amkb-sdk` types or import from the adapter. If a helper is
   reusable, it lives in `amkb-sdk` (`amkb.validation`,
   `amkb.snapshots`, etc.) and the adapter calls it.
4. **Additive DB migrations only.** New columns default to
   NULL / sensible defaults. No destructive migrations, no column
   renames, no dropped tables.

Any PR that breaks one of these constraints is rolled back; the
plan does not accept "small" exceptions.

## Two-milestone split

The work splits cleanly along the core/adapter boundary.

### v0.7.0 — AMKB core plumbing ✅ shipped (2026-04-13)

Adds the minimum `spikuit-core` primitives that an adapter needs
to satisfy AMKB L1 (Core) conformance. Nothing here is
AMKB-shaped on the outside — the types stay `Neuron`/`Synapse`,
the methods stay async — but the behaviors required by the
protocol become available.

Scope (detailed in `amkb-core-plumbing-spec.md`):

- **Soft-retire for Neuron and Synapse** — add `retired_at`
  nullable column. Soft-retire becomes the **only** delete path
  for both core and CLI; physical purging is explicit via
  `spkt history prune`. Vector index rows are physically deleted
  on retire to keep ANN recall undegraded.
- **Event log** — new `changeset` / `event` tables. Each mutation
  appends rows. Read-only consumers can replay.
- **Transaction wrapper** — `async with circuit.transaction(tag,
  actor) as tx:` that buffers mutations and emits one ChangeSet on
  commit. Direct calls to `add_neuron` etc. auto-commit in a
  one-op transaction to keep existing CLI behavior.
- **Predecessor tracking** — `neuron_predecessor` junction table
  populated by merge. `circuit.predecessors(id)` already exists
  for graph adjacency; lineage is a separate concept.
- **Canonical error mapping** — a small adapter-side table that
  maps Spikuit's internal exceptions to `amkb.errors` codes. Core
  raises its own exceptions as today; the adapter translates.
- **Source as Node (adapter-only)** — Spikuit keeps Sources in the
  `source` table. The adapter presents each row as a virtual
  `Node(kind="source", layer="L_source")` without changing
  storage. Junction `neuron_source` becomes the `derived_from`
  edge set on read.

### v0.7.1 — AMKB adapter + conformance ✅ shipped (2026-04-13)

Added `spikuit-agents/src/spikuit_agents/amkb/` with six modules:

- `store.py` — `SpikuitStore` satisfying `amkb.Store`
- `transaction.py` — `SpikuitStoreTransaction` satisfying
  `amkb.Transaction` (drives `Circuit.transaction()`'s async
  `__aenter__`/`__aexit__` across separate bg-loop submissions)
- `mapping.py` — Neuron ↔ Node, Synapse ↔ Edge, datetime
  → `Timestamp`, rel → `SynapseType`
- `_loop.py` — persistent background asyncio loop so aiosqlite
  stays pinned to a single thread for the store's lifetime
- `_ids.py` — `pre|post|rel` triple codec for AMKB `EdgeRef`s
- `__init__.py` — public surface

Conformance (`pytest spikuit-agents/tests/test_amkb_conformance.py`):

| Level | Pass | Skip | Notes |
|---|---|---|---|
| L1 core | 16 | 0 | — |
| L2 lineage | 5 | 1 | `KIND_CATEGORY` not in v0.7.x |
| L3 transactional | 0 | 7 | No concurrent tx, no `revert()` — v0.8+ |
| L4a structural | 5 | 2 | `derived_from` / `attested_by` have no `SynapseType` counterpart |
| L4b intent | 5 | 2 | Free-form attr filter; trivially-true ordering case |

**Total**: 31 passed / 12 skipped / 0 failed. No regressions
(`spikuit-core` 330 / `spikuit-agents` 39). Adapter-only release:
`spikuit-core` gained one helper (`Database.get_neuron_retired_at`)
and is otherwise unchanged.

The L3 skip block is the main v0.8+ debt: Spikuit's `Circuit`
forbids nested transactions (`TransactionNestingError`) and the
adapter has no `revert()`, so concurrent MVCC and rollback will
both need engine work before that level can light up.

## Dependency with v1.0.0 feature issues

Several v1.0.0 issues can reuse the v0.7.0 plumbing for free and
become easier to land on top of it. This is the reason to insert
v0.7.x before v1.0.0 rather than after.

| Issue | Title | Why AMKB plumbing helps |
|---|---|---|
| #12 | Conversational Curation — graph editing in /learn | Transactions + event log give the /learn session a replayable audit trail without inventing one |
| #13 | Feedback queue — separate proposal from application | Proposal = ChangeSet not yet committed; application = commit. Natural fit |
| #17 | Conflict detection — find contradictory neurons | Needs lineage to explain _why_ two neurons are contradictory; predecessor chain is that lineage |

These issues stay in v1.0.0 but become lower-risk after v0.7.x.
Milestone reordering is not required.

## Rollout sequence

1. **Cut branch.** `amkb-integration` from `main` at v0.6.2 (done).
2. **Write design docs.** This file + `amkb-core-plumbing-spec.md`
   land in `docs/design/` first, for review _before_ any code.
3. **v0.7.0 implementation.** DB migrations, transaction wrapper,
   event log, soft-retire. Each behavior behind its own test.
   Every existing test must stay green after each step.
4. **v0.7.1 implementation.** Adapter in `spikuit-agents/amkb/`.
   Conformance suite wired up. CI job added.
5. **Rebase on main.** If v0.6.3 has shipped by then, rebase
   `amkb-integration` and re-run tests. Non-overlapping areas
   mean rebase should be trivial. (The feature originally slated
   for v0.6.4 — External SKILL.md import — is re-targeted to
   v0.7.2 so it can land on top of the AMKB plumbing rather than
   force a reversed-semver ordering; see Risks §1.)
6. **PR + merge.** Two PRs (one per milestone) so review is
   chunked. Release notes call out "AMKB Protocol support is opt
   in; existing CLI usage is unchanged."

## Non-goals for v0.7.x

- **No `spkt amkb` CLI.** The adapter is programmatic only this
  round. A CLI surface can come later.
- **No Spikuit-side break of `amkb-sdk`.** If the adapter surfaces
  a gap in the SDK (missing Store method, missing error code),
  the fix lands in `amkb-sdk` first and `amkb-integration`
  consumes the new version.
- **No retrieval semantic change.** `retrieve` keeps returning
  Spikuit's APPNP+semantic+FSRS-retrievability scores. AMKB
  callers see those same scores unchanged — AMKB does not
  prescribe an ISF, so Spikuit's function satisfies the L4b
  contract as-is.
- **No resurrection semantics.** Reverting a retire/merge is out
  of scope until the protocol and Spikuit agree on what
  "unretire" means in the presence of FSRS state. Conformance
  tests that require resurrection are left capability-skipped,
  same as the dict test store.

## Risks

- **Rebase pain if v0.6.3 touches `spikuit-core/db.py`.** v0.6.3
  (TutorSession migration) is in a different subsystem so
  overlap is unlikely. The originally planned v0.6.4 (External
  SKILL.md import) **would** have touched `db.py` and landing
  it before v0.7.0 creates a reversed-semver situation — you
  cannot cut v0.6.4 after v0.7.0 has shipped without running
  an LTS branch, which Spikuit does not. **Decision:** ship
  AMKB plumbing as v0.7.0 first and re-target External SKILL.md
  import to v0.7.2 so it lands on top of the new schema. The
  v0.6.4 label is retired.
- **Transaction wrapper complexity.** Buffering writes without
  breaking the async auto-commit model is the riskiest piece.
  Mitigation: ship the wrapper first, with its own pytest
  coverage, before building anything on top.
- **Event log growth.** An always-on event log grows unbounded.
  v0.7.0 ships with no pruning — this is acceptable while the
  feature is opt-in, but v1.0.0 needs a retention policy
  (separate issue).
- **Adapter depends on `amkb==0.0.1` which is intentionally
  unusable.** Resolved by consuming `amkb-sdk` as a git dependency
  pinned to an exact rev in the workspace root `pyproject.toml`
  (originally an editable path source at ship time). A proper
  `amkb>=0.1.0` PyPI pin still needs to happen before this repo is
  published externally.

## Success criteria — all met as of v0.7.1 ship

- [x] v0.7.x merges to main with zero regressions in existing
      `spikuit-core` / `spikuit-cli` tests (core 330 pass, agents
      39 pass on 2026-04-13)
- [x] `pytest spikuit-agents/tests/test_amkb_conformance.py` passes
      L1/L2/L4a/L4b (31 passed, 12 capability-skipped)
- [x] No `amkb.*` import appears in `spikuit-core`
- [x] No Spikuit internal type (Neuron, Synapse, Circuit) appears
      in any AMKB-facing API (all translation lives in
      `spikuit_agents.amkb.mapping`)
- [x] `spkt` CLI behavior is byte-identical to v0.6.2 for every
      existing subcommand under test coverage, with one
      deliberate exception: `spkt stats --json` gains additive
      fields (`neurons_retired`, related counts). No existing
      field changes semantics. No other command's output
      drifted
- [x] `retrieve` recall@k unchanged on a zero-retired fixture,
      within noise on a 30%-retired fixture (ANN index is
      physically cleaned on retire)
