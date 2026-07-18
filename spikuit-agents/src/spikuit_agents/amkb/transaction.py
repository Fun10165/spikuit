"""SpikuitStoreTransaction — sync amkb.Transaction over async Circuit.

The AMKB Transaction Protocol is synchronous and aborts by default if
the context body exits without an explicit ``commit()``. The Spikuit
Circuit transaction, by contrast, is async and commits on normal exit.
This module bridges the two by:

1. Imperatively driving Circuit.transaction()'s ``__aenter__`` /
   ``__aexit__`` across separate background-loop submissions, so a
   single Spikuit changeset spans the lifetime of an AMKB Transaction.
2. Tracking ``_state`` so a ``__exit__`` without ``commit()`` synthesizes
   an exception into the Circuit cm to trigger its abort path.

All buffered Spikuit `PendingEvent`s are translated into AMKB `Event`s
on `commit()`; the resulting `ChangeSet` is returned to the caller.
"""

from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from amkb.errors import (
    ECrossLayerInvalid,
    EEmptyContent,
    EInvalid,
    EInvalidRel,
    EMergeConflict,
    ENodeAlreadyRetired,
    ENodeNotFound,
    ESelfLoop,
    ETransactionClosed,
)
from amkb.refs import (
    ActorId,
    ChangeSetRef,
    EdgeRef,
    NodeRef,
    Timestamp,
    TransactionRef,
)
from amkb.types import (
    KIND_CONCEPT,
    KIND_SOURCE,
    LAYER_CONCEPT,
    LAYER_SOURCE,
    ChangeSet,
    Edge,
    Event,
    Node,
)
from spikuit_core.models import Neuron, SynapseType
from spikuit_core.transactions import (
    OP_NEURON_ADD,
    OP_NEURON_MERGE,
    OP_NEURON_RETIRE,
    OP_NEURON_UPDATE,
    OP_SYNAPSE_ADD,
    OP_SYNAPSE_RETIRE,
    OP_SYNAPSE_UPDATE,
    PendingEvent,
    SpikuitTransaction,
)

from spikuit_agents.amkb._ids import decode_edge_ref, encode_edge_ref
from spikuit_agents.amkb._loop import BackgroundLoop
from spikuit_agents.amkb.mapping import (
    dt_to_ts,
    neuron_to_node,
    rel_to_synapse_type,
    synapse_to_edge,
)

if TYPE_CHECKING:
    from spikuit_core import Circuit


class _AbortMarker(BaseException):
    """Synthetic exception used to drive Circuit's abort path."""


OP_TO_EVENT_KIND = {
    OP_NEURON_ADD: "node.created",
    OP_NEURON_UPDATE: "node.rewritten",
    OP_NEURON_RETIRE: "node.retired",
    OP_NEURON_MERGE: "node.merged",
    OP_SYNAPSE_ADD: "edge.created",
    OP_SYNAPSE_RETIRE: "edge.retired",
}


def _parse_payload(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def make_event(
    *,
    op: str,
    target_kind: str,
    target_id: str,
    before_json: str | None,
    after_json: str | None,
) -> Event | None:
    """Translate a Spikuit event tuple into an `amkb.Event`.

    Returns None for ops that have no AMKB analog (e.g. synapse.update).
    For ``OP_NEURON_MERGE`` the Spikuit ``after_json`` payload carries
    ``{"into": id, "sources": [...]}``; the source IDs are surfaced as
    ``meta.ancestors`` so L2 conformance can read the lineage.
    """
    kind = OP_TO_EVENT_KIND.get(op)
    if kind is None:
        return None
    target: NodeRef | EdgeRef
    if target_kind == "neuron":
        target = NodeRef(target_id)
    else:
        target = EdgeRef(target_id)

    before = _parse_payload(before_json)
    after = _parse_payload(after_json)
    meta: dict[str, Any] = {}
    if op == OP_NEURON_MERGE and after is not None:
        sources = after.get("sources") or []
        meta["ancestors"] = [NodeRef(s) for s in sources]

    return Event(
        kind=kind,  # type: ignore[arg-type]
        target=target,
        before=before,
        after=after,
        meta=meta,
    )


def _pending_to_event(pe: PendingEvent) -> Event | None:
    return make_event(
        op=pe.op,
        target_kind=pe.target_kind,
        target_id=pe.target_id,
        before_json=pe.before_json,
        after_json=pe.after_json,
    )


class SpikuitStoreTransaction:
    """Sync amkb.Transaction wrapper around an async Spikuit changeset."""

    def __init__(
        self,
        *,
        circuit: "Circuit",
        loop: BackgroundLoop,
        tag: str,
        actor_id: str,
        actor_kind: str,
    ) -> None:
        self._circuit = circuit
        self._loop = loop
        self.tag = tag
        self.actor = ActorId(actor_id)
        self._state: str = "open"
        self._cm: AbstractAsyncContextManager[SpikuitTransaction] | None = None
        self._spikuit_tx: SpikuitTransaction | None = None
        self._open(actor_id=actor_id, actor_kind=actor_kind)
        # Public ref required by the Protocol; populated after _open().
        assert self._spikuit_tx is not None
        self.ref = TransactionRef(self._spikuit_tx.id)

    # -- lifecycle ----------------------------------------------------------

    def _open(self, *, actor_id: str, actor_kind: str) -> None:
        async def _enter() -> tuple[
            AbstractAsyncContextManager[SpikuitTransaction], SpikuitTransaction
        ]:
            cm = self._circuit.transaction(
                tag=self.tag, actor_id=actor_id, actor_kind=actor_kind,  # type: ignore[arg-type]
            )
            tx = await cm.__aenter__()
            return cm, tx

        cm, tx = self._loop.run(_enter())
        self._cm = cm
        self._spikuit_tx = tx

    def __enter__(self) -> "SpikuitStoreTransaction":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._state == "open":
            try:
                self.abort()
            except Exception:
                if exc_type is None:
                    raise

    def _check_open(self) -> None:
        if self._state != "open":
            raise ETransactionClosed(
                f"transaction is {self._state}", state=self._state,
            )

    def commit(self) -> ChangeSet:
        self._check_open()
        self._state = "committing"
        assert self._cm is not None and self._spikuit_tx is not None
        events_snapshot = list(self._spikuit_tx.events)
        spikuit_tx = self._spikuit_tx

        async def _exit_ok() -> str:
            await self._cm.__aexit__(None, None, None)  # type: ignore[union-attr]
            row = await self._circuit._db.get_changeset(spikuit_tx.id)  # noqa: SLF001
            if row is None or row["committed_at"] is None:
                raise RuntimeError(
                    f"committed changeset {spikuit_tx.id} was not persisted"
                )
            return row["committed_at"]

        committed_at_iso = self._loop.run(_exit_ok())
        self._state = "committed"

        amkb_events: list[Event] = []
        for pe in events_snapshot:
            ev = _pending_to_event(pe)
            if ev is not None:
                amkb_events.append(ev)

        committed_at = dt_to_ts(datetime.fromisoformat(committed_at_iso))
        return ChangeSet(
            ref=ChangeSetRef(spikuit_tx.id),
            tx_ref=TransactionRef(spikuit_tx.id),
            tag=self.tag,
            actor=self.actor,
            committed_at=committed_at,
            events=tuple(amkb_events),
        )

    def abort(self) -> None:
        if self._state in ("aborted", "committed"):
            return
        self._state = "aborting"
        assert self._cm is not None

        async def _exit_abort() -> None:
            try:
                await self._cm.__aexit__(  # type: ignore[union-attr]
                    _AbortMarker, _AbortMarker(), None,
                )
            except _AbortMarker:
                pass

        self._loop.run(_exit_abort())
        self._state = "aborted"

    # -- node operations ----------------------------------------------------

    def create(
        self,
        *,
        kind: str,
        layer: str,
        content: str,
        attrs: dict[str, Any] | None = None,
    ) -> NodeRef:
        self._check_open()
        if kind == KIND_CONCEPT:
            if layer != LAYER_CONCEPT:
                raise ECrossLayerInvalid(
                    f"kind=concept requires layer=L_concept, got {layer!r}",
                    kind=kind, layer=layer,
                )
            if not content:
                raise EEmptyContent("concept content must be non-empty", kind=kind)
        elif kind == KIND_SOURCE:
            if layer != LAYER_SOURCE:
                raise ECrossLayerInvalid(
                    f"kind=source requires layer=L_source, got {layer!r}",
                    kind=kind, layer=layer,
                )
        else:
            raise EInvalid(f"unsupported kind for Spikuit backend: {kind!r}", kind=kind)

        attrs = attrs or {}
        spikuit_type = attrs.get("type") or (
            "source" if kind == KIND_SOURCE else "concept"
        )
        domain = attrs.get("domain")
        source = attrs.get("source")
        neuron = Neuron(
            id=f"n-{uuid4().hex[:12]}",
            content=content,
            type=spikuit_type,
            domain=domain,
            source=source,
        )

        async def _add() -> None:
            await self._circuit.add_neuron(neuron)

        self._loop.run(_add())
        return NodeRef(neuron.id)

    def rewrite(self, ref: NodeRef, *, content: str, reason: str) -> NodeRef:
        self._check_open()

        async def _do() -> NodeRef:
            db = self._circuit._db  # noqa: SLF001
            live = await db.get_neuron(str(ref))
            if live is None:
                any_neuron = await db.get_neuron(str(ref), include_retired=True)
                if any_neuron is None:
                    raise ENodeNotFound(f"node not found: {ref}", ref=str(ref))
                raise ENodeAlreadyRetired(
                    f"node is retired: {ref}", ref=str(ref),
                )
            updated = Neuron(
                id=live.id,
                content=content,
                type=live.type,
                domain=live.domain,
                source=live.source,
                created_at=live.created_at,
            )
            await self._circuit.update_neuron(updated)
            return ref

        return self._loop.run(_do())

    def retire(self, ref: NodeRef, *, reason: str) -> None:
        self._check_open()

        async def _do() -> None:
            await self._circuit.remove_neuron(str(ref))

        self._loop.run(_do())

    def merge(
        self,
        refs: list[NodeRef],
        *,
        content: str,
        attrs: dict[str, Any] | None = None,
        reason: str,
    ) -> NodeRef:
        self._check_open()
        if not refs:
            raise EInvalid("merge requires at least one source ref")

        async def _do() -> NodeRef:
            db = self._circuit._db  # noqa: SLF001
            ancestors = []
            kinds: set[str] = set()
            for r in refs:
                n = await db.get_neuron(str(r))
                if n is None:
                    any_neuron = await db.get_neuron(str(r), include_retired=True)
                    if any_neuron is None:
                        raise ENodeNotFound(
                            f"merge source not found: {r}", ref=str(r),
                        )
                    raise ENodeAlreadyRetired(
                        f"merge source is retired: {r}", ref=str(r),
                    )
                ancestors.append(n)
                # Source vs concept are different AMKB kinds — block
                # cross-kind merges before Spikuit even sees them.
                kinds.add("source" if n.type == "source" else "concept")
            if len(kinds) > 1:
                raise EMergeConflict(
                    f"cannot merge across kinds: {kinds}", kinds=list(kinds),
                )

            spikuit_type = (attrs or {}).get("type") or ancestors[0].type
            domain = (attrs or {}).get("domain") or ancestors[0].domain
            source = (attrs or {}).get("source")
            new_neuron = Neuron(
                id=f"n-{uuid4().hex[:12]}",
                content=content,
                type=spikuit_type,
                domain=domain,
                source=source,
            )
            await self._circuit.add_neuron(new_neuron)
            await self._circuit.merge_neurons(
                source_ids=[str(r) for r in refs],
                into_id=new_neuron.id,
            )
            # Spikuit's merge_neurons appends source content to the
            # target; restore the caller-supplied content so the new
            # node's body matches the AMKB merge contract.
            restored = Neuron(
                id=new_neuron.id,
                content=content,
                type=spikuit_type,
                domain=domain,
                source=source,
                created_at=new_neuron.created_at,
            )
            await self._circuit.update_neuron(restored)
            return NodeRef(new_neuron.id)

        return self._loop.run(_do())

    # -- edge operations ----------------------------------------------------

    def link(
        self,
        src: NodeRef,
        dst: NodeRef,
        *,
        rel: str,
        attrs: dict[str, Any] | None = None,
    ) -> EdgeRef:
        self._check_open()
        if str(src) == str(dst):
            raise ESelfLoop("self-loop is forbidden", src=str(src), dst=str(dst))
        try:
            stype = rel_to_synapse_type(rel)
        except ValueError as exc:
            raise EInvalidRel(str(exc), rel=rel) from exc
        weight = float((attrs or {}).get("weight", 0.5))

        async def _add() -> None:
            await self._circuit.add_synapse(
                str(src), str(dst), stype, weight=weight,
            )

        self._loop.run(_add())
        return encode_edge_ref(str(src), str(dst), stype.value)

    def unlink(self, ref: EdgeRef, *, reason: str) -> None:
        self._check_open()
        pre, post, rel = decode_edge_ref(ref)
        try:
            stype = rel_to_synapse_type(rel)
        except ValueError as exc:
            raise EInvalidRel(str(exc), rel=rel) from exc

        async def _do() -> None:
            await self._circuit.remove_synapse(pre, post, stype)

        self._loop.run(_do())

    # -- in-tx queries ------------------------------------------------------

    def get_node(self, ref: NodeRef) -> Node:
        self._check_open()

        async def _do() -> Node:
            db = self._circuit._db  # noqa: SLF001
            live = await db.get_neuron(str(ref))
            if live is not None:
                return neuron_to_node(live)
            any_neuron = await db.get_neuron(str(ref), include_retired=True)
            if any_neuron is None:
                raise ENodeNotFound(f"node not found: {ref}", ref=str(ref))
            retired_at = await db.get_neuron_retired_at(str(ref))
            return neuron_to_node(any_neuron, retired_at=retired_at)

        return self._loop.run(_do())

    def get_edge(self, ref: EdgeRef) -> Edge:
        self._check_open()
        pre, post, rel = decode_edge_ref(ref)
        try:
            stype = rel_to_synapse_type(rel)
        except ValueError as exc:
            raise EInvalidRel(str(exc), rel=rel) from exc

        async def _do() -> Edge:
            syn = await self._circuit.get_synapse(pre, post, stype)
            if syn is None:
                raise ENodeNotFound(f"edge not found: {ref}", ref=str(ref))
            return synapse_to_edge(syn)

        return self._loop.run(_do())
