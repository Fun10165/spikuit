"""plan_exam() — builds an ExamPlan from circuit state + policy knobs.

This is where the survey's pedagogical decisions become concrete:
- Gap expansion (prerequisites before dependents)
- Interleaving (soft pull from near-due other domains)
- Quiz type selection by scaffold level (desirable difficulties)
- Follow-up attachment (elaborative interrogation)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from spikuit_core import ScaffoldLevel
from spikuit_core.scaffold import compute_scaffold

from ..quiz import BaseQuiz, Flashcard, FreeResponseQuiz
from ..quiz._content import extract_title
from .plan import ExamPlan, ExamStep, FollowUp, FollowUpGenerator, InterleaveMode

if TYPE_CHECKING:
    from spikuit_core import Circuit, Neuron, Scaffold


async def plan_exam(
    circuit: "Circuit",
    *,
    neuron_ids: list[str] | None = None,
    limit: int = 10,
    interleave_by: InterleaveMode = InterleaveMode.NONE,
    require_mastery: bool = False,
    elaborate_on_correct: bool = False,
    collect_confidence: bool = True,
    max_attempts: int = 3,
    interleave_pull_ratio: float = 0.20,
    near_due_days: int = 2,
    follow_up_generator: FollowUpGenerator | None = None,
) -> ExamPlan:
    """Construct an ExamPlan.

    If ``neuron_ids`` is provided, teach those (expanding gaps).
    Otherwise pull from ``circuit.due_neurons(limit=limit)``.
    """
    if neuron_ids is not None:
        ids = list(neuron_ids)
    else:
        ids = await circuit.due_neurons(limit=limit)

    scaffolds: dict[str, "Scaffold"] = {}

    def _scaffold(nid: str) -> "Scaffold":
        s = scaffolds.get(nid)
        if s is None:
            s = compute_scaffold(circuit, nid)
            scaffolds[nid] = s
        return s

    expanded: list[str] = []
    seen: set[str] = set()
    for nid in ids:
        for gap in _scaffold(nid).gaps:
            if gap not in seen:
                expanded.append(gap)
                seen.add(gap)
        if nid not in seen:
            expanded.append(nid)
            seen.add(nid)

    if interleave_by == InterleaveMode.DOMAIN and expanded:
        expanded = await _interleave_by_domain(
            circuit, expanded,
            pull_ratio=interleave_pull_ratio,
            near_due_days=near_due_days,
        )

    # Fetch all neurons in one pass; _interleave_by_domain may have added
    # near-due ids not in the original queue.
    neurons: dict[str, "Neuron"] = {}
    for nid in expanded:
        n = await circuit.get_neuron(nid)
        if n is not None:
            neurons[nid] = n

    steps: list[ExamStep] = []
    for nid in expanded:
        neuron = neurons.get(nid)
        if neuron is None:
            continue
        scaffold = _scaffold(nid)
        step = ExamStep(
            neuron_id=nid,
            quiz=_choose_quiz(neuron, scaffold),
            scaffold=scaffold,
        )

        if elaborate_on_correct and scaffold.context:
            anchor_id = scaffold.context[0]
            anchor = neurons.get(anchor_id) or await circuit.get_neuron(anchor_id)
            if anchor is not None:
                if follow_up_generator is not None:
                    fu = await follow_up_generator.generate_follow_up(
                        neuron=neuron, anchor=anchor, scaffold=scaffold,
                    )
                else:
                    fu = _build_follow_up(neuron, anchor)
                step.follow_ups.append(fu)
        steps.append(step)

    return ExamPlan(
        steps=steps,
        interleave_by=interleave_by,
        require_mastery=require_mastery,
        elaborate_on_correct=elaborate_on_correct,
        collect_confidence=collect_confidence,
        max_attempts=max_attempts,
        interleave_pull_ratio=interleave_pull_ratio,
        near_due_days=near_due_days,
    )


def _choose_quiz(neuron: "Neuron", scaffold) -> "BaseQuiz":
    """Desirable-difficulties mapping: strong cards (MINIMAL/NONE) get the
    harder free-response prompt; weaker cards (FULL/GUIDED) get the
    supportive Flashcard so the learner can rebuild the trace.
    """
    if scaffold.level in (ScaffoldLevel.MINIMAL, ScaffoldLevel.NONE):
        return FreeResponseQuiz(neuron, scaffold)
    return Flashcard(neuron, scaffold)


def _build_follow_up(neuron: "Neuron", anchor: "Neuron") -> FollowUp:
    neuron_title = extract_title(neuron.content) or neuron.id
    anchor_title = extract_title(anchor.content) or anchor.id
    return FollowUp(
        prompt=f"How does {neuron_title} relate to {anchor_title}?",
        rubric=(
            f"A good answer concretely connects {neuron_title} with "
            f"{anchor_title}, not just listing both in isolation."
        ),
        related_neuron_ids=[anchor.id],
    )


async def _interleave_by_domain(
    circuit: "Circuit",
    queue: list[str],
    *,
    pull_ratio: float,
    near_due_days: int,
) -> list[str]:
    """Soft interleave: if one domain dominates, pull near-due from
    other domains and interleave so the dominant domain doesn't run
    consecutively.
    """
    if len(queue) < 3:
        return queue

    domain_of: dict[str, str] = {}
    for nid in queue:
        neuron = await circuit.get_neuron(nid)
        if neuron is not None:
            domain_of[nid] = neuron.domain or "_none"

    neurons_by_domain: dict[str, list[str]] = {}
    for nid, d in domain_of.items():
        neurons_by_domain.setdefault(d, []).append(nid)

    dom_domain, dom_count = max(
        neurons_by_domain.items(), key=lambda x: len(x[1])
    )
    if dom_count / len(queue) <= 0.5:
        return queue

    pull_n = max(1, math.ceil(len(queue) * pull_ratio))
    near = await circuit.near_due_neurons(
        days_ahead=near_due_days,
        limit=pull_n * 3,
        exclude_ids=set(queue),
    )
    non_dom_pulled: list[str] = []
    for nid in near:
        neuron = await circuit.get_neuron(nid)
        if neuron is None:
            continue
        d = neuron.domain or "_none"
        if d != dom_domain:
            non_dom_pulled.append(nid)
            domain_of[nid] = d
        if len(non_dom_pulled) >= pull_n:
            break

    non_dom_buckets: dict[str, list[str]] = {}
    for d, ids in neurons_by_domain.items():
        if d != dom_domain:
            non_dom_buckets[d] = list(ids)
    for nid in non_dom_pulled:
        non_dom_buckets.setdefault(domain_of[nid], []).append(nid)

    dom_items = list(neurons_by_domain[dom_domain])
    non_dom_items = [
        nid for bucket in non_dom_buckets.values() for nid in bucket
    ]

    result: list[str] = []
    i = j = 0
    while i < len(non_dom_items) or j < len(dom_items):
        if i < len(non_dom_items):
            result.append(non_dom_items[i])
            i += 1
        if j < len(dom_items):
            result.append(dom_items[j])
            j += 1
    return result
