# Scaffold & Quiz

ZPD-inspired scaffolding and the Quiz protocol.

## Scaffold Computation

::: spikuit_core.compute_scaffold

## Quiz Protocol

The `BaseQuiz` protocol and its concrete implementations live in
`spikuit-tutor` — core is LLM-free and the grader-bound quiz types
belong with the tutor application package (extracted from `spikuit-cli`
in v0.7.x).

::: spikuit_tutor.quiz.BaseQuiz

::: spikuit_tutor.quiz.Flashcard
