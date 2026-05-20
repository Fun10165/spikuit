# Scaffold & Quiz

ZPD-inspired scaffolding and the Quiz protocol.

## Scaffold Computation

`compute_scaffold` and its result types `Scaffold` / `ScaffoldLevel`
live in **`spikuit-tutor`**. As of v0.9.0 — the Stage 2 tutor
extraction — they are no longer part of the `spikuit_core.appkit`
contract: scaffolding reads FSRS card state, which the substrate no
longer holds. `compute_scaffold` reads card state from the tutor's
overlay store and graph topology from the substrate live, so it belongs
with the tutor application package. The `appkit` surface that adapters
program against is now `Grade`, `Spike`, `NeuronView`, and the
`SubstrateView` structural protocol.

::: spikuit_tutor.compute_scaffold

::: spikuit_tutor.Scaffold

::: spikuit_tutor.ScaffoldLevel

## Quiz Protocol

The `BaseQuiz` protocol and its concrete implementations live in
`spikuit-tutor` — core is LLM-free and the grader-bound quiz types
belong with the tutor application package (extracted from `spikuit-cli`
in v0.7.x).

::: spikuit_tutor.quiz.BaseQuiz

::: spikuit_tutor.quiz.Flashcard
