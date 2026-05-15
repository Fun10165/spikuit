# Emergent Structure

> **Why this page exists.** Most knowledge tools force you to tag, categorise, and folder your material up front. Spikuit lets structure emerge from connections and usage — but it still gives you a place to put labels when you have them. This page explains how those two impulses coexist.

## 1. Two kinds of structure

Spikuit separates knowledge organisation into two layers:

| Layer | Who decides | What it is | When it forms |
|---|---|---|---|
| **Domain** | You | A label you attach to a Neuron (e.g. `math`, `french`, `systems`) | At ingest (or later, or never) |
| **Community** | The graph | A cluster that emerges from the Synapse structure | Continuously, as you add and connect Neurons |

You can use both, either, or neither. They are meant to disagree sometimes — the disagreement is useful.

## 2. Domain: optional, nullable, user-owned

A `domain` is your taxonomy. You decide it. You can leave it blank:

```bash
spkt neuron add "# Hilbert space\n\nComplete inner-product space."
                                                # domain: null

spkt neuron add "# Hilbert space\n..." -d math
                                                # domain: math
```

Domain defaults to `null`. Spikuit does not guess. If you never declare one, your Neurons simply have no domain — and retrieval, review, and everything else works fine without it.

**Why nullable?** Deciding on a taxonomy up front is expensive, and it freezes the wrong tree before you know the shape of the forest. Most productive writing tools (Zettelkasten, Obsidian without folders, Roam) intentionally defer taxonomy. Spikuit follows that instinct, but does not forbid the opposite: if you already know your domains (a student in a single subject, a project with fixed sub-areas), declare them and move on.

## 3. Community: emerges from Synapses

A `community` is a cluster Spikuit discovers for you. It has no name you picked; it is a set of Neurons the graph treats as mutually related.

Communities form because you connect Neurons. You do not run a separate command to create them — they are recomputed whenever the graph changes.

```bash
spkt community list          # show current communities
spkt community detect        # force a recomputation
```

The communities are not folders. A Neuron belongs to at most one community (for now), but there is no naming ceremony, no hierarchy, and no assumption that today's communities will be tomorrow's.

## 4. How the two layers interact

The interesting question is what happens when both layers exist at once. Three cases:

### 4.1 You declared a domain, and the community agrees

The Neuron was tagged `math`, and it ends up in a community where most Neurons are also `math`. Nothing to do. Both layers tell the same story.

### 4.2 You declared a domain, and the community disagrees

The Neuron was tagged `math`, but the community it falls into is mostly `systems`. This is surfaced by `spkt domain audit`:

```bash
spkt domain audit
# => "12 Neurons have domain=math but sit in a systems-heavy community. Review?"
```

This is not an error — it is a signal. Maybe your Neuron really is a cross-cutting piece (category theory showing up in systems programming). Maybe the tag was a careless ingest. Spikuit does not overwrite your domain; it shows you the disagreement and lets you decide.

### 4.3 You left the domain blank

The Neuron has `domain: null`. `spkt domain audit` looks at the community it belongs to and tries to fill the blank:

1. **Clear fill**: the community is strongly dominated by one domain (e.g. 70% `math`). Spikuit fills the Neuron's domain to `math` automatically, logging the decision.
2. **Ambiguous fill**: the community has no dominant domain — most members are also `null`. Spikuit proposes a domain based on content inspection, but does not apply it without your approval.
3. **No fill**: neither signal is clear. Spikuit leaves it blank and moves on. You can always revisit later when more Neurons arrive.

In other words: the emergent layer serves the declared layer, not the other way around. Your tags are never overwritten without asking; blank tags are filled only when the graph's own evidence is strong.

## 5. Why this design

The cost of running a knowledge base comes in two buckets:

- **Ingest cost**: the effort to put something in.
- **Maintenance cost**: the effort to keep it usable as it grows.

Manual tagging is a large share of ingest cost. But removing it entirely pushes the weight onto retrieval: without any structure, you are left with pure vector search, which degrades as your Neuron count grows.

Spikuit's position is that you do not have to choose. You can tag when it is natural and cheap (you know the subject, the Neuron is obviously "math"), and skip when it is not (a thought you captured before you knew where it fit). The graph carries enough of its own structure — via Synapses you add over time, review, and spike propagation — that retrieval degrades gracefully on unlabelled material.

Over time, the emergent layer catches up with the declared layer. Communities stabilise. `domain audit` fills in blanks. A taxonomy forms without you having to design it first.

## 6. A note on vocabulary

You will not see words like "eigenvector", "Laplacian", or "spectral clustering" in normal Spikuit output. Internally those techniques are what compute the communities and the hub-weights, but the CLI hides them behind plain names:

| What the CLI calls it | What it is, technically |
|---|---|
| `community` | A hard cluster from spectral clustering on the graph Laplacian |
| **hub score** / `--hub-weight` | Eigenvector centrality |
| **theme score** / `--theme-weight` | Cosine similarity in eigentheme embedding space |
| **structural layout** | 2-D embedding from the Laplacian's low-frequency modes |

If you want the full theory, see [spike-circuit.md](spike-circuit.md). If you just want to organise your notes, you do not need to.

## 7. Related pages

- [Concepts](../concepts.md) — the higher-level mental model
- [Information Retrieval & RAG](retrieval.md) — how hub and theme scores feed retrieval
- [Knowledge Graphs](graph.md) — the underlying graph algorithms (APPNP, centrality)
- [Spike-Circuit Correspondence](spike-circuit.md) — the mathematical grounding (for the curious)
