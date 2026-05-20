# Substrate Self-Organization — Noise Resilience & Sub-Linear MAC

**Status.** **Design proposal (draft).** Scheduled as the v0.8.x
milestone — see `roadmap.md` §4.2 and §5 for the per-release
breakdown. Companion to `amkb-integration-plan.md` (shipped v0.7.x)
and `amkb-core-plumbing-spec.md`. Written 2026-05-20.

**Provenance.** This document re-homes the substrate-facing half of
an `rl-research` design session (#33 SAGE). That session's working
note —
`agent-workspace/contexts/active/spikuit-amkb-v03-tutor-extraction.md`
— originally framed the ideas below as an **amkb protocol v0.3**
extension (a "7-verb cognitive API"). Reading the actual `amkb-spec`
showed that framing was wrong: the verbs proposed there describe the
*Spikuit substrate*, not the protocol. This doc is the corrected
home for them. See §1.

## 1. Why this is a Spikuit doc, not an amkb-spec change

The rl-research note proposed adding verbs (`encode`, `record_use`,
`curate`, `stat`) and a new conformance level to `amkb-spec`. That
is not viable, and not because of a naming clash:

- `amkb-spec` v0.2 is a **17-operation transaction-owned graph
  protocol** (`create`/`rewrite`/`retire`/`merge`/`link`/`unlink`/
  `get`/`find_by_attr`/`neighbors`/`retrieve`/`begin`/`commit`/
  `abort`/`history`/`diff`/`revert`/`events`). The proposed 7 verbs
  would *replace* that model, not extend it.
- The protocol **deliberately excludes** exactly what the proposal
  adds. `00-overview` lists "scheduling and activation dynamics …
  pressure/decay" as a non-goal: "An AMKB is a graph store with
  lineage and events; it is not a learning system." Rationale R4
  rejects an `ingest`/`encode` operation (ingestion is a transaction
  pattern). R8 rejects a retrieval-quality benchmark in the spec
  ("would force all implementations toward a single retrieval
  strategy"). R13 makes relevance implementation-defined.
- Conformance levels L1–L5 (Core / Lineage / Transactional /
  Structural+Intent / Policy) are all assigned; there is no free
  "Resilience" slot, and per R8 a resilience benchmark would not
  belong in the spec anyway.

The shipped architecture already draws the line in the right place.
`amkb-integration-plan.md` constraint 1: **"No core-logic leakage
into AMKB surface. APPNP, FSRS, pressure dynamics, community
detection, and embedder internals MUST NOT appear in any type,
method, or event that the adapter exposes."** Noise resilience is
built *from* exactly those internals. It is therefore a property of
`spikuit-core` (the substrate), surfaced — if at all — as a Spikuit
extension, never as an amkb operation.

**Decision (2026-05-20, with user).** `amkb-spec` stays as-is. The
behaviors below are `spikuit-core` substrate design. The amkb
adapter is unaffected unless §4 says otherwise.

## 2. Positioning — Spikuit's differentiator

Most RAG/KB research optimizes one of two axes: retrieval precision
(HyDE, GraphRAG, rerankers) or explainability (citations, source
highlighting). Spikuit's substrate competes on a third, near-empty
axis: **self-organization** — the store stays clean and cheap to
maintain *on its own* as noisy material accumulates.

Concretely, the substrate aims to make two claims true:

1. **Noise resilience.** Material later judged wrong is demoted by
   accumulated human dispute signal, and stops surfacing in
   retrieval — without a human editing the graph by hand.
2. **Sub-linear MAC.** *Maintenance-Attention Cost* — human
   intervention time — grows sub-linearly in ingested volume. This
   is the Spikuit-paper H2 hypothesis (see
   `contexts/active/spikuit-cognitive-memory-model.md`).

These are **Spikuit** claims, measured by a **Spikuit** (or future
`amkb-bench`-style) evaluation harness — not amkb conformance. Per
R8 the protocol does not pick a retrieval winner; Spikuit is free to.

## 3. Substrate behaviors

The rl-research note's "7 verbs" are not new operations. They are a
coarse conceptual view of substrate capabilities, most of which
already exist. The table separates what ships today from what this
doc proposes.

| Conceptual verb | Existing `spikuit-core` reality | Proposed in this doc |
|---|---|---|
| `encode` | `add_neuron` + ingest paths | — (no change) |
| `link` | `add_synapse` | — |
| `retrieve` | `circuit.retrieve` (APPNP + semantic + FSRS) | §3.2 cold-component mode |
| `record_use` | `circuit.fire(id, grade)` | §3.1 signed weight |
| `curate` | `merge_neurons`, soft-retire, `spkt domain audit`, curator agent | §3.3 dispute-driven demotion policy |
| `subscribe` | `circuit.events()` | §3.4 two new event kinds |
| `stat` | `spkt stats` | §3.5 four new metrics |

### 3.1 Signed use signal

`circuit.fire` today takes a grade — `miss` / `weak` / `fire` /
`strong` — that drives FSRS (Again/Hard/Good/Easy) plus STDP edge
updates and APPNP propagation.

A failed recall (`miss`) is **not** the same as disputed content.
`miss` means "the learner could not retrieve this"; it is a
scheduling signal. The substrate currently has no signal for "this
atom is *wrong*". This doc adds that second axis as a **signed real
weight** `w ∈ [-1, +1]` accepted alongside (or derived from) the
grade:

| `w` | meaning | substrate response |
|---|---|---|
| `+1.0` | correct / strongly used | STDP LTP, retrieval pressure up |
| `+0.3` | weak hit | mild LTP |
| `0` | neutral (debug read) | no change |
| `-0.3` | hit but not adopted | mild LTD |
| `-1.0` | explicit dispute | strong LTD, synapse decay |

**Threshold response (mandatory).** A single `-1.0` MUST NOT retire
an atom. Demotion requires **N independent dispute signals from
distinct contexts** (N tunable, default ≥ 3). This guards against a
single mistaken downvote erasing knowledge. Demotion is
soft-retire-adjacent: the atom loses retrieval pressure first, and
is only soft-retired (`amkb-core-plumbing-spec.md` §2.1) once
disputes pass the retire threshold.

This is the corrected form of the note's `record_use` verb. It is
`fire` generalized, not a new API surface.

### 3.2 Cold-component retrieve mode

As the graph grows, isolated/low-traffic components ("cold
islands") add retrieval cost without adding value. Proposed:
`retrieve` gains a mode — `default` / `deep` / `all`:

- `default` — skip components below a heat threshold. Cheaper,
  hides stale islands.
- `deep` — include cold components (the false-negative safety net).
- `all` — no component filtering.

**amkb boundary.** `amkb-spec` fixes `retrieve(intent, *, k, layer,
filters)`. The mode is **not** a new protocol parameter. Options:
(a) Spikuit-only kwarg on `circuit.retrieve`, invisible to the
adapter; (b) carry it through the `filters` algebra under an `ext:`
namespace (the spec explicitly permits `ext:` filter kinds). Prefer
(a) for the substrate; expose via (b) only if an amkb consumer
needs it. Either way the protocol surface is unchanged.

An audit hatch — `stat("hidden_islands")` — lists what `default`
mode is currently suppressing, so cold filtering never becomes a
silent black hole. An external link into a cold component re-warms
it on the next propagation pass.

### 3.3 Dispute-driven demotion as a curation policy

`curate` in the note is not a missing operation — Spikuit already
curates via `merge_neurons`, soft-retire, `spkt domain audit`, and
the curator agent. What is new is a **policy**: the substrate
should, on its own schedule, act on accumulated dispute signal
(§3.1) and cold-component state (§3.2) to demote and eventually
soft-retire noise, with a dry-run/apply split so the curator agent
can preview. This reuses the shipped transaction + event log; no
new primitive.

### 3.4 New events

Two `spikuit-core` event kinds, additive to the `event` table's
`op` enum (`amkb-core-plumbing-spec.md` §2.4):

- `atom.demoted` — an atom crossed the dispute threshold and lost
  retrieval pressure.
- `component.cooled` — a component dropped below the heat threshold
  and is now `default`-mode hidden.

Whether these reach the **adapter's** amkb event stream is a
mapping-layer decision. The plumbing spec already filters
core-internal drift (pressure, STDP, FSRS) out of amkb-visible
events (§5). `atom.demoted` is structural-ish and could surface;
`component.cooled` is substrate-internal and probably should not.
Decide when the mapping layer is revisited — not now.

### 3.5 New stat metrics

`spkt stats` gains four fields, additive exactly like
`neurons_retired` was in v0.7.0 (`amkb-core-plumbing-spec.md` §7.6):

| metric | definition (sketch) |
|---|---|
| `noise_resilience_score` | precision recovery rate after injected dispute — the headline eval number |
| `island_count` | number of disconnected components |
| `cold_component_ratio` | cold components / total components |
| `dispute_recovery_rate` | fraction of disputed atoms demoted within K subsequent queries |

`noise_resilience_score` is the metric a Spikuit eval harness (or
`amkb-bench`) would track over time. It is **not** an amkb
conformance test.

## 4. What changes in amkb (nothing, almost)

- **`amkb-spec`: no change.** No new verb, no new conformance level.
- **`amkb-sdk`: no change.**
- **The adapter (`spikuit-agents/amkb/`):** unchanged unless §3.4
  decides to surface `atom.demoted`. If a richer retrieval hit is
  ever wanted (the note's S1: `provenance`, `confidence_breakdown`,
  `component_id`, `component_heat`), it should be a **Spikuit
  extension hit type** with extra attributes — amkb consumers keep
  seeing `RetrievalHit{ref, score}`. No `amkb-spec` PR is needed for
  any of this.

## 5. Relationship to the app-layer split

A separate workstream — extracting `spikuit-tutor` and
`spikuit-agent-rag` packages and treating FSRS as a tutor-app
overlay — is tracked in
`contexts/active/spikuit-amkb-v03-tutor-extraction.md` (H3, staged
extraction). It is **not** in scope here. The only connection: once
that split lands, the substrate behaviors above stay entirely inside
`spikuit-core`, and the tutor/rag apps observe them through
`amkb.Store` plus a Spikuit-core extension interface — never via raw
`from spikuit_core import`.

## 6. SAGE correspondence (sanity check)

The SAGE paper's layers map onto this substrate, confirming the
design is not missing a structural piece:

| SAGE component | Spikuit substrate |
|---|---|
| triple-extraction Writer | Neuron + Synapse creation |
| graph-structure learning | community detection / spectral / eigentheme |
| soft addressing (all-node scoring) | APPNP + R×I×R |
| evaluation propagation | STDP + signed use signal (§3.1) |
| Writer/Reader co-training (RL) | **no counterpart** — Spikuit evolves via human + curator agent, not co-trained RL |

Writer/Reader co-training is deferred to a post-v1.0 evaluation; if
adopted it is digested inside the substrate and needs no protocol
change.

## 7. Open questions

These are flagged for review, not decided.

1. **Dispute threshold N** and what counts as an "independent
   context" — needs a concrete rule before §3.1 is implementable.
2. **Heat metric** for cold-component detection — reuse APPNP
   stationary mass, or a separate decay counter?
3. **Do `atom.demoted` events surface through the adapter?** (§3.4)
4. **Milestone.** ~~L3 transactional conformance is already the named
   v0.8 debt; does self-organization share v0.8?~~ **Resolved in
   `roadmap.md`** (OQ4): L3 is pulled forward to v0.7.2 as a
   prerequisite, and substrate self-organization owns v0.8.0–v0.8.2.

## 8. Cross-references

- `amkb-integration-plan.md` — shipped v0.7.x core/adapter split.
- `amkb-core-plumbing-spec.md` — event log, soft-retire, transaction
  wrapper this doc builds on.
- `agent-workspace/contexts/active/spikuit-amkb-v03-tutor-extraction.md`
  — originating rl-research note + app-layer split (H3).
- `agent-workspace/contexts/active/spikuit-cognitive-memory-model.md`
  — MAC sub-linearity (H2), R×I×R.
- `amkb-spec` `spec/00-overview.md` (non-goals), `spec/99-rationale.md`
  (R4, R8, R13) — why none of this belongs in the protocol.
