# Agent Reflection: Self-Improving Skills via a Sibling Brain

> **Claim.** Spikuit's Skills (curator, tutor, qabot, learn) improve over time by maintaining their own experiences as a separate knowledge graph — a *sibling Brain* isolated from the user's knowledge. The agent's reflections obey the same spike-circuit dynamics (FSRS, STDP, APPNP, consolidation) as user knowledge, with no retrieval-path overhead to the user-facing Brain.

This appendix describes the design pattern used to give Skills persistent, forgetting, self-organising memory of their own past actions. It assumes familiarity with [Spike-Circuit Correspondence](spike-circuit.md) and the [neuroscience](neuroscience.md) / [graph](graph.md) appendices.

---

## 1. Motivation

Skill outputs are graded by the user (accept / reject for curator proposals, quiz correctness for tutor explanations, QABot feedback). Without persistence, each run starts from scratch; the same mistakes recur. We want Skills to *learn from their mistakes* using only natural-language reflections — no model fine-tuning.

Two properties matter:

1. **Reflections must forget.** Stale lessons (about Neurons that have been merged, domains that have been renamed, user preferences that have shifted) should fade unless reinforced.
2. **The user-facing Brain must not pay for this.** Adding reflections into the same graph would inflate retrieval and spreading-activation cost on every user query. This is a hard constraint.

Both properties are satisfied by a design we call *Sibling Brain*.

---

## 2. Sibling Brain

### 2.1 Physical layout

```
my-project/
└── .spikuit/
    ├── circuit.db          # User Brain (retrieve, quiz, consolidate)
    ├── config.toml
    └── agent/              # Agent Brain (isolated)
        ├── circuit.db
        └── config.toml
```

The agent Brain is a full Spikuit Brain: its own graph, its own FSRS state, its own synapse weights, its own consolidation schedule. It is never touched by user-facing commands.

### 2.2 Reflections are Neurons

Each reflection is a Neuron in the agent Brain.

```python
Neuron(
    id = "refl-2026-04-22-curator-merge-reject-…",
    type = "reflection",
    domain = "curator",                       # or tutor, qabot, learn
    content = (
        "Proposed merging [user:neuron-abc] and [user:neuron-def]. "
        "User rejected: surface keywords overlap but purposes differ "
        "(abc is canonical, def is exemplar)."
    ),
    # FSRS fields identical to user Neurons
)
```

Cross-brain references are embedded as `[user:<neuron_id>]` tokens in the reflection text. The user Brain is never modified by the agent Brain.

### 2.3 Synapses between reflections

Two reflections that describe the same kind of mistake may become connected by STDP (co-firing within `tau_stdp`), or explicitly linked by the Skill when it generates them:

```
refl-1 ──relates_to──▶ refl-2
       └──contrasts──▶ refl-5   (this reflection became obsolete
                                  because the user later explicitly
                                  asked for that merge)
```

Community detection on the agent Brain then surfaces clusters of similar lessons.

---

## 3. Dynamics

All Spike-Circuit machinery applies unchanged. The agent Brain is itself a circuit whose dynamics mean:

### 3.1 Forgetting

A reflection that is not retrieved during later curator runs accumulates no fires; its FSRS stability decays; eventually the consolidation SWS phase prunes it. This is *spaced forgetting*: the Skill forgets what it no longer uses.

### 3.2 Reinforcement

When a reflection is retrieved and used, and the resulting proposal is accepted:

| Event | Grade on the reflection |
|---|---|
| Proposal accepted after consulting the reflection | `strong` |
| Proposal rejected despite consulting the reflection | `miss` |
| Reflection retrieved but not consulted | no event (natural decay) |

The reflection's stability rises with repeated successful use, falls with repeated failures. This is the same FSRS schedule that governs a user's knowledge.

### 3.3 STDP-driven generalisation

Reflections that fire together (e.g. different specific merges rejected for the same structural reason) grow connections. Over time, dense clusters form.

### 3.4 Consolidation as policy formation

`spkt consolidate` applied to the agent Brain performs:

- **Triage** — classify reflections by recency and fire pattern.
- **SHY** — globally decay weak synapses between stale reflections.
- **SWS** — remove reflections below the stability threshold.
- **REM** — detect communities of related reflections. Each community receives a `summarizes` summary Neuron, which is a *generalised policy* abstracted from specific cases.

A policy is therefore an emergent higher-level reflection — "don't merge Neurons that share surface keywords but differ in role" — generated automatically from repeated specific failures.

---

## 4. Skill Integration

### 4.1 Curator (v0.8.5 — first implementation)

Existing loop: propose → user accepts/rejects → `spkt consolidate` applies.

Extended loop:

1. Curator generates a candidate proposal on the user Brain.
2. Curator retrieves relevant reflections from the agent Brain (semantic similarity plus APPNP spreading from user Neurons referenced in the proposal).
3. Retrieved reflections modulate the proposal (strengthen, suppress, or annotate).
4. User accepts or rejects.
5. Outcome is recorded: existing reflections that were consulted get fired; a new reflection is added for rejected proposals.

The user Brain retrieval path is unchanged. The agent Brain retrieval happens only inside the curator Skill, not on every user query.

### 4.2 Tutor / QABot (v0.8.6)

Same pattern, different grading signal:

- **Tutor**: a reflection records the situation in which a hint failed; it is fired `strong` when a related hint later succeeds.
- **QABot**: a reflection records the generation style that produced a rejected answer; it is fired `strong` when a similar style is later accepted.

### 4.3 Single-Skill vs per-Skill agent Brain

In the initial implementation, all Skills share one agent Brain, differentiated by `domain`:

```
.spikuit/agent/circuit.db
    ├── domain=curator   reflections
    ├── domain=tutor     reflections
    └── domain=qabot     reflections
```

This allows cross-Skill learning to emerge (a curator reflection may inform a tutor Skill, via community detection spanning domains). If domain-specific isolation becomes necessary for performance or clarity, the agent Brain can be split into per-Skill Brains without schema changes.

---

## 5. CLI

The user-facing CLI is unchanged. Agent Brain operations are accessed through a dedicated subcommand:

```bash
spkt reflect list                 # recent reflections
spkt reflect inspect <id>         # full reflection detail
spkt reflect consolidate          # run consolidation on agent Brain
spkt reflect stats                # MAC and related metrics
spkt reflect disable              # disable reflection writing (debug)
```

Internally these dispatch through the existing multi-brain mechanism with `--brain .spikuit/agent`.

---

## 6. Metrics

The Sibling Brain design enables direct measurement of Skill improvement without model changes:

- **MAC (Maintenance Amortized Cost)** — user intervention time per unit of knowledge maintained, as a function of agent-Brain age.
- **Reflection acceptance rate** — proportion of reflections fired `strong` vs `miss` over successive consolidations.
- **Policy emergence rate** — number of summarizing Neurons formed in REM phases per unit time.
- **Model Scaling Coefficient** — MAC evaluated across Haiku / Sonnet / Opus runtimes, measuring the extent to which reflection compensates for model capability.

These metrics motivate an evaluation of the claim that *reflection infrastructure lowers maintenance cost independently of model progress*.

---

## 7. Connection to Spike-Circuit Correspondence

The agent Brain is itself a circuit. The same three readings of the synapse weight matrix (see [spike-circuit.md](spike-circuit.md)) hold:

- **Spike propagation** — a user action that references `[user:neuron-abc]` fires the agent-Brain Neurons synaptically connected to that reference, spreading activation across the reflection graph.
- **Retrieval as Hopfield descent** — the curator's search for relevant reflections is gradient descent in the agent Brain's energy landscape, with the current proposal as initial condition.
- **Eigenthemes** — the top Laplacian eigenvectors of the agent Brain correspond to recurring *families* of mistakes; these are the natural units into which REM consolidation groups reflections.

Forgetting, reinforcement, and policy formation are therefore not new mechanisms bolted onto Spikuit; they are specific readings of the same spectral structure, applied to a distinct ownership domain (the agent rather than the user).

---

## 8. Design Choices Deliberately Left Open

- **Privacy / deletion semantics** — resetting the agent Brain (forgetting all accumulated lessons) should be a simple directory removal; no user data is touched.
- **Sharing reflections across users** — out of scope for v0.8.5; feasible via future export format.
- **Adversarial reflections** — a poorly designed reflection could bias future proposals harmfully; mitigation (e.g. per-reflection audit trails, user-triggered invalidation) to be considered with daily-use feedback.
- **Cross-Brain synapses** — currently agent Brain references user Neurons via string tokens in `content`, not via first-class Synapse entities. A future extension could promote cross-brain references to Synapses for traversal efficiency, at the cost of coupling.

---

## 9. References

- Shinn, N., Cassano, F., Gopinath, A., Narasimhan, K. & Yao, S. (2023). Reflexion: Language Agents with Verbal Reinforcement Learning. *NeurIPS 2023*.
- Ebbinghaus, H. (1885). *Über das Gedächtnis*. (Foundational spacing / forgetting experiments.)
- Spikuit appendix: [spike-circuit.md](spike-circuit.md), [neuroscience.md](neuroscience.md), [graph.md](graph.md), [retrieval.md](retrieval.md), [spaced-repetition.md](spaced-repetition.md).
