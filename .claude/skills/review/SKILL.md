---
name: review
description: "Run a spaced repetition review session using spkt CLI. Use when the user says /review, 'review', 'study', '復習', '復習しよう', '勉強', or similar."
---

# Review Session

Run an interactive review session using the spkt CLI.

## Steps

### 1. Get due neurons

```bash
spkt tutor due --json
```

If no neurons are due, tell the user and stop.

### 2. For each due neuron, run a review cycle

Loop through the due neurons one at a time:

#### 2a. Read the neuron content

```bash
spkt neuron inspect <neuron_id> --json
```

#### 2b. Generate a quiz question

Based on the neuron's content, type, and domain, generate an appropriate quiz question.

Guidelines for quiz generation:
- **concept**: Ask for a definition, explanation, or example
- **language**: Ask for translation, conjugation, or fill-in-the-blank
- **math**: Ask to state a theorem, prove a step, or solve a small problem
- Adapt difficulty based on FSRS state (Learning = easier, Review = harder)
- Include the neuron's neighbors for context if relevant

Present the question to the user and wait for their answer.

#### 2c. Grade the answer

Evaluate the user's response and assign a grade:
- `strong` — Perfect, immediate, confident
- `fire` — Correct, possibly with minor hesitation
- `weak` — Partially correct or needed a hint
- `miss` — Incorrect or couldn't answer

Tell the user the grade and briefly explain if they were wrong.

#### 2d. Record the result

```bash
spkt neuron fire <neuron_id> --grade <grade> --json
```

Show the updated FSRS state (next review date).

#### 2e. Ask to continue

After each neuron, ask if the user wants to continue or stop.

### 3. Session summary

When the session ends (no more due neurons or user stops), show:
- Number of neurons reviewed
- Grade distribution (how many strong/fire/weak/miss)
- Next upcoming review date

## Notes

- Always use `--json` when calling spkt for reliable parsing
- Keep the session conversational — encourage the user
- If the user asks for a hint, give one but downgrade to `weak` at best
- Respond in the user's language
