# Quiz v2 — Unified Quiz abstraction

Design document for the Quiz rework shipping in v0.6.2 (#39) and v0.6.3 (#42).

Status: **Partially shipped** — the abstraction + Flashcard TUI shipped in
v0.6.2, FreeResponse followed, and `Cloze` (scaffold-directional vocab
recall) + `GeneratedQuiz` (type-agnostic renderer for stored `QuizItem`s,
i.e. the "quiz from the DB" origin of Principle 2) shipped post-v0.9.0.
MCQ / Reorder / Audio / ImageID, Tutor-driven generation, rubric grading,
and the Web Quiz UI (#44) remain future work. Body text below is the
original design and keeps its v0.6.x framing.

## Background

The pre-v0.6.2 quiz layer had two concrete classes in `spikuit-core`:

- `Flashcard`: Show neuron content at the current scaffold level; learner
  self-grades with miss/weak/fire/strong.
- `AutoQuiz`: LLM generates the question via a `generate_fn` callback and
  grades the answer via a `grade_fn` callback, with fallback to stored items
  or Flashcard-style display.

This split has two problems:

1. **`AutoQuiz` is not a quiz type** — it is a *source* of quizzes (LLM
   generation) combined with a *grader* (LLM). The quiz itself (multiple
   choice, free text, cloze, reorder, …) is never explicitly named.
2. **Core depends on LLM callbacks it cannot honor** — `spikuit-core` is
   declared LLM-independent, yet `AutoQuiz` ships the contract for LLM
   generation and grading inside the core package.

## Principles

1. **Every review goes through a `Quiz` instance.** There is no "raw neuron
   review" path — a Flashcard is just the simplest Quiz type.
2. **Quiz type is orthogonal to quiz origin.** The same `Flashcard` /
   `MultipleChoice` / `FreeText` / … types can come from the DB (a quiz
   previously generated and stored) or from a Tutor generator skill
   (on-demand LLM generation).
3. **Quiz owns its UI.** A Quiz instance knows how to render itself — as JSON
   (for frontends to overlay), as a Textual TUI, or as a GUI (when richer
   input is needed, e.g. audio or image).
4. **Grading is rubric-driven, not type-driven.** Mechanically-gradable
   quizzes grade themselves; others attach a rubric to the `QuizResult` and
   a Tutor grader skill scores them using only the rubric + canonical answer
   + student response.
5. **The core engine stays LLM-free.** All LLM interaction (generation,
   grading) lives in agent skills (`spkt-tutor/generators/`,
   `spkt-tutor/graders/`). The Quiz abstraction itself is in
   `spikuit-cli` — agents are always in the loop for quiz review.

## Architecture

```
                        ┌─────────────────────┐
                        │    BaseQuiz         │
                        │   (abstract)        │
                        └──────────┬──────────┘
                                   │
        ┌───────────┬──────────────┼──────────────┬────────────┐
        │           │              │              │            │
    Flashcard   MultipleChoice  FreeText       Cloze       Reorder ...
        │           │              │              │            │
        └───────────┴──────────────┴──────────────┴────────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                │                                     │
         [Path A] retrieve                     [Path B] generate
         DB lookup, stored QuizItems           Tutor generator skill
         filtered by scaffold_level            produces on-demand
                │                                     │
                └──────────────────┬──────────────────┘
                                   │
                                   ▼
                   render() → {mode, payload, submit_url}
                                   │
                   ┌───────────────┼───────────────┐
                   │               │               │
                 TUI             GUI             JSON
               (Textual)    (audio/image)    (frontend overlay)
                   │               │               │
                   └───────────────┼───────────────┘
                                   │
                                submit
                                   │
                                   ▼
                    grade(response) → QuizResult
                                   │
                          needs_tutor_grading?
                           yes ─┤      ├─ no
                                │      │
                   Tutor grader │      │ mechanical
                   skill        │      │
                                │      │
                                └───┬──┘
                                    │
                                    ▼
                         spkt neuron fire (FSRS + APPNP + STDP)
```

### Layers

| Layer | Lives in | Responsibility |
|---|---|---|
| `QuizItem`, `QuizRequest`, `QuizItemRole`, `Scaffold` | `spikuit-core` | Data models + DB persistence |
| `Circuit.add_quiz_item / get_quiz_items` | `spikuit-core` | Path A retrieval |
| `BaseQuiz`, concrete quiz types, renderers | `spikuit-cli` | Presentation + grading logic |
| `TutorSession.next_quiz` | `spikuit-cli` | Routing between retrieve and generate |
| Generator skills (`spkt-tutor/generators/*`) | `spikuit-cli/skills` | Path B — on-demand LLM generation |
| Grader skills (`spkt-tutor/graders/*`) | `spikuit-cli/skills` | Rubric-driven LLM grading |

The `AutoQuiz` class from pre-v0.6.2 is removed. A deprecation alias is left
behind for one minor version.

## Types

### `BaseQuiz`

```python
class BaseQuiz(ABC):
    """Every quiz type inherits from this."""

    quiz_type: ClassVar[str]  # "flashcard", "mcq", "free_text", ...

    def __init__(self, item: QuizItem, scaffold: Scaffold) -> None:
        self.item = item
        self.scaffold = scaffold
        self._submitted: asyncio.Event = asyncio.Event()
        self._response: QuizResponse | None = None

    @abstractmethod
    def front(self) -> RenderedContent: ...
    """Initial view (question side). Scaffold-aware."""

    @abstractmethod
    def back(self) -> RenderedContent: ...
    """Answer view (revealed after flip/submit)."""

    def render(self) -> RenderResponse:
        """Agent-facing render. Returns mode + payload + submit contract."""
        return RenderResponse(
            quiz_type=self.quiz_type,
            mode=self.preferred_mode(),  # "tui" | "gui" | "json"
            front=self.front(),
            back=self.back(),
            accepts_notes=True,
            grade_input=self.grade_input_spec(),
        )

    def preferred_mode(self) -> Literal["tui", "gui", "json"]:
        """Default: tui. Override for audio/image quizzes."""
        return "tui"

    async def submit(self, response: QuizResponse) -> None:
        self._response = response
        self._submitted.set()

    async def wait_for_submit(self) -> QuizResponse:
        await self._submitted.wait()
        assert self._response is not None
        return self._response

    @abstractmethod
    def grade(self, response: QuizResponse) -> QuizResult:
        """Mechanical grading where possible; otherwise flag for Tutor."""
        ...
```

### `QuizResponse`

```python
@dataclass
class QuizResponse:
    # Primary answer payload — interpretation depends on quiz_type
    answer: Any
    self_grade: Grade | None = None     # Required for Flashcard
    # Common, optional fields available on every quiz
    notes: str | None = None            # Free-text feedback from learner
    confidence: int | None = None       # 1–5 self-assessed confidence
    time_spent_ms: int | None = None    # Auto-recorded by UI
```

### `QuizResult`

```python
@dataclass
class QuizResult:
    grade: Grade | None                 # None if needs_tutor_grading
    needs_tutor_grading: bool = False
    grading_rubric: str | None = None   # Shown to Tutor grader skill
    canonical_answer: str | None = None
    student_response: str | None = None
    user_notes: str | None = None       # Lifted from QuizResponse.notes
    correctness: float | None = None    # 0.0–1.0, optional for partial credit
    feedback: str | None = None         # Agent-facing explanation
```

The `user_notes` field is present on every result so the downstream Tutor
session can always see the learner's extra input, regardless of quiz type.

## Quiz type catalog (target for v0.7.x)

| Type | UI | Grading | Notes |
|---|---|---|---|
| `Flashcard` | TUI | Mechanical (self-grade) | Shows neuron content, learner flips to see answer |
| `MultipleChoice` | TUI | Mechanical (choice match) | 2–5 options |
| `Cloze` | TUI | Mechanical (exact or fuzzy) | Fill-in-the-blank |
| `Reorder` | TUI | Mechanical (sequence match) | Drag-free — number-based reorder |
| `FreeText` | TUI | Tutor grader (rubric) | Long-form answer |
| `Audio` | GUI | Tutor grader + optional mechanical | Pronunciation, listening |
| `ImageID` | GUI | Mechanical or Tutor | Identify image content |

Shipped so far: `Flashcard`, `FreeText` (as `FreeResponseQuiz`), `Cloze`, plus `GeneratedQuiz` — not a row in this catalog but the renderer for any stored `QuizItem` regardless of type. The remaining rows are future work.

## Flashcard specifics

### Front / back

| Scaffold level | Front | Back |
|---|---|---|
| `FULL` (new concept) | Title + first paragraph | Full content |
| `GUIDED` (learning) | Title + hint line | Full content |
| `MINIMAL` (comfortable) | Title only | Full content |
| `NONE` (mastered) | Title only, no hints | Full content |

### TUI interaction

```
[Front]
┌─ Functor ──────────────────────────────────┐
│                                            │
│   # Functor                                │
│                                            │
│   (Recall, then press Space to flip)       │
│                                            │
├────────────────────────────────────────────┤
│ [Space] Flip  [n] Notes  [q] Quit          │
└────────────────────────────────────────────┘

     ↓ Space

[Back]
┌─ Functor ──────────────────────────────────┐
│ # Functor                                  │
│ ─────────                                  │
│ A structure-preserving map between         │
│ categories. Maps objects to objects and    │
│ morphisms to morphisms, preserving         │
│ identity and composition.                  │
│                                            │
│ Related: Category, Natural Transformation  │
├────────────────────────────────────────────┤
│ How well did you know this?                │
│   [1] Forgot    [2] Uncertain              │
│   [3] Got it    [4] Perfect                │
│                                            │
│ [n] Add note  [Space] Flip back  [q] Quit  │
└────────────────────────────────────────────┘
```

### Grade input

User-facing labels use numeric keys 1–4 as the primary input, with short
language-neutral labels as secondary text. Internal `Grade` enum is unchanged
(`MISS`/`WEAK`/`FIRE`/`STRONG` — these names reflect the neural firing
metaphor and stay in the data layer).

Mapping:

| Key | Label (EN) | Label (JA) | Internal Grade | FSRS |
|---|---|---|---|---|
| `1` | Forgot | 忘れた | `MISS` | Again |
| `2` | Uncertain | あやふや | `WEAK` | Hard |
| `3` | Got it | まあまあ | `FIRE` | Good |
| `4` | Perfect | 完璧 | `STRONG` | Easy |

Labels are localized via a small message catalog; `--no-emoji` disables the
emoji decoration if the user opts out.

CLI flag `spkt neuron fire -g <grade>` continues to accept both the word form
(`miss`/`weak`/`fire`/`strong`) and the numeric form (`1`/`2`/`3`/`4`) for
backward compatibility and scripting.

### Notes field

Pressing `n` on either side opens a single-line input for free-text feedback.
This lands in `QuizResponse.notes` and propagates to `QuizResult.user_notes`.
In v0.6.2 notes are stored on the spike record only; in v0.6.3 (#42) the
Tutor session begins consuming them for:

- Conflict detection (#17) — "this contradicts what you said yesterday"
- Ghost Neurons (#15) — unknown concepts referenced in notes become
  candidate neurons
- Feedback queue (#13) — batched review of learner questions

## Retrieve vs generate routing

```python
async def next_quiz(
    circuit: Circuit,
    neuron_id: str,
    scaffold: Scaffold,
    *,
    preferred_type: str = "flashcard",
    generate: GeneratorCallback | None = None,
) -> BaseQuiz:
    # Path A: try stored quiz items first
    items = await circuit.get_quiz_items(
        neuron_id, scaffold_level=scaffold.level
    )
    if items:
        item = random.choice(items)
        return quiz_from_item(item, scaffold)

    # Path B: no stored item → ask generator if one is wired up
    if generate is not None:
        item = await generate(
            QuizRequest(primary=neuron_id, scaffold=scaffold)
        )
        await circuit.add_quiz_item(item)
        return quiz_from_item(item, scaffold)

    # Fallback: Flashcard from raw neuron content (no generation needed)
    return Flashcard.from_neuron(
        await circuit.get_neuron(neuron_id), scaffold
    )
```

`generate` is the only LLM entry point in the quiz pipeline, and it is
injected from outside `spikuit-cli/quiz/`. In practice, `TutorSession` owns
the generator skill lookup and passes the callback to `next_quiz`.

## CLI shape

`spkt quiz` replaces the existing flashcard review loop with the Textual TUI.

```
spkt quiz                    # review all due neurons (default limit)
spkt quiz -n 20              # review up to 20 neurons
spkt quiz --domain math      # filter by domain
spkt quiz --type flashcard   # force quiz type (default: flashcard in v0.6.2)
spkt quiz --no-tui           # JSON mode: print RenderResponse, read stdin for submission
```

The `--no-tui` mode is the JSON contract that frontends and `spkt-tutor`
skills use. It reads a `QuizResponse` JSON object from stdin after printing
each `RenderResponse`, so agents can drive the loop without a terminal.

## Migration notes

The migration happens in two phases to avoid disrupting `TutorSession` in
`spikuit-core`, which currently depends on the legacy `Quiz` ABC.

### Phase 1 — v0.6.2 (this issue, #39)

- New `BaseQuiz` abstraction lives in `spikuit-cli/src/spikuit_cli/quiz/`
  — completely new code, does not touch `spikuit-core/quiz.py`.
- New `Flashcard` implementation in cli: uses `Circuit` directly for neuron
  content and FSRS recording; does not subclass the legacy core `Quiz` ABC.
- `spkt quiz` command rewired to the new Textual TUI and new `Flashcard`.
- Legacy `spikuit_core.quiz` (Quiz / Flashcard / AutoQuiz) stays in place
  untouched and continues to back `TutorSession`. Marked as deprecated in
  docstrings; removal deferred to Phase 2.
- `QuizResponse` / new-shape `QuizResult` live in `spikuit-cli.quiz.models`
  (not in core) for v0.6.2. If Phase 2 needs them in core, they promote.

### Phase 2 — v0.6.3 (#42 Tutor coaching improvements)

- Migrate `TutorSession` to the new Quiz v2 abstraction.
- Remove `spikuit_core/quiz.py` entirely.
- Leave deprecation aliases in `spikuit_core/__init__.py`:
  `spikuit_core.Flashcard` / `Quiz` / `AutoQuiz` emit a `DeprecationWarning`
  and point at `spikuit_cli.quiz` (raising `ImportError` if cli is not
  installed) — removed in v0.7.

### Kept throughout

- `QuizItem`, `QuizRequest`, `QuizItemRole` — still in `spikuit-core.models`.
- `Circuit.add_quiz_item` / `get_quiz_items` — still in core; used by Path A.
- `Scaffold`, `compute_scaffold` — scaffolding is a property of the
  neuron-and-graph state, not of the quiz layer.

### DB schema

`QuizItem` table is unchanged for v0.6.2. A new `spike_notes` column (nullable
TEXT) is added to the spike/review log so notes are persisted alongside the
grade. Migration is additive and does not require user action.

## Testing strategy

- **Unit tests** (`spikuit-cli/tests/test_quiz.py`):
  - `BaseQuiz.submit / wait_for_submit` happy path
  - `Flashcard.front / back` for each scaffold level
  - `Flashcard.grade` for numeric and word grade input
  - `QuizResponse` round-trip through `render_json` → `from_json`
- **Textual snapshot tests**:
  - Flashcard front view
  - Flashcard back view with grade bar
  - Notes input modal
  - Full review loop with 3 neurons
- **Integration**:
  - `spkt quiz --no-tui` drives a 2-neuron loop via stdin JSON
  - Notes persist to the spike log and survive a fresh circuit load

## Out of scope for v0.6.2

- Additional quiz types (MCQ / FreeText / Cloze / Reorder / Audio / ImageID)
  — FreeText and Cloze have since shipped; see the Status header
- Tutor-driven quiz generation
- Rubric-driven Tutor grading
- Web Quiz UI (#44)
- Batch quiz mode (#40) — deferred until after daily-use feedback

These are scheduled for v0.6.3 (#42) and later milestones.
