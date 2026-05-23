# Neuron Importance — `importance = f(state, initial)`

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
function of two explicit inputs**, `state` and `initial`. The earlier
"hybrid" framing was rejected because *hybrid* left the boundary
between the components unspecified; this doc records the sharper
commitment.

**Scope.**

*In scope:*
- The neuron scalar-metric **framework**: signature
  `state × initial → [0, 1]`, purity, versionability, codomain
  contract (§2).
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

**`importance(n) = f(state(n), initial(n))`** — a pure function of
two explicit inputs.

- **`state(n)`** is everything Spikuit observes about the neuron's
  position in the graph *as it currently exists*: weighted degree,
  co-fire counts, retrieve hits, community membership. State is
  dynamic and grows as the graph evolves.
- **`initial(n)`** is the user/agent's snapshot of perceived
  importance at neuron creation (or at an explicit recalibration
  event). It is a stored input, optional, nullable. It is **not** a
  knob to be tweaked routinely; mutation is meaningful and logged
  as a recalibration.
- `f` is **pure**: same `(state, initial)` always yields the same
  `importance`. There is no hidden mutable scalar called
  "importance" — there is only the function and its two inputs.

This commitment buys five properties:

1. **Predictability.** Two neurons with the same state and the same
   initial value have the same importance. Caching, offline
   recomputation, and "why is this 0.7?" explanations all become
   tractable.
2. **Independent axes.** `initial` and `state` are orthogonal inputs.
   Their *difference* carries meaning (see §3.3): a neuron whose
   `initial` was low but whose state-derived score is high is
   **emerging** — the graph has discovered importance the user
   didn't initially see. The reverse is a **dormant** neuron — the
   user invested expectation that the graph hasn't validated.
3. **No drift, no double-source-of-truth.** There is no static
   `importance` column to grow stale. There is no derived score
   that disagrees with a stored one. There is the function, and the
   function returns one number.
4. **`f` is policy, and policy is versionable.** Because the
   importance definition lives in code (the function body), not in
   data, swapping `f` for `f'` instantly redefines importance for
   every neuron in the brain. The previous definition is recoverable
   by reverting the code — *the inputs `state` and `initial` are
   persistent and untouched by the swap*. This is the same property
   git gives source code, applied to a knowledge-graph metric: you
   can experiment with formulas, A/B them, regret them, and roll
   back without losing data. A stored `importance` column would
   destroy this property — re-evaluating the formula would mean
   rewriting persisted values, with no clean rollback.
5. **Bounded codomain.** `f: state × initial → [0, 1]`. The output
   is always in the closed unit interval, by construction (clamp at
   the boundary of `f` if needed). Downstream consumers (star
   magnitude buckets in `visualize`, `desired_retention` linear map
   in the tutor overlay, `--min-importance` thresholds, opacity in
   rendering) can rely on this without re-normalizing. Combined with
   `initial ∈ [0, 1]` and `state_score ∈ [0, 1]`, every value in the
   system speaks the same scale.

Additional non-strict guarantees (worth stating but not load-bearing
to the architectural commitment):

- **Monotonicity.** `∂f/∂state_score ≥ 0` and `∂f/∂initial ≥ 0` —
  raising either input cannot lower importance. Holds for the
  linear blend in §4 and any reasonable replacement.
- **Empty-graph degeneracy.** When `state(n)` has no signals
  (isolated new neuron, brand-new brain), `state_score = 0` by
  definition; `f` falls back to `initial` (or 0 if `initial` is
  NULL).

The earlier "hybrid" framing was rejected because it implied two
co-equal sources (a stored `base` and a derived score) blended by an
arbitrary formula. The pure-function framing dissolves that
ambiguity: there is one output, computed deterministically from two
labeled inputs.

## 2.1 Signature vs. semantics

`f: state × initial → [0, 1]` is a **signature**, not a definition.
Many functions satisfy it, and several of them can coexist on the
same brain — each consumed by a different downstream:

| metric (same signature) | what it captures | likely consumer |
|---|---|---|
| **`importance`** *(this doc)* | durable cognitive value to the user | `tutor due` sort, FSRS `desired_retention`, `--min-importance` threshold |
| `salience` | currently-active, recency-weighted | retrieve rerank, chat context selection |
| `centrality` | graph-topological hub-ness | visualize emphasis, structural skeleton view |
| `novelty` | information-theoretic distance from neighbors | curator surfacing of misfits / new frames |
| `recency` | time-since-last-event with decay | "what have I been working on" reports |

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

### 3.2 `initial(n)` — snapshot at creation

A nullable REAL ∈ [0, 1] persisted in a future `neuron.initial`
column (name TBD; current candidates: `initial_importance`,
`importance_initial`, or simply `initial`). Set at `neuron add` time
via an explicit `--initial` flag or inferred by the importing agent.

- **Nullable** — neurons added without an opinion remain
  `initial = NULL`, which the derivation treats as "no prior signal,
  use state only" (functionally equivalent to a neutral 0.5 with
  zero weight, but explicit so we can distinguish *uninformed* from
  *deliberately neutral*).
- **Stable** — not a knob for routine tweaking. Once set, it
  represents *what the user knew about this neuron at that moment*.
  It can be explicitly recalibrated (`spkt neuron update --initial`)
  but such mutation is a logged event, not a tuning convenience.
- **Bounded** — kept in `[0, 1]` to compose cleanly with state's
  normalized score.

### 3.3 Emerging, dormant, and the gap between inputs

Because `initial` and `state` are orthogonal axes, the *difference*
between them carries diagnostic information:

| `initial` | `state_score` | Pattern | Surfacing |
|---|---|---|---|
| low | low | peripheral / unused | bottom of `tutor due` queue |
| low | high | **emerging** — graph found value the user missed | candidate for `spkt neuron explain` ("you flagged this as low but it's now connected to N strong neurons") |
| high | low | **dormant** — user expectation unrealized | candidate for review: seed more connections? merge? retire? |
| high | high | confirmed core | top of `tutor due` queue |

These labels are not stored — they are computed at query time from
the gap `state_score - normalized(initial)`. A future `spkt neuron
diverge` (or similar) can surface neurons whose gap exceeds a
threshold, giving the user a maintenance loop: "what has emerged
this week?" and "what has gone dormant?"

## 4. Sketch of the derivation

Pseudocode for `f(state, initial) → importance`, intended as a
starting point — exact normalization and weights are to be tuned
during the observation phase (§6):

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

    # --- initial(n): user/agent snapshot, nullable ---
    init = brain.initial(neuron_id)  # float ∈ [0, 1] or None

    # --- combine ---
    # Output is bounded to [0, 1] by construction (linear blend of
    # values already in [0, 1]); the clamp is defensive.
    if init is None:
        return clamp(state_score, 0.0, 1.0)
    return clamp(0.6 * state_score + 0.4 * init, 0.0, 1.0)
```

Properties:

- **Pure.** No randomness, no hidden context. Reproducible across
  reads.
- **NULL-respecting.** A neuron with no `initial` set is scored on
  state alone — not "treated as 0.5 with low confidence." Distinct
  semantics from `initial = 0.5`.
- **Cold-start tolerant.** A new neuron with zero edges gets a
  state_score near zero, but a high `initial` lifts it. Without
  `initial`, it stays low until the graph speaks.
- **Graph-dominant at maturity.** `initial`'s contribution is
  capped at 40% so a clear graph signal can override it. Future
  refinement: decay the `initial` weight as the count of graph
  signals grows (`weight_initial(n) = 0.4 / (1 + degree(n)/k)`).

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
| **`initial`** | **Encoding-specificity effect** (Tulving & Thomson 1973) | Attention strength at encoding predicts long-term importance. The user/agent communicates this prior at neuron creation; over time, the graph either validates it or doesn't. |

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
   current `Brain` state, treating `initial` as `None` everywhere
   (since the column doesn't exist yet). No schema change, no
   persisted field.
2. Optional: expose `spkt neuron rank` (read-only) that prints
   neurons sorted by `importance`. Compare against intuition.
3. Run on the maintainer's existing brain (currently ~22 curated
   French grammar neurons) and a future bulk import (~210 Netflix
   vocab items). Check: does the state-only ranking match
   intuition? Where does it fall short — and would a hypothetical
   `initial` value have fixed those cases?
4. If state-only ranking is mostly right → proceed to Phase 1 (add
   `initial` column, expose `--initial` on `neuron add`, integrate
   into `tutor due` sort).
5. If state-only ranking is wrong → tune weights, add signals
   (e.g. community size), or reconsider whether `initial` needs
   higher weight from the start.

This keeps the daily-use loop unblocked while the design is
validated empirically.

## 7. Future surface (not yet committed)

When observation confirms the approach:

- **Schema.** `ALTER TABLE neuron ADD COLUMN initial REAL`
  (nullable). No `importance` column ever — `importance` is the
  function's return value, not a field.
- **CLI write.** `spkt neuron add --initial 0.7|high|mid|low`,
  `spkt neuron update <id> --initial ...`. **The flag names the
  input (`initial`), not the output (`importance`)** —
  reinforces the mental model that the user sets one input to a
  function, not the function's value.
- **CLI read.** `spkt neuron list --sort importance`,
  `spkt neuron rank`, `spkt tutor due --min-importance 0.5`.
  Read API returns the computed value; callers never see the
  `initial` vs `state` split unless they ask for it.
- **Diagnostic surface.** `spkt neuron diverge` (or similar) lists
  neurons whose `state_score - normalized(initial)` exceeds a
  threshold — surfacing **emerging** and **dormant** neurons (§3.3)
  for the maintainer's attention.
- **Caching.** If query cost matters at scale, add a
  `neuron_importance_cache` sidecar table refreshed by `spkt neuron
  recompute-importance` (cron-like, not on every read). The cache
  is **purely a performance device** — the function remains the
  source of truth and the cache can be dropped at any time.

**Visualization is intentionally absent from this list** — see the
*Scope* note in §1 and §9. The metric driving `spkt visualize`
emphasis (likely `centrality`, possibly compound) is a separate
design question whose answer is not necessarily *importance*.

## 8. Open questions (parked)

- **`initial` decay.** Should `initial`'s weight in `f` decay over
  time so old snapshots don't dominate after the graph has spoken?
  Or does the formula in §4 (graph-dominant at maturity) already
  handle this implicitly? The decay-by-degree refinement in §4 is
  one candidate.
- **Community membership signal.** Worth including in `state`, but
  `community detect` is currently manual. If communities go stale,
  `state_score` goes stale. Either auto-rerun on schedule, or only
  include this signal when a community marker is fresh.
- **`initial` provenance.** Should we record *which actor* set
  `initial` (user vs. AI agent vs. import script)? Useful for "AI
  suggested 0.8, user overrode to 0.5" workflows. Could live in
  `changeset` (existing AMKB plumbing) rather than as another
  column.
- **Multi-domain percentile.** Should `state_score`'s percentile
  rank be within the neuron's domain rather than brain-wide? A
  French vocab neuron shouldn't be ranked against a math concept
  neuron for cross-domain percentile fairness. Default proposal:
  domain-local percentile when `neuron.domain` is set, brain-wide
  fallback when not.
- **Mutation semantics for `initial`.** Is `--initial` set-once at
  add time, or can `update --initial` overwrite freely? Current
  stance (§3.2): explicit recalibration is allowed, but logged. Is
  that enough discipline, or should there be a separate `--recal`
  flag to make the intent explicit?
- **What does NULL mean for sort?** When sorting `tutor due` by
  importance, where do `initial = NULL` neurons go? Treating them
  by state alone (§4) is mathematically clean, but a brand-new
  neuron with `state_score = 0` will sit at the bottom forever
  unless something pulls it up. Possibly the tutor should have its
  own "newcomer boost" orthogonal to importance.

These are deferred until observation in §6 surfaces which of them
actually matter.

## 9. Cousin metrics — other inhabitants of the signature (parked)

The architectural pattern `state × initial → [0, 1]` can host other
scalar metrics. This doc commits only to `importance`. The same
contract admits the following cousins, sketched here so future PRs
can plug into the framework rather than reinventing it:

| metric | grounding | sketch | downstream |
|---|---|---|---|
| **`salience(n)`** | recency-weighted activity; what is *currently on the brain's mind* | exponentially-decayed retrieve / co-fire history | retrieve rerank, chat context selection, "what was I just working on" |
| **`centrality(n)`** | graph topology in isolation | PageRank or eigenvector centrality over the synapse graph; `initial` likely unused | `visualize` star magnitude, structural skeleton view, `--min-centrality` filter for graph exports |
| **`novelty(n)`** | information-theoretic distance from neighbors | low embedding cosine similarity to nearest community; surprise signal | curator surfacing of orphans / misfits, "what doesn't yet fit" |
| **`recency(n)`** | time-since-last-event | linear or exponential decay of last fire / co-fire / retrieve | "what have I been working on" reports, freshness filters |

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
