# Neuron Importance — `importance = f(state, importance_prior)`

**Status.** **Design proposal (draft).** No schema change yet — this doc
captures the architectural commitment so future PRs have a reference
point. Written 2026-05-23.

**Provenance.** Emerged from a daily-use review session between the
maintainer and an AI agent (Claude) while curating French vocabulary
neurons. The triggering observation was that reviewing ~200 newly
imported items with **flat priority is painful** — high-value idioms
and low-value cognates compete for the same review budget. The
discussion progressed: simple `importance` column → 2-layer
(`base + derived`) → fully-derived → vague "hybrid" → **a pure
function of two explicit inputs**, `state` and a Bayesian-flavored
**prior** (specifically `importance_prior` for the importance
function). The earlier "hybrid" framing was rejected because
*hybrid* left the boundary between the components unspecified; this
doc records the sharper commitment. The name `prior` was chosen
over `initial` after recognizing that the input is metric-scoped
(each metric has its own prior, possibly with different shape) and
that "initial" alone fails to say *initial of what*.

**Scope.**

*In scope:*
- The neuron scalar-metric **framework**: signature
  `state × prior → [0, 1]` (where `prior` is metric-scoped),
  purity, versionability, codomain contract (§2).
- Definition of **`importance`** as the framework's first
  inhabitant — the metric used for **review triage and gradation**
  at bulk-import time and for FSRS `desired_retention` mapping.
- The grounding (neuroscience / cognitive science) that justifies
  *this* `f` deserving the name "importance" (§4.1).
- Observation-phase plan for validating the design without schema
  change (§6).

*Out of scope, deferred to follow-up docs:*
- **Visualization emphasis** (star magnitude in `spkt visualize`).
  The metric driving visual prominence may not be the same as the
  metric driving review scheduling — visualize likely wants
  graph-topological emphasis (centrality / community), not
  subjective user value. Conflating them would distort the
  starfield.
- **Cousin metrics** that share the framework's signature —
  `salience`, `centrality`, `novelty`, `recency`. Sketched in §9 so
  future PRs can plug into the same contract, but their definitions
  are not committed here.

## 1. The question

When a neuron is imported or curated, what is its "importance" to the
user, and where does that value live?

Two extremes:

- **A. First-class stored attribute** — `neuron.importance` REAL
  column, user-set via `--imp` flag, persisted, read directly.
- **B. Fully derived** — `importance(n)` is a function of the
  surrounding graph state (synapse degree, co-fire counts, retrieve
  hit log), computed on read, never stored as a field on `neuron`.

Both have failure modes:

- **A** is an architectural smell against Spikuit's premise. Spikuit
  is a *graph + spiking* substrate; node value is supposed to
  **emerge** from connectivity, weights, and activity — not be set
  out-of-band. Storing `importance` as a static column makes it
  parallel to fields like `domain` (a categorical tag), which is the
  wrong category. It also drifts: a neuron the user marked
  "high importance" three months ago may now be peripheral after the
  graph has reshaped around it, but the column still says 0.9.
- **B** breaks on cold start. A freshly-added neuron has zero
  synapses, zero co-fires, zero retrieve hits — its derived
  importance is identical to every other newcomer's. The user (or an
  AI agent acting on their behalf) cannot communicate prior
  knowledge such as *"this idiom is core to business French, surface
  it more aggressively even before connections form."*

## 2. The commitment

**`importance(n) = f(state(n), importance_prior(n))`** — a pure
function of two explicit inputs.

- **`state(n)`** is everything Spikuit observes about the neuron's
  position in the graph *as it currently exists*: weighted degree,
  co-fire counts, retrieve hits, community membership. State is
  dynamic and grows as the graph evolves.
- **`importance_prior(n)`** is the user/agent's Bayesian-style
  prior probability assignment for the neuron's importance at
  neuron creation (or at an explicit recalibration event). It is a
  stored input, optional, nullable. It is **not** a knob to be
  tweaked routinely; mutation is meaningful and logged as a
  recalibration. Each cousin metric (§9) has its own
  `<metric>_prior` slot with possibly different shape; for
  importance, the prior is a single REAL `∈ [0, 1]`.
- `f` is **pure**: same `(state, importance_prior)` always yields
  the same `importance`. There is no hidden mutable scalar called
  "importance" — there is only the function and its two inputs.

This commitment buys five properties:

1. **Predictability.** Two neurons with the same `state` and the
   same `importance_prior` value have the same `importance`.
   Caching, offline recomputation, and "why is this 0.7?"
   explanations all become tractable.
2. **Independent axes.** `importance_prior` and `state` are
   orthogonal inputs. Their *difference* carries meaning (see §3.3):
   a neuron whose `importance_prior` was low but whose state-derived
   score is high is **emerging** — the graph has discovered
   importance the user didn't initially see. The reverse is a
   **dormant** neuron — the user invested expectation that the
   graph hasn't validated.
3. **No drift, no double-source-of-truth.** There is no static
   `importance` column to grow stale. There is no derived score
   that disagrees with a stored one. There is the function, and the
   function returns one number.
4. **`f` is policy, and policy is versionable.** Because the
   importance definition lives in code (the function body), not in
   data, swapping `f` for `f'` instantly redefines importance for
   every neuron in the brain. The previous definition is recoverable
   by reverting the code — *the inputs `state` and `importance_prior`
   are persistent and untouched by the swap*. This is the same
   property git gives source code, applied to a knowledge-graph
   metric: you can experiment with formulas, A/B them, regret them,
   and roll back without losing data. A stored `importance` column
   would destroy this property — re-evaluating the formula would
   mean rewriting persisted values, with no clean rollback.
5. **Bounded codomain.** `f: state × importance_prior → [0, 1]`.
   The output is always in the closed unit interval, by
   construction (clamp at the boundary of `f` if needed).
   Downstream consumers (`desired_retention` linear map in the
   tutor overlay, `--min-importance` thresholds, opacity in
   rendering) can rely on this without re-normalizing. Combined
   with `importance_prior ∈ [0, 1]` and `state_score ∈ [0, 1]`,
   every value in the system speaks the same scale.

Additional non-strict guarantees (worth stating but not load-bearing
to the architectural commitment):

- **Monotonicity.** `∂f/∂state_score ≥ 0` and
  `∂f/∂importance_prior ≥ 0` — raising either input cannot lower
  importance. Holds for the linear blend in §4 and any reasonable
  replacement.
- **Empty-graph degeneracy.** When `state(n)` has no signals
  (isolated new neuron, brand-new brain), `state_score = 0` by
  definition; `f` falls back to `importance_prior` (or 0 if
  `importance_prior` is absent — see §3.2 for absent-vs-zero
  semantics).

The earlier "hybrid" framing was rejected because it implied two
co-equal sources (a stored `base` and a derived score) blended by an
arbitrary formula. The pure-function framing dissolves that
ambiguity: there is one output, computed deterministically from two
labeled inputs.

## 2.1 Signature vs. semantics

`f: state × prior → [0, 1]` is a **family signature**, not a
definition — and the `prior` slot is **metric-scoped**: each
specific metric `f_X` has its own `prior_X` of possibly different
shape (or no prior at all). Many functions satisfy this signature
family, and several of them can coexist on the same brain — each
consumed by a different downstream:

| metric | what it captures | `prior` shape | likely consumer |
|---|---|---|---|
| **`importance`** *(this doc)* | durable cognitive value to the user | `importance_prior` — REAL ∈ [0, 1] (nullable) | `tutor due` sort, FSRS `desired_retention`, `--min-importance` threshold |
| `salience` | currently-active, recency-weighted | `salience_prior` — REAL ∈ [0, 1] (nullable, often unused) | retrieve rerank, chat context selection |
| `centrality` | graph-topological hub-ness | *none* — pure state, prior not used | visualize emphasis, structural skeleton view |
| `novelty` | information-theoretic distance from neighbors | possibly `novelty_prior` (REAL or unused) | curator surfacing of misfits / new frames |
| `recency` | time-since-last-event with decay | *none* — pure state | "what have I been working on" reports |

`prior` is intentionally typed per metric. The framework does not
mandate a universal prior shape — only that whichever shape a
metric chooses, the function consuming it remains pure and
returns `[0, 1]`.

What makes a particular `f` deserving of the name **"importance"**
is not its signature but its **grounding** — the principled reasons
each input signal contributes to a notion of *durable cognitive
value*, drawn from neuroscience, cognitive science, and graph
theory. §4 gives the formula sketch; §4.1 records its grounding.

The same signature pattern is intentionally future-compatible (§9):
adding `salience(n)` later means implementing a *different* `f`
with the same contract, not changing the architecture.

## 3. The two inputs

### 3.1 `state(n)` — graph-derived

Drawn only from what Spikuit already records:

| Signal | Source | Rationale |
|---|---|---|
| **Weighted degree** | `synapse.weight` summed over edges touching the neuron | Hub neurons in the graph are structurally important. |
| **Co-fire activity** | `synapse.co_fires` summed over connected edges | Frequent co-activation = neuron participates in active reasoning. |
| **Retrieve hit count** | `retrieve_log` entries containing the neuron's id | External demand for this neuron — proxy for "practical importance". |
| **Community size** | `neuron.community_id` size after `community detect` | Neurons inside a large coherent cluster are more important than isolates. *(optional, Phase 2)* |

Each signal is normalized within the current brain (percentile rank
within domain — see §8) and combined into a single
`state_score(n) ∈ [0, 1]`.

Notably absent from `state`: **fire history (`spike` grades, FSRS
stability / difficulty / retrievability)**. Those belong to the
tutor overlay (spikuit-tutor / FSRS plugin) and represent *how well
the user remembers* the neuron — not its *value*. Feeding them into
`state` would double-count what FSRS already handles and create a
ratchet where forgotten neurons become invisible. See §5.

### 3.2 `importance_prior(n)` — Bayesian prior at creation

The user/agent's prior probability assignment for importance,
captured at neuron creation time and persisted as an explicit input
to `f`. Type: REAL ∈ [0, 1], nullable. Set via an explicit
`--importance-prior` flag at `spkt neuron add` time (or inferred by
the importing agent).

**Name and framing.** The word **`prior`** is chosen in the Bayesian
sense — *the probability the actor assigns before observing graph
evidence*. The graph itself plays the role of evidence: as `state`
accumulates over time, `f` integrates the prior against that
evidence to produce the current `importance`. The earlier draft
called this `initial`, but "initial" alone is ambiguous (initial of
what?). `importance_prior` is self-documenting and scales to cousin
metrics (`salience_prior`, etc.) without name collision.

**Semantics of absence vs. zero vs. neutral:**

| state of `importance_prior` | meaning | how `f` reads it |
|---|---|---|
| **absent** (no value set / NULL) | the actor expressed no opinion at creation — uninformed | `f` falls back to `state_score` alone (no prior contribution) |
| `0.0` | the actor explicitly believes this neuron is unimportant | `f` blends as `0.6 * state_score + 0.4 * 0` — pulls importance toward zero |
| `0.5` | the actor explicitly believes importance is neutral | `f` blends as `0.6 * state_score + 0.4 * 0.5` — pulls toward 0.5 |
| `1.0` | the actor strongly anchors importance at the top | `f` blends as `0.6 * state_score + 0.4 * 1` — pulls importance up |

*absent ≠ 0.5* — these are semantically distinct and `f` treats
them differently. This is a key reason to prefer schema option E2
(sidecar table, row absence = no opinion) over E1 (column NULL,
which can be confused with 0.0 in some query contexts). See §7.

**Mutability:**

- **Stable by default** — not a knob for routine tweaking. Once
  set, `importance_prior` represents *what the actor believed at
  that moment*; subsequent graph evolution is captured by `state`,
  not by retroactively rewriting the prior.
- **Explicit recalibration allowed** — `spkt neuron update
  --importance-prior 0.4` is permitted but the event is logged.
  Implementation under schema E2: the sidecar table either
  overwrites with a new `set_at` (overwrite mode) or appends to a
  separate `neuron_metric_prior_log` table (history mode). Decision
  parked, see §7.
- **Actor provenance recorded** — every prior carries
  `(set_by_actor_id, set_by_actor_kind)` so "AI agent set 0.8, user
  overrode to 0.5" workflows are auditable. Under E1 this would
  require an additional column; E2 makes it natural. See §7.

**Future extensions (parked):**

- Confidence on the prior (mean + interval) — currently single
  scalar.
- Mode-specific priors (review vs. teaching vs. chat) — current
  resolution: these should be separate cousin metrics, not separate
  shapes of the same prior. `importance_prior` is for `importance`
  specifically.

### 3.3 Emerging, dormant, and the gap between inputs

Because `importance_prior` and `state` are orthogonal axes, the
*difference* between them carries diagnostic information:

| `importance_prior` | `state_score` | Pattern | Surfacing |
|---|---|---|---|
| low | low | peripheral / unused | bottom of `tutor due` queue |
| low | high | **emerging** — graph found value the user missed | candidate for `spkt neuron explain` ("you flagged this as low but it's now connected to N strong neurons") |
| high | low | **dormant** — user expectation unrealized | candidate for review: seed more connections? merge? retire? |
| high | high | confirmed core | top of `tutor due` queue |
| absent | any | no opinion at creation | not labeled — `f` is state-only, the diagnostic axis doesn't apply |

These labels are not stored — they are computed at query time from
the gap `state_score - importance_prior` (skipped when prior is
absent). A future `spkt neuron diverge` (or similar) can surface
neurons whose gap exceeds a threshold, giving the user a
maintenance loop: "what has emerged this week?" and "what has gone
dormant?"

## 4. Sketch of the derivation

Pseudocode for `f(state, importance_prior) → importance`, intended
as a starting point — exact normalization and weights are to be
tuned during the observation phase (§6):

```python
def importance(neuron_id, brain) -> float:
    # --- state(n): graph-derived ---
    structural = brain.weighted_degree(neuron_id)       # ∈ [0, ∞)
    activity   = brain.co_fire_total(neuron_id)         # ∈ [0, ∞)
    demand     = brain.retrieve_hit_count(neuron_id)    # ∈ [0, ∞)

    s = percentile_rank(structural, brain.all_weighted_degrees())
    a = percentile_rank(activity,   brain.all_co_fire_totals())
    d = percentile_rank(demand,     brain.all_retrieve_hits())

    state_score = 0.45 * s + 0.30 * a + 0.25 * d  # ∈ [0, 1]

    # --- importance_prior(n): Bayesian prior from actor, nullable ---
    prior = brain.importance_prior(neuron_id)  # float ∈ [0, 1] or None

    # --- combine ---
    # Output is bounded to [0, 1] by construction (linear blend of
    # values already in [0, 1]); the clamp is defensive.
    if prior is None:
        return clamp(state_score, 0.0, 1.0)
    return clamp(0.6 * state_score + 0.4 * prior, 0.0, 1.0)
```

Properties:

- **Pure.** No randomness, no hidden context. Reproducible across
  reads.
- **Absence-respecting.** A neuron with no `importance_prior` set
  is scored on state alone — not "treated as 0.5 with low
  confidence." Distinct semantics from `importance_prior = 0.5`
  (see §3.2 table).
- **Cold-start tolerant.** A new neuron with zero edges gets a
  state_score near zero, but a high `importance_prior` lifts it.
  Without a prior, it stays low until the graph speaks.
- **Graph-dominant at maturity.** `importance_prior`'s contribution
  is capped at 40% so a clear graph signal can override it. Future
  refinement: decay the prior weight as the count of graph signals
  grows (`weight_prior(n) = 0.4 / (1 + degree(n)/k)`).

### 4.1 Grounding — why this `f` is *importance*

Each input signal maps to an established principle in cognitive
science or graph theory. Together they justify naming this
particular `f` "importance" rather than salience, centrality, or
recency:

| Input | Principle | Why it indicates *durable value* |
|---|---|---|
| **Weighted degree** (`s`) | **Degree centrality** (graph theory) | A concept connected to many others is a structural pivot — losing or weakening it costs the cognitive economy. |
| **Co-fire activity** (`a`) | **Hebbian plasticity** — *"cells that fire together wire together"* (Hebb 1949) | Repeated co-activation marks the neuron as a member of stable engrams. Engram membership is a durable property, not a transient state. |
| **Retrieve hits** (`d`) | **Behavioral salience** / use-frequency | A memory the agent (or external query) reaches for often has demonstrated practical value over time — the integration is over the lifetime of the brain, not the last 24h. |
| **`importance_prior`** | **Encoding-specificity effect** (Tulving & Thomson 1973) | Attention strength at encoding predicts long-term importance. The user/agent communicates this prior at neuron creation; over time, the graph either validates it or doesn't. |

Notable omissions and why they are *not* in `importance`:

- **FSRS retention metrics** (stability, difficulty, retrievability)
  — these measure *how well the user remembers* the neuron, which
  is orthogonal to *how valuable it is*. A forgotten high-value
  neuron is still high-value (and FSRS should bring it back
  aggressively). See §3.1 / §5.
- **Pure recency** — a recently-viewed concept is *salient*, not
  necessarily *important*. Recency-weighted information belongs to
  `salience` (a separate cousin metric in §9), not importance.
- **Pure topology** (e.g. PageRank without weights) — captures
  *centrality*, which is structurally interesting for visualization
  but not the same as cognitive value to *this* user. The
  weighted-degree signal already incorporates synapse weights,
  which encode learned co-association strength.

The §4 formula is one defensible blend; future revisions can tune
weights, swap percentile rank for a different normalization, or add
the community-size signal (§3.1) — as long as the grounding above
still holds, the function still earns the name *importance*. If a
revision starts emphasizing recency or pure topology, it should be
renamed to a different cousin metric (§9) rather than redefining
what "importance" means.

## 5. FSRS plugin glue (out of scope for this doc, recorded for record)

Spikuit-core does not know about FSRS. The tutor overlay
(`spikuit-tutor`) is the only place where importance touches review
scheduling.

The intended glue:

- `TutorScheduler` reads `importance(n)` at fire time.
- Maps to FSRS `desired_retention` (e.g. linear from `0.80` at
  importance `0.1` to `0.95` at importance `0.9`).
- Constructs a per-review `Scheduler(desired_retention=mapped)` and
  calls `review_card`.

**Direction is strictly core → plugin.** FSRS state
(stability/difficulty) never feeds back into `importance`. This is
load-bearing for the architectural commitment and matches the
existing `spikuit-core` / `spikuit-tutor` separation introduced by
commit `e96e6b5` (*retire FSRS from spikuit-core into a tutor
overlay*).

## 6. Observation phase (now)

Before adding any column or shipping write surface, validate the
derivation by observation:

1. Implement `importance(neuron, brain)` as a pure function over
   current `Brain` state, treating `importance_prior` as `None`
   everywhere (since the storage doesn't exist yet). No schema
   change, no persisted field.
2. Optional: expose `spkt neuron rank` (read-only) that prints
   neurons sorted by `importance`. Compare against intuition.
3. Run on the maintainer's existing brain (currently ~22 curated
   French grammar neurons) and a future bulk import (~210 Netflix
   vocab items). Check: does the state-only ranking match
   intuition? Where does it fall short — and would a hypothetical
   `importance_prior` value have fixed those cases?
4. If state-only ranking is mostly right → proceed to Phase 1
   (commit to schema option from §7, expose `--importance-prior`
   on `neuron add`, integrate into `tutor due` sort).
5. If state-only ranking is wrong → tune weights, add signals
   (e.g. community size), or reconsider whether `importance_prior`
   needs higher weight from the start.

This keeps the daily-use loop unblocked while the design is
validated empirically.

## 7. Future surface (not yet committed)

When observation confirms the approach:

- **Schema** — see §7.1 for the option matrix. Recommended:
  schema option **E2** (sidecar table `neuron_metric_prior`)
  because it (a) supports cousin metrics with zero migration
  churn, (b) carries actor provenance natively, (c) makes
  *absent ≠ 0* explicit via row absence. No `importance` column
  ever — `importance` is the function's return value, not a field.
- **CLI write.** `spkt neuron add --importance-prior 0.7`
  (also accepting `high`/`mid`/`low` as symbolic aliases mapped
  to 0.8/0.5/0.2). Under E2 a generic form
  `spkt neuron add --prior importance=0.7` could be supported in
  addition. `spkt neuron update <id> --importance-prior ...` for
  explicit recalibration. **The flag names the input (a `prior`),
  not the output (`importance`)** — reinforces the mental model
  that the actor sets one input to a function, not the function's
  value.
- **CLI read.** `spkt neuron list --sort importance`,
  `spkt neuron rank`, `spkt tutor due --min-importance 0.5`.
  Read API returns the computed value; callers never see the
  `prior` vs `state` split unless they ask for it.
- **Diagnostic surface.** `spkt neuron diverge` (or similar) lists
  neurons whose `state_score - importance_prior` exceeds a
  threshold — surfacing **emerging** and **dormant** neurons
  (§3.3) for the maintainer's attention. Neurons with absent
  prior are skipped from this view (no diagnostic axis).
- **Caching.** If query cost matters at scale, add a
  `neuron_importance_cache` sidecar table refreshed by `spkt neuron
  recompute-importance` (cron-like, not on every read). The cache
  is **purely a performance device** — the function remains the
  source of truth and the cache can be dropped at any time.

**Visualization is intentionally absent from this list** — see the
*Scope* note in §1 and §9. The metric driving `spkt visualize`
emphasis (likely `centrality`, possibly compound) is a separate
design question whose answer is not necessarily *importance*.

### 7.1 Schema option matrix

When the time comes to persist `importance_prior` (and eventually
cousin metric priors), three options:

| Option | Shape | Pros | Cons |
|---|---|---|---|
| **E1 — per-metric column** | `ALTER TABLE neuron ADD COLUMN importance_prior REAL` (nullable); add `salience_prior REAL` etc. when each metric ships | Simple, type-safe, easy `ORDER BY`; minimal query overhead | New metric = new migration; provenance needs extra columns; *absent vs 0* relies on `NULL` discipline (easy to get wrong in SQL) |
| **E2 — sidecar table (recommended)** | `CREATE TABLE neuron_metric_prior (neuron_id TEXT, metric_name TEXT, value REAL, set_at TEXT, set_by_actor_id TEXT, set_by_actor_kind TEXT, PRIMARY KEY (neuron_id, metric_name))` | Zero schema churn per new metric; provenance is built in; *absent = no row* is unambiguous; recalibration history easy via separate `_log` table or `UPDATE` with `set_at` rewrite | Sort by importance requires JOIN; slightly more code per metric |
| E3 — JSON column on `neuron` | `ALTER TABLE neuron ADD COLUMN priors TEXT` storing `{"importance": 0.7, ...}` | Schema-stable | Slow `ORDER BY`, no type guarantee, no provenance without nested structure, awkward indexing |

**Recommendation: E2.** Rationale:

1. The cousin-metric architecture (§9) makes "more metric priors
   over time" the expected pattern, not the exception. E1's
   migration cost compounds.
2. *Absent vs explicit zero* is semantically load-bearing for `f`
   (§3.2 / §4). Row-absence in E2 is unambiguous; `NULL` in E1 is
   often coerced or misread by downstream tooling.
3. Actor provenance (§3.2) is parked as a §8 open question under
   E1; E2 dissolves it by adding two columns to the sidecar.
4. Recalibration logging fits naturally as a separate
   `neuron_metric_prior_log` append-only table sharing the same
   schema shape — no schema duplication.

E2 cost (JOIN on sort) is recoverable via the `neuron_importance_cache`
table mentioned above. The cache is allowed to materialize `f`'s
output; what we must *not* materialize is the user-set prior
itself, which lives only in the sidecar.

**Decision deferred** until observation phase (§6) yields signal on
whether the rank is meaningful — but the doc records the preferred
direction so future PRs don't litigate this from scratch.

## 8. Open questions (parked)

Resolved or substantially mitigated by the §3.2 / §7.1 design
(removed from this list): prior decay (handled by the
graph-dominant-at-maturity property in §4 + the optional
decay-by-degree refinement); prior provenance (built into schema
E2); absent-vs-zero semantics (defined in §3.2 table).

Remaining:

- **Community membership signal.** Worth including in `state`, but
  `community detect` is currently manual. If communities go stale,
  `state_score` goes stale. Either auto-rerun on schedule, or only
  include this signal when a community marker is fresh.
- **Multi-domain percentile.** Should `state_score`'s percentile
  rank be within the neuron's domain rather than brain-wide? A
  French vocab neuron shouldn't be ranked against a math concept
  neuron for cross-domain percentile fairness. Default proposal:
  domain-local percentile when `neuron.domain` is set, brain-wide
  fallback when not.
- **Recalibration mode under E2.** When a user runs `spkt neuron
  update --importance-prior 0.4`, should the sidecar (a) overwrite
  the row and update `set_at`, or (b) append to a separate
  `neuron_metric_prior_log` while keeping the canonical row
  current? (b) preserves history but doubles storage; (a) loses
  audit trail. Tentative: (a) for the canonical row, optional (b)
  if the user opts into history.
- **What does absent prior mean for sort?** When sorting `tutor
  due` by importance, where do neurons with absent prior go?
  Treating them by state alone (§4) is mathematically clean, but
  a brand-new neuron with `state_score = 0` will sit at the bottom
  forever unless something pulls it up. Possibly the tutor should
  have its own "newcomer boost" orthogonal to importance.
- **Symbolic alias mapping.** `--importance-prior high|mid|low` is
  a UX convenience; the mapping (proposed 0.8 / 0.5 / 0.2) is
  arbitrary. Should this be configurable per brain, or hardcoded?
  Hardcoded keeps explanations simple ("high = 0.8") and avoids a
  setting that needs to be remembered.

These are deferred until observation in §6 surfaces which of them
actually matter.

## 9. Cousin metrics — other inhabitants of the signature (parked)

The architectural pattern `state × prior → [0, 1]` (with `prior`
metric-scoped) can host other scalar metrics. This doc commits only
to `importance`. The same contract admits the following cousins,
sketched here so future PRs can plug into the framework rather than
reinventing it:

| metric | grounding | sketch | `prior` shape | downstream |
|---|---|---|---|---|
| **`salience(n)`** | recency-weighted activity; what is *currently on the brain's mind* | exponentially-decayed retrieve / co-fire history | `salience_prior` (REAL ∈ [0, 1], often unused — recency speaks for itself) | retrieve rerank, chat context selection, "what was I just working on" |
| **`centrality(n)`** | graph topology in isolation | PageRank or eigenvector centrality over the synapse graph | **none** — pure state | `visualize` star magnitude, structural skeleton view, `--min-centrality` filter for graph exports |
| **`novelty(n)`** | information-theoretic distance from neighbors | low embedding cosine similarity to nearest community; surprise signal | possibly `novelty_prior` (REAL or unused) | curator surfacing of orphans / misfits, "what doesn't yet fit" |
| **`recency(n)`** | time-since-last-event | linear or exponential decay of last fire / co-fire / retrieve | **none** — pure state | "what have I been working on" reports, freshness filters |

Schema option E2 (§7.1) — the sidecar `neuron_metric_prior`
keyed by `(neuron_id, metric_name)` — naturally accommodates any
of the above adding their own prior with zero migration. Metrics
that need no prior simply never get rows.

### Implementation note (for future PRs)

A uniform `NeuronMetric` Protocol — `__call__(brain, neuron_id) →
float` — would let these be plugged into tutor sort, retrieve
rerank, visualize, and any other consumer through a single
interface. Each metric is a stand-alone module with:

- A name (so `--sort` flags and CLI surfaces can address it by
  string).
- A pure implementation respecting the codomain contract.
- Optional cache support via the same sidecar pattern (§7).

This doc does **not** mandate creating that Protocol now — that is a
follow-up architectural decision. It is mentioned only so the
present `importance` implementation does not foreclose the option.

### Which metric feeds which consumer?

A consequence of the signature being a family: each downstream
consumer should explicitly pick which metric it wants, rather than
silently assuming one global notion of "neuron score." Current
intent:

| consumer | metric (today) | metric (anticipated) |
|---|---|---|
| `tutor due` sort | `importance` | `importance` (review-triage value) |
| FSRS `desired_retention` | `importance` | `importance` |
| `--min-importance` filter | `importance` | `importance` |
| `spkt neuron diverge` | `importance` (gap analysis) | `importance` |
| `spkt visualize` emphasis | *(deferred)* | likely `centrality` or a compound — **not** `importance` |
| retrieve rerank | none currently | possibly `salience` |
| "what doesn't fit" curator view | none currently | possibly `novelty` |

Locking this matrix in writing prevents future drift where a
visualize PR silently starts depending on `importance` and a
follow-up importance tweak surprises the visualization.
