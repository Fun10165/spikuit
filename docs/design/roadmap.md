# Spikuit / AMKB — Roadmap

**Status.** Living roadmap. Redrawn 2026-05-20 to absorb the
substrate self-organization design (`substrate-self-organization.md`)
and to correct the AMKB version model. Supersedes the 2026-04-13
roadmap note that lived only in agent-workspace memory.

**Scope.** Three coupled repositories on one release cadence:

- **`amkb-spec`** — the normative AMKB protocol (documents, not code).
- **`amkb-sdk`** — the `amkb` Python package implementing the spec.
- **`spikuit`** — the AMKB reference implementation (`spikuit-core`
  substrate + `spikuit-agents/amkb` adapter + `spkt` CLI).

They version independently but move together: `spikuit` consumes
`amkb`, and `amkb` conforms to `amkb-spec`.

## 1. Snapshot (2026-05-20)

| Repo | Version | State |
|---|---|---|
| `amkb-spec` | `v0.2.0` (tagged) | `spec/` 00–05 + 99 complete; `conformance/` scaffolded for L1–L4b; `schema/`, `examples/` still empty. README metadata stale (claims 0.1.0). |
| `amkb-sdk` | `v0.0.1` (PyPI placeholder) | `amkb.*` store helpers extracted; tracks `amkb-spec` v0.2 surface. No real release yet. |
| `spikuit` | `v0.7.1` | AMKB adapter shipped — conformance L1/L2 pass, L4 partial. L3 (Transactional) and L5 (Policy) outstanding. `amkb` pinned via git source, not PyPI. |

**Conformance levels** (assigned by `amkb-spec`, fixed): L1 Core /
L2 Lineage / L3 Transactional / L4a Structural / L4b Intent /
L5 Policy. All five are taken — there is no free slot, and no
"Resilience" level (see §2).

## 2. amkb-spec track

`amkb-spec` is a deliberately minimal graph-CRUD + lineage + events
protocol (17 operations, transaction-owned). It continues on its own
track toward `v1.0.0`; the substrate work in §5 contributes **nothing**
to it.

**No "cognitive API" rewrite.** An earlier design thread proposed a
7-verb cognitive protocol (`encode`/`record_use`/`curate`/`stat`/…)
and a new conformance level. That was rejected (decision 2026-05-20):
it would *replace* the protocol model, and the additions it wanted —
use-signal, scheduling/activation, a retrieval-quality benchmark — are
exactly what `amkb-spec` excludes by design (00-overview non-goals,
rationale R4/R8/R13). Those behaviors are now `spikuit-core` substrate
design; see `substrate-self-organization.md` §1.

A future `amkb-spec` `v0.3` is still possible — but for protocol
maturation, not the cognitive rewrite:

| Milestone | Content |
|---|---|
| housekeeping | Fix stale README/version metadata (0.1.0 → 0.2.0). `chore`. |
| `v0.3` (tentative) | Finish `conformance/` test suite (currently scaffold only); add L5 Policy test matrix; refine operation edge cases surfaced by the `spikuit` adapter. |
| `v0.4` (tentative) | `schema/` — JSON Schema / reference types. `examples/` — worked transaction patterns. |
| `v1.0.0` | Spec frozen; conformance suite complete L1–L5; proven by ≥1 conforming implementation (`spikuit`). |

**`amkb-bench` is out of scope for `amkb-spec`.** Per R8 the protocol
does not pick a retrieval-quality winner. Any noise-resilience or
retrieval benchmark — including `noise_resilience_score` (§5) — lives
in a future separate `amkb-bench` project, never in `amkb-spec`
conformance.

## 3. amkb-sdk track

| Milestone | Content |
|---|---|
| `v0.1.0` | First real release. Implements the `amkb-spec` v0.2 17-op surface + `amkb.Store` + shared helpers. Published to PyPI. Ships in lockstep with `spikuit` v0.7.2 (which then drops the git-source pin). |
| `v0.2.x+` | Tracks `amkb-spec` minor versions. Additive only within a major. |
| `v1.0.0` | Aligns with `amkb-spec` v1.0.0. |

## 4. spikuit track

Four lines. v0.7.x finishes the AMKB adapter; v0.8.x is the substrate
self-organization milestone (the headline of this redraw); v0.9.x is
the feature/UX line; v1.0.0 is the daily-use landing.

### 4.1 v0.7.x — Adapter & conformance completion

| Version | Theme |
|---|---|
| `v0.7.1` ✅ | AMKB adapter shipped (`spikuit_agents.amkb.*`). Conformance L1/L2 + partial L4. |
| `v0.7.2` | **Conformance completion** — L3 (Transactional), full L4 (Structural+Intent), L5 (Policy once `amkb-spec` scaffolds it). Release `amkb-sdk` v0.1.0 to PyPI and migrate the `spikuit` dependency from git-source pin to the PyPI version. |
| `v0.7.3` | External `SKILL.md` import (carried from the 2026-04-13 plan). Tutor Intelligence — follow-up generation, interleave quality, gap detection. |

L3 transactional conformance was previously logged as "v0.8 debt"
(`amkb-integration-plan.md`). It is **pulled forward to v0.7.2**: the
substrate demotion policy (§5, v0.8.2) reuses the shipped transaction
+ event log, so transaction maturity must precede the v0.8.x work.

### 4.2 v0.8.x — Substrate self-organization

The new milestone. Makes `spikuit-core` deliver the two claims in
`substrate-self-organization.md` §2: **noise resilience** and
**sub-linear MAC** (Maintenance-Attention Cost). Detail in §5.

| Version | Theme |
|---|---|
| `v0.8.0` | Measurement foundation — signed use signal (`w ∈ [-1,+1]`), four new `spkt stats` metrics. Resolve open questions OQ1 (dispute threshold N) + OQ2 (heat metric). |
| `v0.8.1` | Cold-component retrieve mode (`default`/`deep`/`all`), two new core events (`atom.demoted`, `component.cooled`). Resolve OQ3 (adapter surfacing). |
| `v0.8.2` | Dispute-driven demotion policy with dry-run/apply split. Noise-resilience eval harness producing `noise_resilience_score`. |

### 4.3 v0.9.x — Feature & UX line

The feature backlog from the 2026-04-13 plan, shifted out of v0.8
because substrate self-organization now occupies it. Themes, not yet
pinned to point versions:

- GUI / Web UI MVP — stateless renderer, graph visualization, neuron
  add/review from the browser; structural ("spectral") layout drop-in.
- Batch diff ingest — diff-aware document re-ingest for token savings.
- Table / Media attachment — body as a lightweight index, partial
  retrieve.
- Spectral retrieval — eigentheme profile, hub-weight, theme-weight.
- Theme audit — `domain audit --theme-drift`, curator integration.
- Curator agent brain — sibling brain `.spikuit/agent/`, auto
  reflection, `spkt reflect`, MAC metrics.
- Tutor / QABot reflection — extend the curator mechanism to other
  skills, cross-skill learning.

Interleaved with this: a **daily-use polishing phase** — the user
runs Spikuit daily, adds domain extractors as needed, and the
tutor/qabot experience is tuned on accumulated real data. Versions
advance as small v0.9.x point releases through this phase.

### 4.4 v1.0.0 — Daily Use Ready

Implemented only after daily use has validated the substrate:

- Multi-brain (vault-style separation) + adapter abstraction merge.
- Cloud archive — S3/GCS export.
- Agent-loop SDK / curator agent maturity.
- Retrieval benchmark + paper infrastructure.
- Learning-effect evaluation.

`v1.0.0` is the semver landing point for "Daily Use Ready" — the name
is fixed; the content is whatever survived daily-use validation.

## 5. Substrate self-organization milestone (detail)

Full design: `substrate-self-organization.md`. That document is the
*what*; this section is the *when*. It maps the design's §3 behaviors
onto the v0.8.x point releases and lists the gates.

| Design § | Behavior | Lands in |
|---|---|---|
| §3.1 | Signed use signal — `circuit.fire` accepts `w ∈ [-1,+1]`; `-1.0` = explicit dispute, drives LTD + synapse decay. | `v0.8.0` |
| §3.5 | Four new `spkt stats` metrics — `noise_resilience_score`, `island_count`, `cold_component_ratio`, `dispute_recovery_rate`. | `v0.8.0` |
| §3.2 | Cold-component retrieve mode — `default` skips low-heat components, `deep`/`all` include them; `stat("hidden_islands")` audit hatch. | `v0.8.1` |
| §3.4 | Two new `spikuit-core` events — `atom.demoted`, `component.cooled` (additive to the `event.op` enum). | `v0.8.1` |
| §3.3 | Dispute-driven demotion policy — substrate acts on accumulated dispute + cold-component state to demote/soft-retire noise; dry-run/apply split for the curator agent. | `v0.8.2` |

**Gates** — the design's §7 open questions, owned by the roadmap:

- **OQ1 (v0.8.0 gate).** Dispute threshold `N` and what counts as an
  "independent context". A single `-1.0` MUST NOT retire an atom;
  demotion needs `N ≥ 3` independent disputes. The concrete rule must
  be decided before §3.1 is implementable.
- **OQ2 (v0.8.0 gate).** Heat metric for cold-component detection —
  reuse APPNP stationary mass, or a separate decay counter.
- **OQ3 (v0.8.1 gate).** Whether `atom.demoted` / `component.cooled`
  surface through the amkb adapter's event stream — a mapping-layer
  decision (`amkb-core-plumbing-spec.md` §5 already filters
  core-internal drift).
- **OQ4 — resolved here.** The design asked whether self-organization
  shares v0.8 with the L3 transactional debt. Resolution: L3 is
  pulled to **v0.7.2** (§4.1), so it is a *prerequisite* of v0.8.x,
  not a co-tenant. Substrate self-organization owns v0.8.x cleanly.

**amkb surface.** This milestone touches no `amkb-spec` operation and
no `amkb-sdk` type. The richer retrieval hit the design floats (S1:
`provenance`, `confidence_breakdown`, `component_id`, `component_heat`)
ships, if at all, as a **Spikuit extension hit type** — amkb consumers
keep seeing `RetrievalHit{ref, score}`. No `amkb-spec` PR is required
(`substrate-self-organization.md` §4).

## 6. Tutor / agent-rag extraction workstream

A parallel, mostly orthogonal workstream tracked in
`agent-workspace/contexts/active/spikuit-amkb-v03-tutor-extraction.md`
(H3). It extracts `spikuit-tutor` and `spikuit-agent-rag` as packages
and treats FSRS as a tutor-app overlay. Staged because FSRS currently
leaks across `spikuit-core` and `spikuit-cli`:

| Stage | Content | Slot |
|---|---|---|
| Stage 0 | Python package boundary only — carve `spikuit-tutor/`, move `tutor/`+`quiz/` out of `spikuit-cli`, forbid `from spikuit_core` (CI lint). DB schema untouched. | Any v0.7.x point release — low risk, independent. |
| Stage 1 | Tutor-app owns overlay state; still reads/writes core FSRS columns by contract; no direct import. | v0.8.x window. |
| Stage 2 | DB migration — retire FSRS columns from core, move to tutor-app SQLite, joined by `atom_id`. **Not additive** — needs its own session and migration plan. | v0.9.x. |

Once the split lands, the §5 substrate behaviors stay entirely inside
`spikuit-core`; tutor/rag apps observe them through `amkb.Store` plus
a Spikuit-core extension interface, never via raw
`from spikuit_core import` (`substrate-self-organization.md` §5).

## 7. Sequencing — open questions

Decided enough to start; flagged for the user, not frozen.

1. **Substrate vs. feature ordering.** This redraw gives v0.8.x to
   substrate self-organization and pushes the GUI/feature line to
   v0.9.x. The 2026-04-13 plan had the GUI MVP at v0.8.0. If browser
   UX is wanted sooner, v0.8 and v0.9 can be interleaved instead of
   sequenced — a product call left to the user.
2. **Tutor extraction Stage 0 timing.** Independent and low-risk; it
   can land in v0.7.2 or v0.7.3 opportunistically rather than waiting
   for a dedicated slot.
3. **GitHub Milestones.** This roadmap should be mirrored into GitHub
   Milestones (`v0.7.2` / `v0.7.3` / `v0.8.0`–`v0.8.2`), with stale
   `v1.0.0`/`v2.0.0`/`v3.0.0` milestones from the old plan retired and
   their issues reassigned.

## 8. Cross-cutting principles

Hold across every milestone above:

- **Four skills, fixed.** `tutor` / `qabot` (primary) + `learn` /
  `curator` (meta). New capability is absorbed into an existing skill,
  never added as a fifth.
- **RAG and Study are peers.** Do not over-index on the tutor.
- **Accuracy is not assumed.** LLM accuracy is not the lever;
  correctness is carried by architecture.
- **DB changes are additive only** — the AMKB constraint. The one
  sanctioned exception is tutor-extraction Stage 2 (§6), which removes
  columns and therefore needs an explicit migration plan.
- **No core-logic leakage into the AMKB surface.** APPNP, FSRS,
  pressure dynamics, community detection, and embedder internals MUST
  NOT appear in any amkb type, method, or event
  (`amkb-integration-plan.md` constraint 1).

## 9. What changed from the 2026-04-13 roadmap

| Then (2026-04-13) | Now (2026-05-20) |
|---|---|
| v0.8.0–v0.8.6 packed with GUI, batch ingest, attachments, spectral retrieval, theme audit, curator, reflection. | Those become the v0.9.x feature line (§4.3). |
| No substrate self-organization milestone. | v0.8.x is now substrate self-organization (§4.2, §5). |
| L3 transactional conformance = unscheduled "v0.8 debt". | Pulled forward to v0.7.2 — prerequisite for v0.8.x (§4.1, OQ4). |
| "amkb v0.3" implied a cognitive-protocol expansion. | Dropped. `amkb-spec` stays a minimal graph protocol; a future v0.3 is maturation only (§2). |
| Roadmap lived only in agent-workspace memory. | Lives here, in-repo, version-controlled. |

## 10. Cross-references

- `substrate-self-organization.md` — the v0.8.x design (this roadmap
  schedules it).
- `amkb-integration-plan.md` — shipped v0.7.x core/adapter split.
- `amkb-core-plumbing-spec.md` — event log, soft-retire, transaction
  wrapper the substrate work builds on.
- `agent-workspace/contexts/active/spikuit-amkb-v03-tutor-extraction.md`
  — the originating design thread and the §6 extraction workstream.
- `amkb-spec` `spec/00-overview.md`, `spec/99-rationale.md` — why the
  protocol stays minimal.
