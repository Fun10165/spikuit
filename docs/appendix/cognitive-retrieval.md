# Cognitive Retrieval & the AMKB Memory Model

> **Claim.** Spikuit's retrieval score is not an ad-hoc mixture of signals. It is a computational instantiation of a four-stage cognitive memory model — encoding, storage, consolidation, retrieval — in which each signal corresponds to a distinct stage's state variable. Adding a concept to Spikuit and retrieving it later are the same operation, observed at different times.

This appendix connects Spikuit's scoring equation to cognitive psychology, compares the resulting model against Zettelkasten-inspired systems (A-Mem in particular), and argues that this correspondence is what makes Spikuit a reference implementation of the **Agent-Managed Knowledge Base (AMKB)** protocol rather than an application of spaced repetition to RAG.

---

## 1. The four-stage memory model

Human memory research (Atkinson & Shiffrin, 1968; Baddeley & Hitch, 1974; Squire & Kandel, 2009) distinguishes four stages that any persistent memory system — biological or artificial — must instantiate.

| Stage | Cognitive function | Spikuit mechanism |
|---|---|---|
| **Encoding** | Converting perception into a storable representation | `neuron add` + embedder + ingest extractors |
| **Storage** | Holding representations in a stable substrate | `circuit.db` (SQLite + sqlite-vec), Synapse weights, FSRS state |
| **Consolidation** | Reorganising storage during quiet periods; strengthening useful links, pruning weak ones | STDP weight updates, LIF pressure decay, `spkt consolidate`, community re-computation |
| **Retrieval** | Reconstructing representations on demand in response to a cue | `spkt retrieve`, QABot/Tutor sessions, spike propagation from query seed |

The stages are not separate stores. They are readings of the same graph state at different times, under different operators. This matches the currently dominant view in cognitive neuroscience (Roediger & Butler, 2011; Antony et al., 2017): memory is not primarily about preservation of traces but about the construction of representations at retrieval time, from a substrate that has been continuously reshaped by prior use.

Spikuit's design takes this view literally: every retrieval fires Synapses (via APPNP), every fire updates weights (via STDP), every update influences the next retrieval. There is no separate "index" to rebuild.

---

## 2. R × I × R: a decomposition of retrieval score

A common decomposition in cognitive AI-assistant work (Wang & Zhao, 2024; similar framings in AriGraph, A-Mem) is:

$$
\mathrm{score}(n \mid q) = \mathrm{Recency}(n) \cdot \mathrm{Importance}(n) \cdot \mathrm{Relevance}(n, q).
$$

- **Recency** — how recently the item was accessed, written, or activated.
- **Importance** — a context-independent measure of how central the item is to the knowledge base.
- **Relevance** — how well the item matches the specific query.

Spikuit's hybrid retrieval score (see [retrieval.md](retrieval.md))

$$
\mathrm{score}(n \mid q) = \max(\mathrm{keyword}_q, \mathrm{semantic}_q) \cdot (1 + \mathrm{retrievability} + \mathrm{centrality} + \mathrm{pressure} + \mathrm{boost})
$$

decomposes cleanly along these axes:

| R × I × R axis | Spikuit term | Cognitive interpretation |
|---|---|---|
| Relevance | `max(keyword, semantic)` | Cue-target similarity at the sensory/lexical layer |
| Importance | `centrality` (and, from v0.8.3, eigentheme profile) | Structural prominence — hub Neurons are retrieved preferentially even when local similarity is weak |
| Recency (short-term) | `pressure` | Neighbor spikes raise a Neuron's short-horizon activation; decays with $\tau_m = 14$ days |
| Recency (long-term) | `retrievability` | FSRS-derived memory strength; represents the probability of successful recall now |
| Recency (conversational) | `boost` | Session-local salience from QABot accept/reject feedback |

The three recency-family signals are not redundant. They correspond to distinct neural time-scales — working-memory pressure (seconds–minutes), consolidated memory retrievability (days–months), and episodic salience (within-session). Spikuit keeps them separate because they decay at different rates and serve different roles in retrieval.

### 2.1 Why multiplication, not addition

Relevance enters multiplicatively; importance and recency enter as a `(1 + ...)` modifier. This structure has a specific reason: a query-irrelevant Neuron, no matter how central or recently reviewed, should not dominate retrieval. The central term `max(keyword, semantic)` enforces a relevance gate; the parenthetical term then shapes the ranking among relevant candidates.

This is the formal version of a principle that cognitive models have long encoded: "cue + context" rather than "context alone" (Tulving & Thomson, 1973). A powerful context without a cue retrieves nothing.

---

## 3. Consolidation: why the substrate changes between retrievals

The four-stage model's most distinctive claim — relative to a filesystem or vector index — is that **the store changes when nothing is being stored**. Biological consolidation occurs offline (sleep, rest states); engineered consolidation must be engineered in.

In Spikuit:

- **STDP** (spike-timing-dependent plasticity): two Neurons that fire close in time have their connecting Synapse strengthened; asynchronous co-activation weakens it. The update rule uses $\tau_{\mathrm{stdp}} = 7$ days, slow enough to respond to a week's worth of retrieval pattern, fast enough to adapt within a month.
- **LIF decay** (leaky integrate-and-fire pressure): activation does not accumulate indefinitely. Per-Neuron pressure decays exponentially with $\tau_m = 14$ days.
- **Community re-detection**: after synapse weights drift enough, community boundaries shift. In v0.8.3+ this is spectral (see [spike-circuit.md](spike-circuit.md) §6.2).
- **`spkt consolidate`**: an explicit batch operator that identifies merge/split candidates based on the updated weights. Proposal-only by default; the user approves or rejects.

The cost accounting makes the value of this explicit. Without consolidation, maintenance cost grows linearly (or worse) with KB size — every new piece of knowledge must be reconciled against every existing piece. With consolidation, the reconciliation work happens structurally, on the weight matrix, not piece-by-piece. The cost-amortisation argument is worked out in §5 below.

---

## 4. Comparison: A-Mem, AriGraph, and the Zettelkasten heritage

Spikuit inherits three principles from the Zettelkasten tradition (Luhmann, 1992; Ahrens, 2017) — principles that A-Mem and AriGraph also adopt:

1. **Atomicity.** One Neuron holds one idea. Larger documents are ingested as connected networks of Neurons, not monolithic records.
2. **Backlinks.** Relations between Neurons are first-class objects (Synapses), not derived from text similarity at query time.
3. **Emergent structure.** No up-front taxonomy is required. Structure forms through accumulated Synapses and usage.

The table below contrasts how three systems implement these principles, plus the additional layer Spikuit adds.

| Principle | A-Mem (Xu et al., 2024) | AriGraph (2024) | Spikuit |
|---|---|---|---|
| Atomicity | LLM-generated atomic notes | Episodic nodes | User/agent-curated Neurons (LearnSession) |
| Backlinks | LLM-suggested semantic links | Typed edges (causal, temporal) | Typed Synapses (`requires`, `extends`, `contrasts`, `relates_to`, `summarizes`) |
| Emergent structure | Cluster via embedding + LLM | Community detection on episodic graph | Spectral clustering + eigentheme embedding + nullable `domain` (see [emergent-structure.md](emergent-structure.md)) |
| **Scheduling** | — | — | **FSRS per Neuron + propagation via LIF pressure** |
| **Explicit consolidation operator** | — | — | **STDP + `spkt consolidate`** |
| **Retrieval substrate changes between queries** | No (vector index is static) | Partial (graph edits) | **Yes (weights drift on every fire)** |

The last three rows are where Spikuit diverges. A-Mem improves retrieval quality through better chunking and tagging, but its index is still a conventional vector store — retrieval at time $t_1$ and $t_2$ against the same corpus returns the same ranking if the corpus is unchanged. Spikuit does not guarantee this: use of a Neuron at $t_1$ changes where it ranks at $t_2$, even with no content edits.

This is not a bug. It is the point.

---

## 5. Implications for AMKB: maintenance cost scaling

The AMKB protocol (see `contexts/active/` and the broader Spikuit docs) positions Spikuit as a reference implementation. The central claim is about cost, not performance: as the KB grows, **per-unit maintenance cost should decrease, not increase**.

Define the Maintenance Amortised Cost as

$$
\mathrm{MAC}(t) = \frac{H(t)}{\Omega(t)},
$$

where $H(t)$ is the cumulative human intervention time spent on the KB up to $t$ (reviewing proposals, correcting classifications, merging duplicates) and $\Omega(t)$ is a measure of usable knowledge-mass (e.g. weighted Neuron count with successful retrieval contribution).

For a well-designed AMKB, we expect MAC to be **sub-linear in KB size**:

$$
\mathrm{MAC}(t) = \Theta\!\left(\frac{1}{\Omega(t)^{\gamma}}\right), \quad 0 < \gamma \le 1.
$$

The four mechanisms above are what produce sub-linearity:

- **Emergent structure** (§4): eliminates per-Neuron tagging cost — the dominant term in naive KBs. Null-default `domain` + auto-fill means the user's per-Neuron cognitive load does not grow with corpus size.
- **Consolidation** (§3): reconciliation cost is paid on the weight matrix, not pairwise.
- **Retrieval changes substrate** (§4): every retrieval is a free micro-consolidation event. Use produces curation, rather than competing with it.
- **Nullable domain + audit** (§4): the user pays for taxonomy only when disagreement is surfaced, not prophylactically.

The corresponding null hypothesis for **Paper 2** is:

> **H2.** Under stationary usage intensity, Spikuit's per-Neuron human intervention time, averaged over a sliding window, decreases monotonically with $\Omega(t)$ after a warm-up phase. The decrease is independent of underlying LLM model capability (i.e. MAC shows the same slope under Haiku, Sonnet, and Opus curator agents).

This is what "architecture over accuracy" means empirically: if Spikuit's design works, *model upgrades do not change the slope*. Only the intercept moves. A KB whose MAC has the wrong slope cannot be rescued by a better LLM.

---

## 6. Why this grounds AMKB, not just Spikuit

AMKB is a protocol, not a product. The point of this appendix is that the cognitive model gives AMKB a principled specification — a target that any implementation can aim at and any competitor can evaluate against.

- **Required capabilities** (from §1): encode, store, consolidate, retrieve. All four must be first-class. A KB missing consolidation (e.g. a vector store + SRS bolt-on) does not qualify.
- **Required decomposition** (from §2): R × I × R with distinguishable recency time-scales. An AMKB whose "recency" conflates session and multi-month signals will have pathological retrieval at long horizons.
- **Required cost property** (from §5): sub-linear MAC. An AMKB whose maintenance scales linearly is a filesystem with branding.

Any implementation meeting these can be an AMKB. Spikuit is one — arguably the first to write the model down.

---

## 7. References

### Cognitive psychology / memory theory
- Atkinson, R. C. & Shiffrin, R. M. (1968). Human memory: a proposed system. In *Psychology of Learning and Motivation*, vol. 2, 89–195.
- Baddeley, A. D. & Hitch, G. (1974). Working memory. In *Psychology of Learning and Motivation*, vol. 8, 47–89.
- Tulving, E. & Thomson, D. M. (1973). Encoding specificity and retrieval processes in episodic memory. *Psychological Review*, 80(5), 352–373.
- Squire, L. R. & Kandel, E. R. (2009). *Memory: From Mind to Molecules* (2nd ed.). Roberts & Co.
- Roediger, H. L. & Butler, A. C. (2011). The critical role of retrieval practice in long-term retention. *Trends in Cognitive Sciences*, 15(1), 20–27.
- Antony, J. W., Ferreira, C. S., Norman, K. A. & Wimber, M. (2017). Retrieval as a fast route to memory consolidation. *Trends in Cognitive Sciences*, 21(8), 573–576.

### Zettelkasten and modern descendants
- Luhmann, N. (1992). *Kommunikation mit Zettelkästen*. (posthumous; English discussions in Schmidt, 2018).
- Ahrens, S. (2017). *How to Take Smart Notes*. Create Space.
- Xu, Y. et al. (2024). A-Mem: Agentic Memory for LLM Agents. *arXiv preprint*.
- (2024). AriGraph: Episodic Memory for Embodied Agents. *arXiv preprint*.

### Retrieval
- Robertson, S. & Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. *FnTIR*, 3(4).
- Lewis, P. et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *NeurIPS 2020*.

---

## 8. Related pages

- [Concepts](../concepts.md) — higher-level overview
- [Emergent Structure](emergent-structure.md) — how `domain` and `community` coexist
- [Spike-Circuit Correspondence](spike-circuit.md) — the dynamical-systems view
- [Information Retrieval & RAG](retrieval.md) — the pragmatic scoring formula
- [Spaced Repetition Systems](spaced-repetition.md) — FSRS v6 in Spikuit
