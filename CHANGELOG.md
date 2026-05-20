# Changelog

All notable changes to Spikuit are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/); Spikuit uses
[semantic versioning](https://semver.org/) — pre-1.0, a minor bump may
carry breaking changes.

This log begins at v0.9.0; earlier releases predate it.

## [0.9.0] — 2026-05-20

### Tutor extraction, Stage 2 — FSRS leaves the substrate

Stage 2 (`docs/design/tutor-extraction-stage2.md`) retires the learner
model from `spikuit-core`. FSRS card state and scheduling now live
wholly in `spikuit-tutor`; the substrate is a knowledge-graph engine
that no longer knows what a "review" or a "due card" is.

This release is **not additive** — it is a substrate refactor plus a
data migration. Run the migration script before relying on the upgrade
(see *Migration* below).

### Breaking

- **`fsrs_state` table retired from `spikuit-core`.** FSRS card state
  moves to a `spikuit-tutor`-owned overlay DB (the `fsrs_card` table,
  default path `<substrate-stem>.tutor.db`). `spikuit-core` no longer
  depends on the `fsrs` package — enforced by CI.
- **`appkit` contract reshaped.** `compute_scaffold`, `Scaffold` and
  `ScaffoldLevel` are removed from `spikuit_core.appkit` (they move to
  `spikuit_tutor`). The `SchedulerCircuit` Protocol is renamed
  `SubstrateView` and reshaped — it no longer schedules. `appkit`
  `__all__` is now `Grade, Spike, NeuronView, SubstrateView`.
- **`spkt retrieve` re-ranks.** The retrieval score no longer includes
  the FSRS retrievability term — the substrate ranks by its own
  signals only (`text_sim`, `centrality`, `pressure`, `boost`).
  Results shift accordingly. Memory-aware retrieval can return later as
  a tutor feature layered over `retrieval_boost`.
- **`spkt progress` → `spkt tutor progress`.** The learner-facing
  progress report is tutor domain and moved under a new `tutor`
  command group.
- **`Circuit.fire` returns `None`** (was an FSRS `Card`). Review
  orchestration inverts: the tutor session loads, schedules and
  persists the card, then calls `substrate.fire(spike)` for graph
  plasticity only.
- **`Circuit.stats` drops `cards_loaded`.** The tutor reports its own
  card count.
- **`due_neurons` / `near_due_neurons` / `get_card` / `progress`
  removed from `Circuit`.** They are FSRS queries — reimplemented in
  `spikuit-tutor`'s `TutorScheduler` over the overlay store.

### Changed

- `consolidate` and `diagnose` triage on substrate-native `spike`-table
  signals (count, recency, grade distribution) instead of FSRS
  stability. A coarser signal, but the substrate now self-assesses from
  its own event log rather than borrowing the tutor's memory model.
- `compute_scaffold` and `compute_progress` read FSRS state from the
  tutor overlay; graph topology still comes from the substrate live,
  through the new `Circuit.edge_type` and public `Circuit.get_spikes_for`.
- FSRS cards are created lazily on first review (previously: eagerly at
  neuron creation). A never-reviewed neuron still surfaces as "due"
  through the tutor's lazy-card union of past-due cards and uncarded
  neurons.

### Added

- `spikuit_tutor.TutorStore` — the FSRS overlay database, with
  reconcile-on-open orphan-card pruning.
- `spikuit_tutor.TutorScheduler` — the tutor's FSRS engine and review
  orchestrator.
- `scripts/migrate_fsrs_to_tutor.py` — the Stage 2 data migration
  (`--dry-run`, `--reverse`, `--brain` / `--db-path`).
- `tools/check_core_no_fsrs.py` — CI check asserting `spikuit-core/src`
  contains no `import fsrs`.

### Migration

Run `scripts/migrate_fsrs_to_tutor.py` to copy FSRS card state from the
old `fsrs_state` table into the new tutor overlay:

```sh
uv run python scripts/migrate_fsrs_to_tutor.py --dry-run   # preview
uv run python scripts/migrate_fsrs_to_tutor.py             # migrate
```

The migration is idempotent and does **not** drop `fsrs_state` — the
table is left dormant for one release so that a rollback is a pure code
revert with no data loss. `--reverse` copies the overlay's cards back
into `fsrs_state` for the case where reviews happened post-migration.
The `DROP TABLE fsrs_state` ships in a later release.
