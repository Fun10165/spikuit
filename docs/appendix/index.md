# Appendix: Algorithms & Technical Details

Spikuit draws on ideas from five fields. Each page covers the theory,
how Spikuit applies it, and key references.

1. [Computational Neuroscience](neuroscience.md) — STDP, LIF, spreading activation, sleep consolidation
2. [Cognitive & Developmental Psychology](psychology.md) — forgetting curve, testing effect, ZPD, scaffolding
3. [Spaced Repetition Systems](spaced-repetition.md) — FSRS v6, grade mapping
4. [Knowledge Graphs & Graph-Based ML](graph.md) — PageRank, APPNP, community detection
5. [Information Retrieval & RAG](retrieval.md) — hybrid retrieval, conversational curation
6. [Spike-Circuit Correspondence](spike-circuit.md) — theoretical grounding: spikes, retrieval, and eigenthemes as three readings of one operator
7. [Agent Reflection](agent-reflection.md) — Sibling Brain pattern: how Skills acquire self-improving memory via an isolated reflection graph
8. [Emergent Structure](emergent-structure.md) — how `domain` (user-declared, nullable) and `community` (emergent from Synapses) coexist, and when blanks get filled automatically
9. [Cognitive Retrieval & AMKB Memory Model](cognitive-retrieval.md) — four-stage cognitive model (encode/store/consolidate/retrieve), R×I×R decomposition of Spikuit's score, and why sub-linear MAC is the AMKB target

For implementation specifics (algorithms, parameters, embedding pipeline):

- [Implementation Details](implementation.md) — APPNP math, STDP updates, LIF model, plasticity parameters, embedder config, tech stack

For a higher-level overview, see [Concepts](../concepts.md).
