# Tutor extraction — Stage 1 design

**Status:** Reviewed — round 1 (2026-05-20) resolved Q1–Q5 (§8).
Design only, no implementation in this doc.
**Slot:** v0.8.x window (per `roadmap.md` §6). Stage 0 ships first (PR #66).
**Supersedes:** nothing. Extends `roadmap.md` §6 and the H3 staging in
`agent-workspace/contexts/active/spikuit-amkb-v03-tutor-extraction.md`.

## 1. Purpose

Stage 0 (PR #66) carved `spikuit-tutor` out of `spikuit-cli` as a
package-boundary move only — `spikuit-tutor` still imports
`spikuit-core` domain types directly. Stage 1 turns that raw coupling
into a **controlled contract**: a curated, semver-stable surface that
`spikuit-tutor` (and later `spikuit-agent-rag`) may import, behind
which the substrate internals can churn freely.

This matters because v0.8.x is the substrate self-organization
milestone (`substrate-self-organization.md`): `spikuit-core` internals
— `circuit`, `propagation`, `community`, `spectral`, `db` — are about
to change a lot. Without a contract surface, every substrate change
risks breaking the app layer silently.

Stage 1 deliberately does **not** migrate the database. FSRS columns
stay in `spikuit-core` until Stage 2. Stage 1 is additive and
reversible.

## 2. Current coupling — the facts

Measured against the post-Stage-0 tree (`spikuit-tutor/src/`).

### 2.1 What `spikuit-tutor` imports from `spikuit-core`

Seven files, twelve import sites, seven distinct symbols:

| Symbol | Kind | Used as | Files |
|---|---|---|---|
| `Grade` | `IntEnum` | runtime — compared `>=`, `==`; constructed | `tutor/session.py`, `quiz/{models,flashcard,tui}.py` |
| `ScaffoldLevel` | `str`-Enum | runtime — compared `==`, `in` | `tutor/builder.py`, `quiz/{flashcard,free_response}.py` |
| `Spike` | `msgspec.Struct` | runtime — constructed, passed to `circuit.fire` | `tutor/session.py` |
| `compute_scaffold` | function | runtime — called | `tutor/builder.py` |
| `Circuit` | class | type hint only (`TYPE_CHECKING`) | `tutor/{session,builder,plan}.py` |
| `Neuron` | `msgspec.Struct` | type hint only (`TYPE_CHECKING`) | `tutor/{builder,plan}.py`, `quiz/{flashcard,free_response}.py` |
| `Scaffold` | `msgspec.Struct` | type hint only (`TYPE_CHECKING`) | `tutor/{builder,plan}.py`, `quiz/{flashcard,free_response}.py` |

So the **runtime** coupling is four symbols (`Grade`, `ScaffoldLevel`,
`Spike`, `compute_scaffold`); `Circuit`, `Neuron`, `Scaffold` are
type-hint-only.

### 2.2 What `spikuit-tutor` calls on the injected `Circuit`

`spikuit-tutor` never constructs a `Circuit` — it receives one by
dependency injection (`TutorSession.__init__`, `plan_exam(circuit,…)`).
It calls exactly four methods:

```
circuit.fire(spike)            # session.py — record a review event
circuit.get_neuron(id)         # builder.py
circuit.due_neurons(...)       # builder.py
circuit.near_due_neurons(...)  # builder.py
```

### 2.3 Finding: `spikuit-tutor` does not touch FSRS columns

`roadmap.md` §6 describes Stage 1 as "tutor-app reads/writes core FSRS
columns by contract." That is imprecise. The `fsrs_state` table
(`neuron_id TEXT PK, card_json TEXT`) is read and written entirely
**inside** `Circuit` (`Circuit.fire`, `Circuit.get_card`,
`Circuit.due_neurons`). `spikuit-tutor` has no raw column access to
gate. **The contract surface is the `Circuit` method subset, not the
table.** Raw-column ownership only becomes a question at Stage 2, when
the table itself moves.

### 2.4 `compute_scaffold` is deeply substrate-coupled

`compute_scaffold(circuit, neuron_id) -> Scaffold` reads, in one call:
FSRS card state (`circuit.get_card`, `card.state`, `card.stability`),
graph topology (`circuit.neighbors`, `circuit.predecessors`), raw
networkx edge data (`circuit.graph[a][b]["type"]`), and imports the
`fsrs` package's `State` enum directly. It is a substrate-state query
that happens to return a tutor-facing recommendation. Relocating it
into `spikuit-tutor` would drag all of that surface — plus an `fsrs`
dependency — into the app layer. This design keeps it in
`spikuit-core` and exposes it through the contract.

## 3. What the contract must achieve

1. `spikuit-tutor/src/**` contains **zero** `from spikuit_core import …`
   reaching into substrate internals — verified by CI.
2. The symbols `spikuit-tutor` legitimately needs are still reachable,
   through one explicitly-versioned module.
3. Substrate internals (`circuit`, `propagation`, `community`,
   `spectral`, `db`, `models`) may be refactored during v0.8.x without
   touching `spikuit-tutor`.
4. The shape chosen does not get thrown away by Stage 2.

### 3.1 The enum constraint

`Grade` and `ScaffoldLevel` are compared by identity/value
(`grade >= Grade.FIRE`, `level == ScaffoldLevel.FULL`). A structural
`Protocol` cannot stand in for an enum — `spikuit-tutor` needs the
*actual* enum classes. Any design that claims "tutor defines its own
interfaces" still has to source these two enums from somewhere both
`spikuit-core` and `spikuit-tutor` agree on.

## 4. Design options

### 4.1 Option A — curated `spikuit_core.appkit` facade (recommended)

`spikuit-core` ships one new module, `spikuit_core/appkit.py`, that
re-exports the app-facing surface and nothing else:

```python
# spikuit-core/src/spikuit_core/appkit.py
"""Stable app-facing surface of spikuit-core.

Application packages (spikuit-tutor, spikuit-agent-rag) import ONLY
from spikuit_core.appkit — never from spikuit_core internals. This
module is the versioned contract; substrate internals may churn
freely behind it.
"""
from ._appkit_protocols import SchedulerCircuit, NeuronView
from .models import Grade, ScaffoldLevel, Scaffold, Spike
from .scaffold import compute_scaffold

__all__ = [
    "SchedulerCircuit", "NeuronView",
    "Grade", "ScaffoldLevel", "Scaffold", "Spike",
    "compute_scaffold",
]
```

`SchedulerCircuit` is a `Protocol` capturing exactly §2.2:

```python
# spikuit-core/src/spikuit_core/_appkit_protocols.py
class SchedulerCircuit(Protocol):
    async def fire(self, spike: Spike) -> object: ...
    async def get_neuron(self, neuron_id: str) -> NeuronView | None: ...
    async def due_neurons(self, *a, **k) -> list[object]: ...
    async def near_due_neurons(self, *a, **k) -> list[object]: ...
```

`spikuit-tutor` then imports type hints as `SchedulerCircuit` /
`NeuronView` instead of the concrete `Circuit` / `Neuron`. The real
`spikuit_core.Circuit` satisfies `SchedulerCircuit` structurally — no
runtime change, no wiring change in `spikuit-cli`.

Migration of the twelve sites:

| Before | After |
|---|---|
| `from spikuit_core import Grade, ScaffoldLevel, Spike` | `from spikuit_core.appkit import Grade, ScaffoldLevel, Spike` |
| `from spikuit_core.scaffold import compute_scaffold` | `from spikuit_core.appkit import compute_scaffold` |
| `from spikuit_core import Circuit` (TYPE_CHECKING) | `from spikuit_core.appkit import SchedulerCircuit` |
| `from spikuit_core import Neuron, Scaffold` (TYPE_CHECKING) | `from spikuit_core.appkit import NeuronView, Scaffold` |

**CI rule:** in `spikuit-tutor/src/**`, the only permitted spelling is
`from spikuit_core.appkit import …`. Any other `spikuit_core` import
fails the build.

`appkit` is **public, semver-stable API** — the rest of `spikuit_core`
is internal. That designation is what lets `appkit` double as the
contract a **custom adapter** programs against: a third party can build
their own adapter (a different scheduler, a spaced-export tool) on the
same surface `spikuit-tutor` uses, without reading substrate internals.
`spikuit-tutor` is then simply the first-party, pre-installed adapter —
not a privileged one.

- **Pros:** small, mechanical diff; no type relocation; no change to
  `Circuit.fire`; `compute_scaffold` stays where its dependencies are;
  fully reversible; Stage-2-ready (appkit is the single seam to edit
  when FSRS retires).
- **Cons:** `spikuit-tutor` still has a hard `spikuit-core` dependency
  and still installs the whole engine. The contract is "curated
  surface," not "package independence." The CI rule has one allowed
  prefix (`spikuit_core.appkit`) rather than a flat ban.

### 4.2 Option B — standalone `spikuit-substrate-api` package

A fifth workspace package holding the Protocols **and** the shared
value types (`Grade`, `ScaffoldLevel`, `Spike`, `Scaffold`).
`spikuit-core` imports its types *from* this package; `spikuit-tutor`
depends *only* on it, never on `spikuit-core`.

- **Pros:** true package independence — `spikuit-tutor` becomes
  installable and testable without the engine; the flat ban "no
  `spikuit_core` anywhere" is honest with no exceptions.
- **Cons:** relocating the enums forces an edit to every
  `spikuit-core` file that uses `Grade`/`Spike` (substrate-wide
  churn during the same window substrate self-organization is
  landing — exactly the collision `roadmap.md` §6 wants to avoid); a
  fifth package; `compute_scaffold` still cannot move (its `fsrs` and
  graph coupling), so it stays in core and the "independence" is
  partial anyway.

**A and B are not exclusive — B is the graduation of A.** Because the
CI import rule guarantees every app touches *only*
`spikuit_core.appkit`, promoting `appkit` to a standalone
`spikuit-substrate-api` package later is a mechanical packaging move:
publish the package, make `spikuit_core.appkit` a re-export shim
pointing at it, repoint the app `pyproject.toml` dependency. **No app
code changes** — the spelling `from spikuit_core.appkit import …` stays
valid across the move. So Stage 1 picks A; B is deferred until a real
third-party adapter ecosystem (or standalone-install demand) makes the
fifth package earn its cost. Choosing A now does not burn the B
bridge — it lays the first plank of it.

### 4.3 Rejected

- **`amkb.Store` extension namespace.** The `amkb` adapter lives in
  `spikuit-agents`; routing the tutor contract through it would make
  `spikuit-tutor` depend on `spikuit-agents`, violating the dependency
  direction (`agents → tutor`, never the reverse).
- **Pure consumer-defined Protocols, no shared module.** Breaks on the
  enum constraint (§3.1): `Grade` and `ScaffoldLevel` cannot be
  structural.

### 4.4 Packaging & the adapter ecosystem (out of Stage 1 scope)

Two future directions surfaced in review round 1. Both are **additive
and orthogonal to the A/B choice**, so neither blocks Stage 1 — but
they confirm why A (with `appkit` designated public) is the right
shape.

- **pip extras.** `pip install spikuit[tutor]` / `spikuit[rag]` /
  `spikuit[all]` is implementable today: Stage 0 already gave
  `spikuit-tutor` its own distributable boundary, and the umbrella
  `spikuit` package can declare `[project.optional-dependencies]`
  whenever wanted. It works identically under A or B — a contract
  package carries no engine, so a working tutor pulls in `spikuit-core`
  either way. Recommended default once extras land: bare
  `pip install spikuit` keeps today's behaviour (core + cli + tutor —
  do not break existing users), `spikuit[rag]` opt-in, `spikuit[all]`
  everything. This is a small standalone packaging task, slotted
  separately — not part of the Stage 1 contract work.
- **Custom adapters.** A first-class adapter SPI (registration,
  discovery, lifecycle) belongs to the longer adapter-abstraction arc,
  not Stage 1. But its *foundation* is exactly the appkit contract: a
  stable surface adapter authors depend on. Stage 1 delivers that
  foundation; the SPI is built on top later. Designating `appkit`
  public/semver-stable from day one (§4.1) is what keeps that path
  open, and `spikuit-tutor` becomes the first-party preinstalled
  adapter — fine to bundle, not privileged.

## 5. Recommended Stage 1 plan

Adopt **Option A**. Concretely:

1. Add `spikuit_core/_appkit_protocols.py` — `SchedulerCircuit`,
   `NeuronView` Protocols.
2. Add `spikuit_core/appkit.py` — the facade module above. Cover it
   with a test asserting `Circuit` satisfies `SchedulerCircuit` and
   `Neuron` satisfies `NeuronView` (`isinstance` with
   `runtime_checkable`, or a `mypy`-level assertion).
3. Repoint the twelve import sites in `spikuit-tutor/src/**` per the
   §4.1 table.
4. Add the CI import rule (§6).
5. Update the `spikuit-tutor` package docstring (it currently says
   "the `from spikuit_core` imports are replaced in Stage 1").
6. `docs/reference/` — `compute_scaffold` and `Scaffold` are now
   documented as the appkit surface.

No change to `Circuit`, to `Circuit.fire`'s signature, to the
database, or to `spikuit-cli` wiring. `spikuit-agents` keeps importing
`Grade` from wherever it does today (it is not an app package and is
out of scope for the ban — but moving it to `appkit` too is a
low-cost consistency win; see open question Q3).

## 6. CI enforcement

There is **no test or lint CI workflow today** — `.github/workflows/`
holds only `docs.yml` and `publish.yml`. Stage 1 must therefore add
the CI surface that the import rule runs in.

Proposal: a new `ci.yml` that runs (a) `pytest` per package and (b)
the import check. The import check, kept dependency-free:

```python
# tools/check_app_imports.py — fails if spikuit-tutor reaches past appkit
import ast, pathlib, sys

ALLOWED = {"spikuit_core.appkit"}
bad = []
for path in pathlib.Path("spikuit-tutor/src").rglob("*.py"):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("spikuit_core"):
            if node.module not in ALLOWED:
                bad.append(f"{path}:{node.lineno}: from {node.module}")
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name.startswith("spikuit_core") and n.name not in ALLOWED:
                    bad.append(f"{path}:{node.lineno}: import {n.name}")
if bad:
    print("\n".join(bad)); sys.exit(1)
```

If a linter is adopted later, this folds into `ruff`
(`flake8-tidy-imports` `banned-api`) — but an AST script needs no new
dependency and states the one allowed prefix explicitly.

## 7. Stage 2 interplay

Stage 2 retires the `fsrs_state` table from `spikuit-core` and moves
FSRS state into a `spikuit-tutor`-owned SQLite store, joined by
`atom_id`. After Stage 2, `Grade` and the FSRS card are unambiguously
tutor-domain.

Option A is built for that: at Stage 2, `appkit.py` is the **single
file to edit** — drop the FSRS-facing re-exports (`Grade`, `Spike`,
`compute_scaffold`), and `spikuit-tutor` repoints them to its own
modules. The `SchedulerCircuit` Protocol shrinks (no more `fire`).
Nothing in Option A is wasted.

Option B would have front-loaded the enum relocation into Stage 1 —
i.e. done part of Stage 2's hard work early, during the substrate
self-organization window. That is the sequencing `roadmap.md` §6
explicitly warns against.

## 8. Open questions for review

Review round 1 (2026-05-20) resolved Q1–Q5; resolutions recorded
inline.

- **Q1 — Option A vs B. → RESOLVED: adopt A.** A is the curated
  facade; B is reframed (§4.2) as a later *graduation* of A, not a
  competing option — deferred until a real third-party adapter
  ecosystem or standalone-install demand appears. The `appkit` surface
  is designated public/semver-stable so it can serve as the
  custom-adapter contract directly. pip extras and the custom-adapter
  SPI (§4.4) are additive and do not change this.
- **Q2 — `compute_scaffold` home. → RESOLVED: confirmed.** Stays in
  `spikuit-core`, exposed via `appkit` (its `fsrs` + graph coupling
  makes relocation expensive and premature).
- **Q3 — `spikuit-agents`. → RESOLVED: confirmed yes.** It also moves
  to `from spikuit_core.appkit import Grade` for consistency, even
  though it is out of scope for the enforced ban (not an app package).
- **Q4 — CI scope. → RESOLVED: confirmed both.** The new `ci.yml`
  runs the full `pytest` matrix *and* the import check — closing the
  missing test CI gap in the same PR.
- **Q5 — `roadmap.md` §6 wording. → RESOLVED: confirmed.** One-line
  correction to §6 ("FSRS columns by contract" → the `Circuit` method
  subset, per §2.3) lands together with Stage 1.

## 9. Effort & risk

| | |
|---|---|
| Diff size | Small — 1 new module + 1 protocols file + 12 repointed imports + 1 CI workflow + 1 check script. |
| Runtime risk | Near-zero — re-exports and structural typing; no behavior change. |
| Test risk | Low — existing suites cover the call paths; add one appkit conformance test. |
| Reversibility | Full — `appkit.py` can be deleted and imports reverted. |
| Blocking dependency | Stage 0 (PR #66) must merge first. |

## 10. Cross-references

- `roadmap.md` §6 — extraction workstream, Stage table, v0.8.x slot.
- `substrate-self-organization.md` §5 — names the "Spikuit-core
  extension interface" this doc designs.
- `agent-workspace/contexts/active/spikuit-amkb-v03-tutor-extraction.md`
  — H3 staging (Stage 0/1/2), canonical context.
- PR #66 — Stage 0 boundary move (prerequisite).
