# Scaffold & Quiz

ZPD-inspired scaffolding and the Quiz protocol.

## Scaffold Computation

`compute_scaffold` and the [`Scaffold`](models.md) model are part of the
**`spikuit_core.appkit`** contract — the curated, semver-stable surface
that application packages (`spikuit-tutor`, `spikuit-agent-rag`) import
from. Application code should reach them as
`from spikuit_core.appkit import compute_scaffold, Scaffold`: that import
opts into the contract, where substrate internals may churn but the
appkit surface may not. `appkit` also re-exports `Grade`,
`ScaffoldLevel`, and `Spike`, plus the `SchedulerCircuit` and
`NeuronView` structural protocols an adapter programs against.

::: spikuit_core.compute_scaffold

## Quiz Protocol

The `BaseQuiz` protocol and its concrete implementations live in
`spikuit-tutor` — core is LLM-free and the grader-bound quiz types
belong with the tutor application package (extracted from `spikuit-cli`
in v0.7.x).

::: spikuit_tutor.quiz.BaseQuiz

::: spikuit_tutor.quiz.Flashcard
