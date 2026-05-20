"""Spikuit Circuit — the public API for the knowledge graph engine.

Circuit is the main entry point for spikuit-core. It owns the database,
the in-memory NetworkX graph, and exposes all operations external layers
(Quiz, CLI, agents) need.
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import networkx as nx

from .db import DEFAULT_DB_PATH, Database
from .embedder import Embedder, EmbeddingType, vec_to_blob
from .models import Grade, Neuron, Plasticity, QuizItem, QuizItemRole, Source, Spike, Synapse, SynapseConfidence, SynapseType
from .propagation import compute_propagation, compute_stdp, decay_all_pressure
from .transactions import (
    OP_NEURON_ADD,
    OP_NEURON_MERGE,
    OP_NEURON_RETIRE,
    OP_NEURON_UPDATE,
    OP_SYNAPSE_ADD,
    OP_SYNAPSE_RETIRE,
    OP_SYNAPSE_UPDATE,
    ActorKind,
    SpikuitTransaction,
    TransactionAbortedError,
    TransactionNestingError,
)


def _neuron_snapshot_json(neuron: Neuron) -> str:
    """Serialize a Neuron to a JSON snapshot for the event log."""
    import msgspec
    return msgspec.json.encode(neuron).decode()


def _synapse_snapshot_json(synapse: Synapse) -> str:
    """Serialize a Synapse to a JSON snapshot for the event log."""
    import msgspec
    return msgspec.json.encode(synapse).decode()


def _synapse_target_id(pre: str, post: str, stype: SynapseType | str) -> str:
    """Stable target_id for synapse events: 'pre|post|type'."""
    type_str = stype.value if isinstance(stype, SynapseType) else stype
    return f"{pre}|{post}|{type_str}"


class ReadOnlyError(Exception):
    """Raised when a mutating operation is attempted on a read-only Circuit."""


class Circuit:
    """The knowledge graph engine — NetworkX graph + propagation.

    Circuit is the main entry point for spikuit-core. It owns the database,
    the in-memory NetworkX graph, and exposes all operations that external
    layers (CLI, agents, sessions) need.

    As of Stage 2 (``tutor-extraction-stage2.md``) the substrate owns no
    learner model: FSRS scheduling — cards, ratings, due queues — lives
    wholly in ``spikuit-tutor``. ``fire`` records a review event and runs
    the grade-driven plasticity pipeline, but no longer schedules.

    Example:
        ```python
        circuit = Circuit(db_path="brain.db")
        await circuit.connect()

        neuron = Neuron.create("# Functor\\n\\nA mapping between categories.")
        await circuit.add_neuron(neuron)

        spike = Spike(neuron_id=neuron.id, grade=Grade.FIRE)
        await circuit.fire(spike)

        await circuit.close()
        ```

    Args:
        db_path: Path to the SQLite database file.
        plasticity: Tunable learning parameters (uses defaults if ``None``).
        embedder: Embedding provider for semantic search (optional).
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        plasticity: Plasticity | None = None,
        embedder: Embedder | None = None,
        read_only: bool = False,
    ) -> None:
        self._embedder = embedder
        self._read_only = read_only
        self._db: Database = Database(
            db_path,
            embedding_dimension=embedder.dimension if embedder else None,
        )
        self._graph: nx.DiGraph = nx.DiGraph()
        self.plasticity: Plasticity = plasticity or Plasticity()
        self._current_tx: SpikuitTransaction | None = None

    def _guard_readonly(self) -> None:
        """Raise ReadOnlyError if Circuit is in read-only mode."""
        if self._read_only:
            raise ReadOnlyError("Circuit is in read-only mode")

    # -- AMKB transactions (v0.7.0) -----------------------------------------

    @asynccontextmanager
    async def transaction(
        self,
        *,
        tag: str | None = None,
        actor_id: str,
        actor_kind: ActorKind = "agent",
    ) -> AsyncIterator[SpikuitTransaction]:
        """Open an explicit changeset.

        All mutations performed inside the block (in v0.7.0+ commits)
        are buffered as events and flushed atomically on exit. Raising
        an exception aborts the changeset.

        Args:
            tag: Caller-supplied label, e.g. "ingest:papers-2026".
            actor_id: Free-form identifier of who initiated the change.
            actor_kind: One of "human", "agent", "system".

        Raises:
            TransactionNestingError: If a transaction is already active
                on this Circuit (nested transactions are not supported
                in v0.7.0).
        """
        self._guard_readonly()
        if self._current_tx is not None:
            raise TransactionNestingError(
                f"transaction {self._current_tx.id} already active"
            )
        tx = SpikuitTransaction.open(
            tag=tag, actor_id=actor_id, actor_kind=actor_kind,
        )
        await self._db.insert_changeset_open(
            changeset_id=tx.id,
            tag=tx.tag,
            actor_id=tx.actor_id,
            actor_kind=tx.actor_kind,
            started_at=tx.started_at,
        )
        self._current_tx = tx
        try:
            yield tx
        except BaseException:
            tx.status = "aborted"
            self._current_tx = None
            await self._db.abort_changeset(tx.id)
            raise
        # Success path: flush buffered events and mark committed.
        self._current_tx = None
        events = [
            (
                e.op, e.target_kind, e.target_id,
                e.before_json, e.after_json, e.at,
            )
            for e in tx.events
        ]
        await self._db.commit_changeset(
            tx.id,
            events=events,
            committed_at=datetime.now(timezone.utc).isoformat(),
        )
        tx.status = "committed"

    @property
    def current_transaction(self) -> SpikuitTransaction | None:
        """Return the active transaction, if any. Adapter-only API."""
        return self._current_tx

    @asynccontextmanager
    async def _auto_tx(
        self, *, tag: str | None = None,
    ) -> AsyncIterator[SpikuitTransaction]:
        """Yield the current transaction, opening an implicit one if none.

        Implicit transactions are tagged as system actors so adapter
        consumers can distinguish them from explicit caller-driven
        changesets.
        """
        if self._current_tx is not None:
            yield self._current_tx
            return
        async with self.transaction(
            tag=tag, actor_id="system", actor_kind="system",
        ) as tx:
            yield tx

    # -- Lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Connect to DB and load the graph into memory."""
        await self._db.connect()
        await self._load_graph()
        await self._load_retrieval_boosts()

    async def close(self) -> None:
        await self._db.close()

    async def _load_graph(self) -> None:
        """Load all neurons (as nodes) and synapses (as edges) into NetworkX."""
        self._graph.clear()
        neurons = await self._db.list_neurons(limit=100_000)
        for n in neurons:
            self._graph.add_node(n.id, type=n.type, domain=n.domain)
        synapses = await self._db.get_all_synapses()
        for s in synapses:
            self._graph.add_edge(
                s.pre, s.post,
                type=s.type.value, weight=s.weight, co_fires=s.co_fires,
            )
        # Load community IDs into node data
        community_ids = await self._db.get_community_ids()
        for nid, cid in community_ids.items():
            if nid in self._graph:
                self._graph.nodes[nid]["community_id"] = cid

    async def _load_retrieval_boosts(self) -> None:
        """Load retrieval boosts from DB into graph node attributes."""
        boosts = await self._db.get_all_retrieval_boosts()
        for nid, boost in boosts.items():
            if nid in self._graph:
                self._graph.nodes[nid]["retrieval_boost"] = boost

    # -- Embedding helpers --------------------------------------------------

    def _prepare_embed_text(
        self,
        neuron: Neuron,
        searchable: dict[str, str] | None = None,
        max_searchable_chars: int = 500,
    ) -> str:
        """Build the text to embed for a neuron.

        Strips YAML frontmatter and prepends contextual prefixes that
        improve retrieval quality:

        - ``[Section: X]`` from frontmatter ``section`` field
        - ``[key: value]`` pairs from source searchable metadata

        Args:
            neuron: The neuron whose content to prepare.
            searchable: Source searchable metadata dict (optional).
            max_searchable_chars: Max total chars for searchable prefix.
        """
        from .models import _parse_frontmatter, strip_frontmatter

        fm = _parse_frontmatter(neuron.content)
        body = strip_frontmatter(neuron.content)

        prefix_parts: list[str] = []
        if fm.get("section"):
            prefix_parts.append(f"[Section: {fm['section']}]")

        if searchable:
            total = 0
            for key, value in searchable.items():
                part = f"[{key}: {value}]"
                if total + len(part) > max_searchable_chars:
                    break
                prefix_parts.append(part)
                total += len(part)

        if prefix_parts:
            return " ".join(prefix_parts) + " " + body
        return body

    # -- Neuron operations --------------------------------------------------

    async def add_neuron(self, neuron: Neuron) -> Neuron:
        """Add a Neuron to the circuit.

        Auto-embeds content if an embedder is configured. The substrate
        creates no FSRS card — scheduling state is the tutor's, created
        lazily on first review (``tutor-extraction-stage2.md`` §4.4).

        Args:
            neuron: The neuron to add.

        Returns:
            The same neuron (pass-through for chaining).
        """
        self._guard_readonly()
        async with self._auto_tx(tag="neuron.add") as tx:
            await self._db.insert_neuron(neuron)
            self._graph.add_node(neuron.id, type=neuron.type, domain=neuron.domain)

            # Auto-embed if embedder is available
            if self._embedder is not None:
                text = self._embedder.apply_prefix(
                    self._prepare_embed_text(neuron), EmbeddingType.DOCUMENT,
                )
                vec = await self._embedder.embed(text)
                await self._db.upsert_embedding(neuron.id, vec_to_blob(vec))

            tx.emit(
                OP_NEURON_ADD, "neuron", neuron.id,
                after_json=_neuron_snapshot_json(neuron),
            )

        return neuron

    async def get_neuron(self, neuron_id: str) -> Neuron | None:
        return await self._db.get_neuron(neuron_id)

    async def list_neurons(self, **kwargs: object) -> list[Neuron]:
        return await self._db.list_neurons(**kwargs)  # type: ignore[arg-type]

    async def update_neuron(self, neuron: Neuron) -> None:
        self._guard_readonly()
        prior = await self._db.get_neuron(neuron.id)
        async with self._auto_tx(tag="neuron.update") as tx:
            await self._db.update_neuron(neuron)
            if neuron.id in self._graph:
                self._graph.nodes[neuron.id]["type"] = neuron.type
                self._graph.nodes[neuron.id]["domain"] = neuron.domain
            # Re-embed on content change
            if self._embedder is not None:
                text = self._embedder.apply_prefix(
                    self._prepare_embed_text(neuron), EmbeddingType.DOCUMENT,
                )
                vec = await self._embedder.embed(text)
                await self._db.upsert_embedding(neuron.id, vec_to_blob(vec))
            tx.emit(
                OP_NEURON_UPDATE, "neuron", neuron.id,
                before_json=_neuron_snapshot_json(prior) if prior else None,
                after_json=_neuron_snapshot_json(neuron),
            )

    async def remove_neuron(self, neuron_id: str) -> None:
        """Soft-retire a neuron and cascade-retire its synapses.

        The neuron row stays in the database with ``retired_at`` set,
        preserving spike history. Its vector row is physically deleted
        to keep ANN recall undegraded. Synapses touching the neuron are
        cascade-retired. A ``neuron.retire`` event plus one
        ``synapse.retire`` event per cascaded synapse are emitted in
        the current (or implicit) transaction.
        """
        self._guard_readonly()
        neuron = await self._db.get_neuron(neuron_id)
        if neuron is None:
            return  # already retired or never existed — idempotent
        before = _neuron_snapshot_json(neuron)
        async with self._auto_tx(tag="neuron.retire") as tx:
            retired_at_ts = datetime.now(timezone.utc).isoformat()
            retired_synapses = await self._db.soft_retire_neuron(
                neuron_id, retired_at_ts,
            )
            tx.emit(
                OP_NEURON_RETIRE,
                "neuron",
                neuron_id,
                before_json=before,
                after_json=None,
            )
            for (pre, post, stype) in retired_synapses:
                tx.emit(
                    OP_SYNAPSE_RETIRE,
                    "synapse",
                    f"{pre}|{post}|{stype}",
                    before_json=None,
                    after_json=None,
                )
        if neuron_id in self._graph:
            self._graph.remove_node(neuron_id)

    # -- Quiz item operations -----------------------------------------------

    async def add_quiz_item(self, item: QuizItem) -> QuizItem:
        """Persist a quiz item with neuron associations.

        Args:
            item: The quiz item to store. Must have at least one neuron in
                ``neuron_ids`` with the ``PRIMARY`` role.

        Returns:
            The persisted QuizItem (with auto-generated ID if empty).

        Raises:
            ValueError: If no primary neuron is specified.
        """
        if not item.primary_neuron_ids:
            raise ValueError("QuizItem must have at least one PRIMARY neuron.")
        await self._db.insert_quiz_item(item)
        return item

    async def get_quiz_items(
        self,
        neuron_id: str,
        *,
        role: QuizItemRole | None = None,
        scaffold_level: str | None = None,
    ) -> list[QuizItem]:
        """Get quiz items associated with a neuron.

        Args:
            neuron_id: The neuron to look up.
            role: Filter by role (primary/supporting). ``None`` = any role.
            scaffold_level: Filter by scaffold-level label. ``None`` = any level.

        Returns:
            List of matching QuizItems, newest first.
        """
        return await self._db.get_quiz_items(
            neuron_id, role=role, scaffold_level=scaffold_level,
        )

    async def remove_quiz_item(self, item_id: str) -> None:
        """Delete a quiz item by ID."""
        await self._db.delete_quiz_item(item_id)

    # -- Synapse operations -------------------------------------------------

    async def add_synapse(
        self,
        pre: str,
        post: str,
        type: SynapseType,
        weight: float = 0.5,
        confidence: SynapseConfidence = SynapseConfidence.EXTRACTED,
        confidence_score: float = 1.0,
    ) -> list[Synapse]:
        """Add a Synapse between two neurons.

        Bidirectional types (``contrasts``, ``relates_to``) automatically
        create the reverse edge as well.

        Args:
            pre: Source neuron ID.
            post: Target neuron ID.
            type: Connection semantics.
            weight: Initial edge weight (default ``0.5``).
            confidence: Provenance tag (EXTRACTED, INFERRED, AMBIGUOUS).
            confidence_score: Confidence score (0.0–1.0, meaningful for INFERRED).

        Returns:
            List of created synapses (1 for directed, 2 for bidirectional).

        Raises:
            ValueError: If either neuron does not exist in the circuit.
        """
        self._guard_readonly()
        if pre not in self._graph or post not in self._graph:
            raise ValueError(
                f"Both neurons must exist in the circuit. "
                f"pre={pre!r} exists={pre in self._graph}, "
                f"post={post!r} exists={post in self._graph}"
            )

        created: list[Synapse] = []

        async with self._auto_tx(tag="synapse.add") as tx:
            synapse = Synapse(
                pre=pre, post=post, type=type, weight=weight,
                confidence=confidence, confidence_score=confidence_score,
            )
            await self._db.insert_synapse(synapse)
            self._graph.add_edge(
                pre, post, type=type.value, weight=weight, co_fires=0,
            )
            created.append(synapse)
            tx.emit(
                OP_SYNAPSE_ADD, "synapse",
                _synapse_target_id(pre, post, type),
                after_json=_synapse_snapshot_json(synapse),
            )

            if type.is_bidirectional:
                reverse = Synapse(
                    pre=post, post=pre, type=type, weight=weight,
                    confidence=confidence, confidence_score=confidence_score,
                )
                await self._db.insert_synapse(reverse)
                self._graph.add_edge(
                    post, pre, type=type.value, weight=weight, co_fires=0,
                )
                created.append(reverse)
                tx.emit(
                    OP_SYNAPSE_ADD, "synapse",
                    _synapse_target_id(post, pre, type),
                    after_json=_synapse_snapshot_json(reverse),
                )

        return created

    async def get_synapse(
        self, pre: str, post: str, type: SynapseType
    ) -> Synapse | None:
        return await self._db.get_synapse(pre, post, type)

    async def remove_synapse(
        self, pre: str, post: str, type: SynapseType
    ) -> None:
        """Soft-retire a synapse and emit a retire event.

        Bidirectional types retire both directions.
        """
        self._guard_readonly()
        async with self._auto_tx(tag="synapse.retire") as tx:
            at = datetime.now(timezone.utc).isoformat()
            did = await self._db.soft_retire_synapse(pre, post, type, at)
            if self._graph.has_edge(pre, post):
                self._graph.remove_edge(pre, post)
            if did:
                tx.emit(
                    OP_SYNAPSE_RETIRE, "synapse",
                    _synapse_target_id(pre, post, type),
                )
            if type.is_bidirectional:
                did_r = await self._db.soft_retire_synapse(post, pre, type, at)
                if self._graph.has_edge(post, pre):
                    self._graph.remove_edge(post, pre)
                if did_r:
                    tx.emit(
                        OP_SYNAPSE_RETIRE, "synapse",
                        _synapse_target_id(post, pre, type),
                    )

    async def list_synapses(
        self,
        neuron_id: str | None = None,
        type: SynapseType | None = None,
    ) -> list[Synapse]:
        """List synapses, optionally filtered by neuron or type.

        Args:
            neuron_id: If given, return synapses where this neuron is pre or post.
            type: If given, filter to this synapse type.

        Returns:
            List of matching synapses.
        """
        if neuron_id is not None:
            outgoing = await self._db.get_synapses_from(neuron_id)
            incoming = await self._db.get_synapses_to(neuron_id)
            # Deduplicate (bidirectional types appear in both)
            seen: set[tuple[str, str, str]] = set()
            synapses: list[Synapse] = []
            for s in outgoing + incoming:
                key = (s.pre, s.post, s.type.value)
                if key not in seen:
                    seen.add(key)
                    synapses.append(s)
        else:
            synapses = await self._db.get_all_synapses()

        if type is not None:
            synapses = [s for s in synapses if s.type == type]

        return synapses

    async def set_synapse_weight(
        self,
        pre: str,
        post: str,
        type: SynapseType,
        weight: float,
    ) -> Synapse:
        """Set the weight of an existing synapse.

        Args:
            pre: Source neuron ID.
            post: Target neuron ID.
            type: Synapse type.
            weight: New weight value.

        Returns:
            The updated Synapse.

        Raises:
            ValueError: If the synapse does not exist.
        """
        self._guard_readonly()
        synapse = await self._db.get_synapse(pre, post, type)
        if synapse is None:
            raise ValueError(f"Synapse not found: {pre!r} → {post!r} ({type.value})")
        before = _synapse_snapshot_json(synapse)
        async with self._auto_tx(tag="synapse.weight") as tx:
            synapse.weight = weight
            await self._db.update_synapse(synapse)
            if self._graph.has_edge(pre, post):
                self._graph[pre][post]["weight"] = weight
            tx.emit(
                OP_SYNAPSE_UPDATE, "synapse",
                _synapse_target_id(pre, post, type),
                before_json=before,
                after_json=_synapse_snapshot_json(synapse),
            )
        return synapse

    async def merge_neurons(
        self,
        source_ids: list[str],
        into_id: str,
    ) -> dict:
        """Merge multiple neurons into a target neuron.

        Content from source neurons is appended to the target. Synapses are
        redirected, source links transferred, and source neurons removed.

        Args:
            source_ids: IDs of neurons to merge (will be deleted).
            into_id: ID of the target neuron (survives).

        Returns:
            Summary dict with merge statistics.

        Raises:
            ValueError: If any neuron does not exist or into_id is in source_ids.
        """
        self._guard_readonly()

        if into_id in source_ids:
            raise ValueError("into_id must not be in source_ids")

        target = await self._db.get_neuron(into_id)
        if target is None:
            raise ValueError(f"Target neuron not found: {into_id!r}")

        sources_to_merge = []
        for sid in source_ids:
            n = await self._db.get_neuron(sid)
            if n is None:
                raise ValueError(f"Source neuron not found: {sid!r}")
            sources_to_merge.append(n)

        async with self._auto_tx(tag="neuron.merge") as tx:
            before_target = _neuron_snapshot_json(target)

            # 1. Append content
            merged_content = target.content
            for n in sources_to_merge:
                merged_content += "\n\n---\n\n" + n.content
            target.content = merged_content
            await self._db.update_neuron(target)

            # 2. Redirect synapses
            synapses_redirected = 0
            for sid in source_ids:
                for s in await self._db.get_synapses_from(sid):
                    if s.post == into_id or s.post in source_ids:
                        continue
                    existing = await self._db.get_synapse(into_id, s.post, s.type)
                    if existing is None:
                        new_syn = Synapse(pre=into_id, post=s.post, type=s.type, weight=s.weight)
                        await self._db.insert_synapse(new_syn)
                        self._graph.add_edge(into_id, s.post, type=s.type.value, weight=s.weight, co_fires=0)
                        synapses_redirected += 1
                        tx.emit(
                            OP_SYNAPSE_ADD, "synapse",
                            _synapse_target_id(into_id, s.post, s.type),
                            after_json=_synapse_snapshot_json(new_syn),
                        )

                for s in await self._db.get_synapses_to(sid):
                    if s.pre == into_id or s.pre in source_ids:
                        continue
                    existing = await self._db.get_synapse(s.pre, into_id, s.type)
                    if existing is None:
                        new_syn = Synapse(pre=s.pre, post=into_id, type=s.type, weight=s.weight)
                        await self._db.insert_synapse(new_syn)
                        self._graph.add_edge(s.pre, into_id, type=s.type.value, weight=s.weight, co_fires=0)
                        synapses_redirected += 1
                        tx.emit(
                            OP_SYNAPSE_ADD, "synapse",
                            _synapse_target_id(s.pre, into_id, s.type),
                            after_json=_synapse_snapshot_json(new_syn),
                        )

            # 3. Transfer source attachments
            sources_transferred = 0
            for sid in source_ids:
                neuron_sources = await self._db.get_sources_for_neuron(sid)
                for src in neuron_sources:
                    await self._db.attach_source(into_id, src.id)
                    sources_transferred += 1

            # 4. Retire source neurons (shares the merge changeset)
            import msgspec
            from datetime import datetime, timezone
            for sid in source_ids:
                await self.remove_neuron(sid)
                await self._db.insert_predecessor(
                    into_id, sid,
                    datetime.now(timezone.utc).isoformat(),
                )

            # 5. Re-embed target
            if self._embedder is not None:
                text = self._embedder.apply_prefix(
                    self._prepare_embed_text(target), EmbeddingType.DOCUMENT,
                )
                vec = await self._embedder.embed(text)
                await self._db.upsert_embedding(into_id, vec_to_blob(vec))

            # 6. Update in-memory graph node
            if into_id in self._graph:
                self._graph.nodes[into_id]["content"] = target.content

            # 7. Emit a single merge event on the target.
            merge_payload = msgspec.json.encode({
                "into": into_id,
                "sources": list(source_ids),
            }).decode()
            tx.emit(
                OP_NEURON_MERGE, "neuron", into_id,
                before_json=before_target,
                after_json=merge_payload,
            )

        return {
            "merged": len(source_ids),
            "into": into_id,
            "synapses_redirected": synapses_redirected,
            "sources_transferred": sources_transferred,
        }

    async def predecessors_of_lineage(self, neuron_id: str) -> list[str]:
        """Return parent neuron IDs recorded when ``neuron_id`` absorbed them.

        Adapter-only read API for AMKB L2 lineage conformance.
        """
        return await self._db.get_predecessors(neuron_id)

    async def prune_retired(self) -> dict[str, int]:
        """Physically delete all soft-retired neurons and synapses.

        Escape hatch for ``spkt history prune``. Event log is preserved.
        Does not emit events — this is historical garbage collection,
        not a lifecycle transition.
        """
        self._guard_readonly()
        return await self._db.prune_retired_neurons()

    # -- _meta neurons ------------------------------------------------------

    async def upsert_meta_neuron(self, meta_id: str, content: str) -> Neuron:
        """Create or replace a _meta domain neuron.

        _meta neurons are auto-generated descriptions of the Brain itself.
        They participate in retrieve() but are excluded from due/fire.

        Args:
            meta_id: The neuron ID (e.g. ``"_meta:overview"``).
            content: Markdown content for the neuron.

        Returns:
            The created or updated Neuron.
        """
        self._guard_readonly()
        existing = await self._db.get_neuron(meta_id)
        if existing:
            existing.content = content
            existing.updated_at = datetime.now(timezone.utc)
            await self._db.update_neuron(existing)
            if meta_id in self._graph:
                self._graph.nodes[meta_id]["content"] = content
            if self._embedder:
                await self._embed_neuron(existing)
            return existing

        neuron = Neuron(
            id=meta_id,
            content=content,
            type="meta",
            domain="_meta",
        )
        await self._db.insert_neuron(neuron)
        self._graph.add_node(neuron.id, type="meta", domain="_meta")
        if self._embedder:
            await self._embed_neuron(neuron)
        return neuron

    async def clear_meta_neurons(self) -> int:
        """Remove all _meta domain neurons.

        Returns:
            Number of neurons removed.
        """
        self._guard_readonly()
        meta_ids = [
            nid for nid in self._graph.nodes
            if self._graph.nodes[nid].get("domain") == "_meta"
        ]
        for nid in meta_ids:
            await self.remove_neuron(nid)
        return len(meta_ids)

    async def generate_manual(self, *, write_meta: bool = False) -> dict:
        """Generate a user guide for this Brain.

        Returns a dict with domain overview, sample topics, knowledge cutoff,
        coverage notes, and source attribution. Optionally writes _meta neurons.

        Args:
            write_meta: If True, upsert _meta neurons with manual content.

        Returns:
            Dict with keys: domains, cutoff, coverage, sources, neuron_count.
        """
        # Gather domain info (exclude _meta)
        domain_info: dict[str, dict] = {}
        for nid, data in self._graph.nodes(data=True):
            domain = data.get("domain") or "uncategorized"
            if domain == "_meta":
                continue
            if domain not in domain_info:
                domain_info[domain] = {"count": 0, "neurons": []}
            domain_info[domain]["count"] += 1
            domain_info[domain]["neurons"].append(nid)

        # For each domain, pick representative topics (highest centrality)
        centrality = nx.degree_centrality(self._graph) if self._graph else {}
        domains: list[dict] = []
        for domain, info in sorted(domain_info.items(), key=lambda x: -x[1]["count"]):
            # Top neurons by centrality
            ranked = sorted(info["neurons"], key=lambda n: centrality.get(n, 0), reverse=True)
            top_ids = ranked[:5]
            topics = []
            for nid in top_ids:
                n = await self._db.get_neuron(nid)
                if n:
                    title = n.content.split("\n")[0].lstrip("# ").strip()
                    if title:
                        topics.append(title)
            limited = info["count"] < 5
            domains.append({
                "name": domain,
                "neuron_count": info["count"],
                "topics": topics,
                "limited_coverage": limited,
            })

        # Knowledge cutoff: latest source fetch date
        sources = await self._db.list_sources()
        cutoff = None
        source_list: list[dict] = []
        for src in sources:
            if src.fetched_at and (cutoff is None or src.fetched_at > cutoff):
                cutoff = src.fetched_at
            source_list.append({
                "id": src.id,
                "title": src.title or src.url or src.id,
                "url": src.url,
                "fetched_at": src.fetched_at.isoformat() if src.fetched_at else None,
            })

        total_neurons = sum(1 for nid in self._graph.nodes
                           if self._graph.nodes[nid].get("domain") != "_meta")

        result = {
            "neuron_count": total_neurons,
            "domains": domains,
            "cutoff": cutoff.isoformat() if cutoff else None,
            "sources": source_list,
        }

        if write_meta:
            # Overview
            overview_lines = [f"# Brain Overview\n\nThis brain contains {total_neurons} neurons across {len(domains)} domains.\n"]
            for d in domains:
                coverage = " (limited coverage)" if d["limited_coverage"] else ""
                overview_lines.append(f"- **{d['name']}**: {d['neuron_count']} neurons{coverage}")
            await self.upsert_meta_neuron("_meta:overview", "\n".join(overview_lines))

            # Per-domain coverage
            for d in domains:
                topics_str = ", ".join(d["topics"]) if d["topics"] else "no topics yet"
                content = f"# {d['name']} domain\n\n{d['neuron_count']} neurons. Topics: {topics_str}."
                await self.upsert_meta_neuron(f"_meta:coverage:{d['name']}", content)

            # Cutoff
            cutoff_str = cutoff.strftime("%Y-%m-%d") if cutoff else "no sources fetched"
            await self.upsert_meta_neuron(
                "_meta:cutoff",
                f"# Knowledge Cutoff\n\nLatest source fetch: {cutoff_str}.",
            )

            # Examples
            example_lines = ["# Sample Questions\n"]
            for d in domains:
                if d["topics"]:
                    example_lines.append(f"## {d['name']}")
                    for topic in d["topics"][:3]:
                        example_lines.append(f"- What is {topic}?")
                    example_lines.append("")
            await self.upsert_meta_neuron("_meta:examples", "\n".join(example_lines))

        return result

    # -- Spike (fire) -------------------------------------------------------

    async def fire(self, spike: Spike) -> None:
        """Record a review event and run the grade-driven plasticity pipeline.

        As of Stage 2 (``tutor-extraction-stage2.md`` §4.2) the substrate
        no longer schedules: ``fire`` records the spike and runs the
        plasticity steps, but FSRS card state is the tutor's. The tutor
        is the review orchestrator now — it schedules with FSRS, then
        calls ``fire`` as a callee. The pipeline here is:

        1. Record spike to DB
        2. APPNP: propagate activation to neighbors (pressure deltas)
        3. Reset source neuron pressure
        4. STDP: update edge weights based on co-fire timing
        5. Record last-fire timestamp for future STDP

        Args:
            spike: The review event to process.
        """
        self._guard_readonly()
        # Guard: auto-generated neurons are not reviewable
        node_data = self._graph.nodes.get(spike.neuron_id, {})
        if node_data.get("domain") == "_meta" or node_data.get("type") == "community_summary":
            raise ValueError(
                f"Cannot fire auto-generated neuron {spike.neuron_id!r}: "
                "auto-generated neurons are not reviewable."
            )
        # 1. Record spike
        await self._db.insert_spike(spike)

        # 2. APPNP propagation → update neighbor pressures
        deltas = compute_propagation(
            self._graph, spike.neuron_id, spike.grade, self.plasticity,
        )
        now_iso = spike.fired_at.isoformat()
        for nid, delta in deltas.items():
            node_data = self._graph.nodes[nid]
            current = node_data.get("pressure", 0.0)
            node_data["pressure"] = current + delta
            node_data["pressure_updated_at"] = now_iso

        # 3. Reset source neuron's pressure (post-fire reset)
        if spike.neuron_id in self._graph:
            self._graph.nodes[spike.neuron_id]["pressure"] = self.plasticity.pressure_reset
            self._graph.nodes[spike.neuron_id]["pressure_updated_at"] = now_iso

        # 4. STDP edge updates
        stdp_updates = compute_stdp(
            self._graph, spike.neuron_id, spike.grade,
            spike.fired_at, self.plasticity,
        )
        for pre, post, new_weight, is_co_fire in stdp_updates:
            # Update in-memory graph
            self._graph[pre][post]["weight"] = new_weight
            if is_co_fire:
                self._graph[pre][post]["co_fires"] = (
                    self._graph[pre][post].get("co_fires", 0) + 1
                )

            # Persist to DB
            syn = await self._db.get_synapse(pre, post, SynapseType(self._graph[pre][post]["type"]))
            if syn is not None:
                syn = Synapse(
                    pre=syn.pre, post=syn.post, type=syn.type,
                    weight=new_weight,
                    co_fires=self._graph[pre][post].get("co_fires", 0),
                    last_co_fire=spike.fired_at if is_co_fire else syn.last_co_fire,
                )
                await self._db.update_synapse(syn)

        # 5. Record last fire time on the node (for STDP timing)
        if spike.neuron_id in self._graph:
            self._graph.nodes[spike.neuron_id]["last_fired_at"] = now_iso

    async def get_spikes_for(
        self, neuron_id: str, *, limit: int = 50
    ) -> list[Spike]:
        """Review events recorded for a neuron, newest first.

        Public on the app contract as of Stage 2 (§4.3): the tutor's
        relocated ``progress`` report needs review history, and the
        substrate's own ``consolidate``/``diagnose`` triage now reads the
        ``spike`` table directly instead of FSRS card state.
        """
        return await self._db.get_spikes_for(neuron_id, limit=limit)

    # -- Pressure -----------------------------------------------------------

    def get_pressure(self, neuron_id: str) -> float:
        """Get the current LIF pressure for a neuron."""
        if neuron_id not in self._graph:
            return 0.0
        return self._graph.nodes[neuron_id].get("pressure", 0.0)

    def _set_pressure(self, neuron_id: str, value: float) -> None:
        """Set pressure directly (for testing / manual override)."""
        if neuron_id in self._graph:
            self._graph.nodes[neuron_id]["pressure"] = value
            self._graph.nodes[neuron_id]["pressure_updated_at"] = (
                datetime.now(timezone.utc).isoformat()
            )

    def decay_pressure(self, *, now: datetime | None = None) -> None:
        """Apply LIF leak to all neuron pressures."""
        if now is None:
            now = datetime.now(timezone.utc)
        decay_all_pressure(self._graph, now, self.plasticity)

    # -- Retrieval boost ----------------------------------------------------

    def get_retrieval_boost(self, neuron_id: str) -> float:
        if neuron_id not in self._graph:
            return 0.0
        return self._graph.nodes[neuron_id].get("retrieval_boost", 0.0)

    def set_retrieval_boost(self, neuron_id: str, value: float) -> None:
        if neuron_id in self._graph:
            self._graph.nodes[neuron_id]["retrieval_boost"] = value

    async def commit_retrieval_boosts(self) -> None:
        """Persist all in-memory retrieval boosts to DB."""
        updates = {}
        for nid in self._graph.nodes:
            boost = self._graph.nodes[nid].get("retrieval_boost", 0.0)
            if boost != 0.0:
                updates[nid] = boost
        if updates:
            await self._db.batch_set_retrieval_boosts(updates)

    # -- Retrieve -----------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[Neuron]:
        """Retrieve neurons matching a query with graph-weighted scoring.

        Scoring formula::

            score = max(keyword_sim, semantic_sim)
                    × (1 + centrality + pressure + boost)

        ``semantic_sim`` uses sqlite-vec KNN when an embedder is configured;
        otherwise only keyword matching is used. ``boost`` is accumulated
        through [`QABotSession`][spikuit_core.QABotSession] feedback.

        As of Stage 2 (``tutor-extraction-stage2.md`` §4.3) the score
        carries no FSRS retrievability term — the substrate ranks by its
        own signals only. A tutor wanting memory-aware retrieval pushes a
        per-neuron weight through ``set_retrieval_boost`` instead.

        Args:
            query: Search query text.
            limit: Maximum number of results.
            filters: Key-value filters. ``type`` and ``domain`` filter on the
                neuron table; other keys filter on source filterable metadata.
                Strict semantics: neurons without the key are excluded.

        Returns:
            List of matching neurons, sorted by score descending.
        """
        if not query.strip():
            return []

        query_lower = query.lower()
        keywords = query_lower.split()
        if not keywords:
            return []

        # Pre-filter neuron IDs if filters provided
        allowed_ids: set[str] | None = None
        if filters:
            allowed_ids = await self._db.get_filtered_neuron_ids(filters)

        # Compute degree centrality (no scipy needed, unlike PageRank)
        centrality_map: dict[str, float] = {}
        if self._graph.number_of_nodes() > 1:
            centrality_map = nx.degree_centrality(self._graph)

        # Semantic similarity via embeddings (if available)
        semantic_scores: dict[str, float] = {}
        if self._embedder is not None and self._db.has_embeddings:
            query_text = self._embedder.apply_prefix(query, EmbeddingType.QUERY)
            query_vec = await self._embedder.embed(query_text)
            query_blob = vec_to_blob(query_vec)
            # Fetch more candidates than limit to allow re-ranking
            knn_results = await self._db.knn_search(query_blob, limit=limit * 3)
            if knn_results:
                # Convert L2 distance to similarity score (0-1)
                max_dist = max(d for _, d in knn_results) or 1.0
                for nid, dist in knn_results:
                    semantic_scores[nid] = max(0.0, 1.0 - dist / (max_dist + 1e-6))

        # Collect candidate neuron IDs (keyword matches + semantic matches)
        all_neurons = await self._db.list_neurons(limit=1000)
        neuron_map = {n.id: n for n in all_neurons}

        scored: list[tuple[float, Neuron]] = []
        seen: set[str] = set()

        for n in all_neurons:
            if allowed_ids is not None and n.id not in allowed_ids:
                continue
            content_lower = n.content.lower()
            hits = sum(1 for kw in keywords if kw in content_lower)
            keyword_sim = hits / len(keywords) if hits > 0 else 0.0
            sem_sim = semantic_scores.get(n.id, 0.0)
            text_sim = max(keyword_sim, sem_sim)

            if text_sim == 0.0:
                continue

            centrality_norm = centrality_map.get(n.id, 0.0)
            pressure = self.get_pressure(n.id)

            boost = self.get_retrieval_boost(n.id)
            score = text_sim * (1.0 + centrality_norm + pressure + boost)
            scored.append((score, n))
            seen.add(n.id)

        # Include semantic-only hits not caught by keyword scan
        for nid, sem_sim in semantic_scores.items():
            if nid in seen or sem_sim == 0.0:
                continue
            if allowed_ids is not None and nid not in allowed_ids:
                continue
            n = neuron_map.get(nid)
            if n is None:
                continue
            centrality_norm = centrality_map.get(n.id, 0.0)
            pressure = self.get_pressure(n.id)
            score = sem_sim * (1.0 + centrality_norm + pressure)
            scored.append((score, n))

        # Community boost: identify dominant community from top-K, boost same-community
        if self.plasticity.community_weight > 0 and scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            top_k = scored[:5]
            community_counts: dict[int, int] = {}
            for _, n in top_k:
                cid = self._graph.nodes.get(n.id, {}).get("community_id")
                if cid is not None:
                    community_counts[cid] = community_counts.get(cid, 0) + 1
            if community_counts:
                dominant_cid = max(community_counts, key=community_counts.get)  # type: ignore[arg-type]
                for i, (s, n) in enumerate(scored):
                    ncid = self._graph.nodes.get(n.id, {}).get("community_id")
                    if ncid == dominant_cid:
                        scored[i] = (s * (1.0 + self.plasticity.community_weight), n)

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [n for _, n in scored[:limit]]

        if results:
            await self._db.log_retrieve(query, [n.id for n in results])

        return results

    # -- Ensemble -----------------------------------------------------------

    def ensemble(self, neuron_id: str, *, hops: int = 2) -> list[str]:
        """Get the N-hop neighborhood of a neuron.

        Args:
            neuron_id: Center neuron.
            hops: Radius of the ego graph (default 2).

        Returns:
            List of neighbor neuron IDs (excluding the center).
        """
        if neuron_id not in self._graph:
            return []
        subgraph = nx.ego_graph(self._graph, neuron_id, radius=hops)
        return [nid for nid in subgraph.nodes if nid != neuron_id]

    # -- Graph introspection ------------------------------------------------

    def neighbors(self, neuron_id: str) -> list[str]:
        """Direct successors (outgoing synapses)."""
        if neuron_id not in self._graph:
            return []
        return list(self._graph.successors(neuron_id))

    def predecessors(self, neuron_id: str) -> list[str]:
        """Direct predecessors (incoming synapses)."""
        if neuron_id not in self._graph:
            return []
        return list(self._graph.predecessors(neuron_id))

    def edge_type(self, pre: str, post: str) -> str | None:
        """Synapse type of the edge ``pre → post``, or ``None`` if there
        is no such edge.

        A read-only topology accessor on the app contract (Stage 2 §4.5):
        it lets app code (e.g. the tutor's ``compute_scaffold``) read an
        edge's type without importing NetworkX or touching ``.graph``.
        """
        edge = self._graph.get_edge_data(pre, post)
        if edge is None:
            return None
        return edge.get("type", "relates_to")

    @property
    def neuron_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def synapse_count(self) -> int:
        return self._graph.number_of_edges()

    @property
    def graph(self) -> nx.DiGraph:
        """Direct access to the NetworkX graph (read-only use)."""
        return self._graph

    # -- Embedding backfill -------------------------------------------------

    async def embed_all(self, *, batch_size: int = 32) -> int:
        """Backfill embeddings for all neurons that don't have one yet.

        Args:
            batch_size: Number of texts to embed per API call.

        Returns:
            Number of neurons newly embedded.
        """
        if self._embedder is None:
            return 0
        all_neurons = await self._db.list_neurons(limit=100_000)
        to_embed: list[Neuron] = []
        for n in all_neurons:
            rows = await self._db.conn.execute_fetchall(
                "SELECT 1 FROM neuron_vec_map WHERE neuron_id = ?", (n.id,)
            )
            if not rows:
                to_embed.append(n)
        if not to_embed:
            return 0

        # Preload searchable metadata for neurons with sources
        searchable_map: dict[str, dict[str, str]] = {}
        for n in to_embed:
            sources = await self._db.get_sources_for_neuron(n.id)
            for src in sources:
                if src.searchable:
                    searchable_map[n.id] = src.searchable
                    break  # use first source with searchable

        count = 0
        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i : i + batch_size]
            texts = [
                self._embedder.apply_prefix(
                    self._prepare_embed_text(n, searchable=searchable_map.get(n.id)),
                    EmbeddingType.DOCUMENT,
                )
                for n in batch
            ]
            vecs = await self._embedder.embed_batch(texts)
            for n, vec in zip(batch, vecs):
                await self._db.upsert_embedding(n.id, vec_to_blob(vec))
                count += 1
        return count

    # -- Source operations --------------------------------------------------

    async def add_source(self, source: Source) -> Source:
        """Add a Source to the circuit.

        Args:
            source: The source to persist.

        Returns:
            The same source (pass-through for chaining).
        """
        await self._db.insert_source(source)
        return source

    async def get_source(self, source_id: str) -> Source | None:
        return await self._db.get_source(source_id)

    async def find_source_by_url(self, url: str) -> Source | None:
        return await self._db.find_source_by_url(url)

    async def get_sources_for_neuron(self, neuron_id: str) -> list[Source]:
        return await self._db.get_sources_for_neuron(neuron_id)

    async def attach_source(self, neuron_id: str, source_id: str) -> None:
        """Link a source to a neuron (idempotent)."""
        await self._db.attach_source(neuron_id, source_id)

    async def detach_source(self, neuron_id: str, source_id: str) -> None:
        """Remove the link between a neuron and a source."""
        await self._db.detach_source(neuron_id, source_id)

    async def list_sources(self, *, limit: int = 100) -> list[Source]:
        """List sources."""
        return await self._db.list_sources(limit=limit)

    async def get_source(self, source_id: str) -> Source | None:
        """Get a source by ID."""
        return await self._db.get_source(source_id)

    async def update_source(self, source: Source) -> None:
        """Update source fields (pass the modified Source object)."""
        await self._db.update_source(source)

    async def get_neurons_for_source(self, source_id: str) -> list[str]:
        """Get neuron IDs attached to a source."""
        return await self._db.get_neurons_for_source(source_id)

    async def get_meta_keys(self) -> list[dict]:
        """Get distinct filterable/searchable keys with counts."""
        return await self._db.get_meta_keys()

    async def get_meta_values(self, key: str) -> list[dict]:
        """Get distinct values for a metadata key."""
        return await self._db.get_meta_values(key)

    async def get_domain_counts(self) -> list[dict]:
        """Get domain names with neuron counts."""
        return await self._db.get_domain_counts()

    async def get_stale_sources(self, stale_days: int) -> list:
        """Get URL sources older than stale_days since last fetch."""
        return await self._db.get_stale_sources(stale_days)

    async def rename_domain(self, old: str, new: str) -> int:
        """Rename all neurons with domain=old to domain=new."""
        count = await self._db.rename_domain(old, new)
        # Update in-memory graph
        for nid in self._graph.nodes:
            if self._graph.nodes[nid].get("domain") == old:
                self._graph.nodes[nid]["domain"] = new
        return count

    async def merge_domains(self, sources: list[str], target: str) -> int:
        """Merge multiple domains into target."""
        count = await self._db.merge_domains(sources, target)
        for nid in self._graph.nodes:
            if self._graph.nodes[nid].get("domain") in sources:
                self._graph.nodes[nid]["domain"] = target
        return count

    # -- Community detection ------------------------------------------------

    async def detect_communities(
        self, *, resolution: float = 1.0
    ) -> dict[int, list[str]]:
        """Run Louvain community detection and persist results.

        Uses an undirected projection of the graph. Results are stored
        in the DB and loaded into NetworkX node data.

        Args:
            resolution: Louvain resolution parameter. Higher values
                produce more communities.

        Returns:
            Mapping of community_id → list of neuron IDs.
        """
        if self._graph.number_of_nodes() == 0:
            return {}

        undirected = self._graph.to_undirected()
        communities = nx.community.louvain_communities(
            undirected, resolution=resolution, seed=42,
        )

        result: dict[int, list[str]] = {}
        mapping: dict[str, int] = {}
        for cid, members in enumerate(communities):
            result[cid] = sorted(members)
            for nid in members:
                mapping[nid] = cid

        # Persist to DB and update in-memory graph
        await self._db.batch_update_community_ids(mapping)
        for nid, cid in mapping.items():
            if nid in self._graph:
                self._graph.nodes[nid]["community_id"] = cid

        return result

    def get_community(self, neuron_id: str) -> int | None:
        """Get the community ID for a neuron (from in-memory graph)."""
        if neuron_id not in self._graph:
            return None
        return self._graph.nodes[neuron_id].get("community_id")

    def community_map(self) -> dict[str, int]:
        """Return a mapping of neuron_id → community_id for all assigned neurons."""
        result: dict[str, int] = {}
        for nid in self._graph.nodes:
            cid = self._graph.nodes[nid].get("community_id")
            if cid is not None:
                result[nid] = cid
        return result

    async def generate_community_summaries(self) -> list[dict]:
        """Generate summary neurons for each community.

        For each community, creates a ``community_summary`` neuron with
        member titles and domain info, linked to members via ``summarizes``
        synapses. Replaces existing summaries on re-run.

        Returns:
            List of dicts with summary neuron info per community.
        """
        self._guard_readonly()

        # Build community → members mapping (exclude _meta)
        communities: dict[int, list[str]] = {}
        for nid in self._graph.nodes:
            data = self._graph.nodes[nid]
            if data.get("domain") == "_meta":
                continue
            if data.get("type") == "community_summary":
                continue
            cid = data.get("community_id")
            if cid is not None:
                communities.setdefault(cid, []).append(nid)

        if not communities:
            return []

        # Remove old community_summary neurons. These are internal
        # infrastructure rebuilt from scratch each run with deterministic
        # IDs (cs-NNNN) — they are NOT user-visible knowledge and must
        # not be soft-retired, or subsequent regeneration would collide
        # on primary key. Bypass remove_neuron and hard-delete directly.
        old_summaries = [
            nid for nid in list(self._graph.nodes)
            if self._graph.nodes[nid].get("type") == "community_summary"
        ]
        for nid in old_summaries:
            await self._db.delete_neuron(nid)
            if nid in self._graph:
                self._graph.remove_node(nid)

        results: list[dict] = []
        for cid, members in sorted(communities.items()):
            if len(members) < 2:
                continue

            # Gather member info
            titles: list[str] = []
            domains: set[str] = set()
            for nid in members:
                n = await self._db.get_neuron(nid)
                if n:
                    title = n.content.split("\n")[0].lstrip("# ").strip()
                    if title:
                        titles.append(title)
                    if n.domain:
                        domains.add(n.domain)

            # Build summary content
            domain_str = ", ".join(sorted(domains)) if domains else "mixed"
            topics_str = ", ".join(titles[:10])
            if len(titles) > 10:
                topics_str += f", ... (+{len(titles) - 10} more)"

            content = (
                f"# Community {cid}: {domain_str}\n\n"
                f"This cluster covers {len(members)} neurons.\n"
                f"Key topics: {topics_str}."
            )

            summary_id = f"cs-{cid:04d}"
            primary_domain = max(domains, key=lambda d: sum(
                1 for nid in members
                if self._graph.nodes.get(nid, {}).get("domain") == d
            )) if domains else None

            neuron = Neuron(
                id=summary_id,
                content=content,
                type="community_summary",
                domain=primary_domain,
            )
            await self._db.insert_neuron(neuron)
            self._graph.add_node(neuron.id, type="community_summary", domain=primary_domain)
            if self._embedder:
                await self._embed_neuron(neuron)

            # Link to members
            for member_id in members:
                await self.add_synapse(
                    summary_id, member_id, SynapseType.SUMMARIZES,
                    confidence=SynapseConfidence.INFERRED,
                    confidence_score=1.0,
                )

            results.append({
                "id": summary_id,
                "community_id": cid,
                "member_count": len(members),
                "domains": sorted(domains),
                "topics": titles[:10],
            })

        return results

    # -- Consolidation (sleep) -----------------------------------------------

    def _graph_state_hash(self) -> str:
        """Compute a SHA256 hash of the current graph state for plan validation."""
        parts: list[str] = []
        for nid in sorted(self._graph.nodes):
            parts.append(nid)
        for u, v, data in sorted(self._graph.edges(data=True)):
            parts.append(f"{u}->{v}:{data.get('weight', 0):.4f}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    async def consolidate(
        self,
        *,
        decay_factor: float = 0.8,
        weight_floor: float | None = None,
        similarity_threshold: float = 0.85,
        domain: str | None = None,
    ) -> dict:
        """Generate a consolidation plan (dry-run).

        Biologically-inspired 4-phase consolidation:
        1. SWS (Replay): Discover latent synapses via embedding similarity
        2. SHY (Downscaling): Decay weights, identify prunable synapses
        3. REM (Interference): Detect near-duplicate neurons
        4. Triage: Flag low-value neurons as forget candidates

        Args:
            decay_factor: Multiply all synapse weights by this (SHY phase).
            weight_floor: Prune synapses below this. Defaults to plasticity.weight_floor.
            similarity_threshold: Cosine similarity threshold for latent synapses / duplicates.
            domain: Optional domain filter (TMR-inspired targeted consolidation).

        Returns:
            A consolidation plan dict with actions and state_hash.
        """
        if weight_floor is None:
            weight_floor = self.plasticity.weight_floor

        state_hash = self._graph_state_hash()

        # Filter neurons by domain if requested
        target_nids: set[str] = set()
        for nid in self._graph.nodes:
            data = self._graph.nodes[nid]
            if data.get("domain") == "_meta" or data.get("type") == "community_summary":
                continue
            if domain and data.get("domain") != domain:
                continue
            target_nids.add(nid)

        # Phase 1: SWS — Discover latent synapses
        latent_synapses: list[dict] = []
        if self._embedder and self._db.has_embeddings:
            existing_edges: set[tuple[str, str]] = set()
            for u, v in self._graph.edges():
                existing_edges.add((u, v))
                existing_edges.add((v, u))

            checked: set[tuple[str, str]] = set()
            for nid in target_nids:
                blob = await self._db.get_embedding(nid)
                if blob is None:
                    continue
                neighbors = await self._db.knn_search(blob, limit=10)
                for neighbor_id, distance in neighbors:
                    if neighbor_id == nid or neighbor_id not in target_nids:
                        continue
                    pair = tuple(sorted([nid, neighbor_id]))
                    if pair in checked or pair in existing_edges:
                        continue
                    checked.add(pair)
                    # Convert L2 distance to cosine similarity approximation
                    sim = max(0.0, 1.0 - distance / 2.0)
                    if sim >= similarity_threshold:
                        latent_synapses.append({
                            "pre": pair[0],
                            "post": pair[1],
                            "similarity": round(sim, 3),
                            "action": "add_synapse",
                            "type": "relates_to",
                        })

        # Phase 2: SHY — Weight decay + prune
        decayed_synapses: list[dict] = []
        prunable_synapses: list[dict] = []
        all_synapses = await self._db.get_all_synapses()
        for s in all_synapses:
            if domain:
                pre_domain = self._graph.nodes.get(s.pre, {}).get("domain")
                post_domain = self._graph.nodes.get(s.post, {}).get("domain")
                if pre_domain != domain and post_domain != domain:
                    continue
            new_weight = s.weight * decay_factor
            if new_weight < weight_floor:
                prunable_synapses.append({
                    "pre": s.pre,
                    "post": s.post,
                    "type": s.type.value,
                    "old_weight": round(s.weight, 4),
                    "new_weight": round(new_weight, 4),
                    "action": "remove_synapse",
                })
            else:
                decayed_synapses.append({
                    "pre": s.pre,
                    "post": s.post,
                    "type": s.type.value,
                    "old_weight": round(s.weight, 4),
                    "new_weight": round(new_weight, 4),
                    "action": "set_weight",
                })

        # Identify neurons that would become isolated after pruning
        pruned_edges = {(p["pre"], p["post"]) for p in prunable_synapses}
        removable_neurons: list[dict] = []
        for nid in target_nids:
            remaining_edges = 0
            for neighbor in self._graph.predecessors(nid):
                if (neighbor, nid) not in pruned_edges:
                    remaining_edges += 1
            for neighbor in self._graph.successors(nid):
                if (nid, neighbor) not in pruned_edges:
                    remaining_edges += 1
            if remaining_edges == 0 and self._graph.degree(nid) > 0:
                # Stage 2 (§4.3): "activity" is read from the substrate's
                # own spike log, not the tutor's FSRS card state.
                spikes = await self._db.get_spikes_for(nid, limit=1)
                if not spikes:
                    removable_neurons.append({
                        "id": nid,
                        "action": "remove_neuron",
                        "reason": "isolated_after_prune_no_activity",
                    })

        # Phase 3: REM — Near-duplicate detection
        near_duplicates: list[dict] = []
        if self._embedder and self._db.has_embeddings:
            dup_checked: set[tuple[str, str]] = set()
            for nid in target_nids:
                blob = await self._db.get_embedding(nid)
                if blob is None:
                    continue
                neighbors = await self._db.knn_search(blob, limit=5)
                for neighbor_id, distance in neighbors:
                    if neighbor_id == nid or neighbor_id not in target_nids:
                        continue
                    pair = tuple(sorted([nid, neighbor_id]))
                    if pair in dup_checked:
                        continue
                    dup_checked.add(pair)
                    sim = max(0.0, 1.0 - distance / 2.0)
                    if sim >= 0.95:
                        near_duplicates.append({
                            "neuron_a": pair[0],
                            "neuron_b": pair[1],
                            "similarity": round(sim, 3),
                            "action": "propose_merge",
                        })
                    elif sim >= 0.85:
                        # High similarity but not duplicate — confusable pair
                        if (pair[0], pair[1]) not in existing_edges:
                            near_duplicates.append({
                                "neuron_a": pair[0],
                                "neuron_b": pair[1],
                                "similarity": round(sim, 3),
                                "action": "propose_contrast",
                            })

        # Phase 4: Triage — forget candidates.
        # Stage 2 (§4.3): the substrate triages on its own spike-table
        # signal (review count + grade distribution), not the tutor's
        # FSRS stability. A neuron that is old, peripheral, and never
        # successfully recalled is a forget candidate. This is a coarser
        # signal than FSRS stability — directionally correct, not exact.
        forget_candidates: list[dict] = []
        centrality = nx.degree_centrality(self._graph) if self._graph.number_of_nodes() > 1 else {}
        now = datetime.now(timezone.utc)
        for nid in target_nids:
            cent = centrality.get(nid, 0.0)
            n = await self._db.get_neuron(nid)
            if n is None:
                continue
            age_days = (now - n.created_at).days
            if cent >= 0.1 or age_days <= 30:
                continue
            spikes = await self._db.get_spikes_for(nid, limit=100_000)
            success = sum(1 for s in spikes if int(s.grade) >= int(Grade.FIRE))
            if success == 0:
                forget_candidates.append({
                    "id": nid,
                    "review_count": len(spikes),
                    "successful_reviews": success,
                    "centrality": round(cent, 3),
                    "age_days": age_days,
                    "action": "flag_forget",
                })

        return {
            "state_hash": state_hash,
            "domain": domain,
            "params": {
                "decay_factor": decay_factor,
                "weight_floor": weight_floor,
                "similarity_threshold": similarity_threshold,
            },
            "sws": {"latent_synapses": latent_synapses},
            "shy": {
                "decayed": decayed_synapses,
                "prunable": prunable_synapses,
                "removable_neurons": removable_neurons,
            },
            "rem": {"near_duplicates": near_duplicates},
            "triage": {"forget_candidates": forget_candidates},
            "summary": {
                "latent_synapses": len(latent_synapses),
                "weight_decays": len(decayed_synapses),
                "prunable_synapses": len(prunable_synapses),
                "removable_neurons": len(removable_neurons),
                "near_duplicates": len(near_duplicates),
                "forget_candidates": len(forget_candidates),
            },
        }

    async def apply_consolidation(self, plan: dict) -> dict:
        """Apply a consolidation plan. Validates state hash first.

        Args:
            plan: A plan dict from consolidate().

        Returns:
            Summary of applied actions.

        Raises:
            ValueError: If the current graph state doesn't match the plan's hash.
        """
        self._guard_readonly()
        current_hash = self._graph_state_hash()
        if current_hash != plan["state_hash"]:
            raise ValueError(
                f"Brain state has changed since plan was generated. "
                f"Plan hash: {plan['state_hash']}, current: {current_hash}. "
                f"Re-run 'spkt consolidate' to generate a fresh plan."
            )

        applied = {
            "synapses_added": 0,
            "weights_decayed": 0,
            "synapses_pruned": 0,
            "neurons_removed": 0,
        }

        # Phase 1: Add latent synapses
        for ls in plan["sws"]["latent_synapses"]:
            try:
                await self.add_synapse(
                    ls["pre"], ls["post"],
                    SynapseType(ls["type"]),
                    confidence=SynapseConfidence.INFERRED,
                    confidence_score=ls["similarity"],
                )
                applied["synapses_added"] += 1
            except (ValueError, KeyError):
                pass  # Skip if neurons no longer exist

        # Phase 2: Decay weights + prune
        for ds in plan["shy"]["decayed"]:
            try:
                await self.set_synapse_weight(
                    ds["pre"], ds["post"], SynapseType(ds["type"]), ds["new_weight"]
                )
                applied["weights_decayed"] += 1
            except (ValueError, KeyError):
                pass

        for ps in plan["shy"]["prunable"]:
            try:
                await self.remove_synapse(ps["pre"], ps["post"], SynapseType(ps["type"]))
                applied["synapses_pruned"] += 1
            except (ValueError, KeyError):
                pass

        for rn in plan["shy"]["removable_neurons"]:
            try:
                await self.remove_neuron(rn["id"])
                applied["neurons_removed"] += 1
            except (ValueError, KeyError):
                pass

        return applied

    # -- Stats --------------------------------------------------------------

    async def stats(self) -> dict[str, object]:
        """Overview statistics."""
        neuron_count = await self._db.count_neurons()
        total_count = await self._db.count_neurons(include_retired=True)
        cmap = self.community_map()
        return {
            "neurons": neuron_count,
            "neurons_retired": total_count - neuron_count,
            "synapses": self._graph.number_of_edges(),
            "graph_density": nx.density(self._graph) if neuron_count > 1 else 0.0,
            "communities": len(set(cmap.values())) if cmap else 0,
        }

    # -- Diagnostics ----------------------------------------------------------

    async def diagnose(
        self,
        *,
        weak_synapse_threshold: float = 0.2,
    ) -> dict:
        """Run read-only brain health diagnostics.

        Returns a structured dict with all health metrics:
        orphans, weak_synapses, domain_balance, community_cohesion,
        bridge_gaps, dangling_prerequisites, source_freshness,
        surprise_bridges.
        """
        g = self._graph

        # -- Orphan neurons: degree == 0 -----------------------------------
        orphans = [nid for nid in g.nodes if g.degree(nid) == 0]

        # -- Weak synapses -------------------------------------------------
        weak_synapses = []
        for u, v, data in g.edges(data=True):
            w = data.get("weight", 0.5)
            if w < weak_synapse_threshold:
                weak_synapses.append({
                    "pre": u, "post": v,
                    "type": data.get("type", "relates_to"),
                    "weight": w,
                })

        # -- Domain balance ------------------------------------------------
        domain_counts: dict[str, int] = {}
        for nid in g.nodes:
            d = g.nodes[nid].get("domain") or "(none)"
            domain_counts[d] = domain_counts.get(d, 0) + 1
        total_neurons = g.number_of_nodes()
        domain_balance = {
            "counts": domain_counts,
            "total": total_neurons,
        }
        if total_neurons > 0 and len(domain_counts) > 1:
            max_c = max(domain_counts.values())
            min_c = min(domain_counts.values())
            domain_balance["imbalance_ratio"] = max_c / min_c if min_c > 0 else float("inf")
        else:
            domain_balance["imbalance_ratio"] = 1.0

        # -- Community cohesion --------------------------------------------
        cmap = self.community_map()
        community_groups: dict[int, set[str]] = {}
        for nid, cid in cmap.items():
            community_groups.setdefault(cid, set()).add(nid)

        intra_edges = 0
        inter_edges = 0
        for u, v in g.edges:
            cu = cmap.get(u)
            cv = cmap.get(v)
            if cu is not None and cv is not None:
                if cu == cv:
                    intra_edges += 1
                else:
                    inter_edges += 1

        total_community_edges = intra_edges + inter_edges
        community_cohesion = {
            "communities": len(community_groups),
            "intra_edges": intra_edges,
            "inter_edges": inter_edges,
            "cohesion_ratio": (
                intra_edges / total_community_edges
                if total_community_edges > 0 else 0.0
            ),
        }

        # -- Bridge gaps: communities with no cross-community edges --------
        communities_with_bridges: set[int] = set()
        for u, v in g.edges:
            cu = cmap.get(u)
            cv = cmap.get(v)
            if cu is not None and cv is not None and cu != cv:
                communities_with_bridges.add(cu)
                communities_with_bridges.add(cv)
        isolated_communities = [
            cid for cid in community_groups
            if cid not in communities_with_bridges
               and len(community_groups[cid]) > 1
        ]

        # -- Dangling prerequisites ----------------------------------------
        # Stage 2 (§4.3): a prerequisite's health is read from the
        # substrate's own spike log, not the tutor's FSRS card. A
        # prerequisite that was never practised, or never successfully
        # recalled, is a dangling prerequisite.
        dangling_prereqs = []
        for u, v, data in g.edges(data=True):
            if data.get("type") == "requires":
                # u requires v — check whether v is practised/recalled.
                spikes = await self._db.get_spikes_for(v, limit=100_000)
                if not spikes:
                    dangling_prereqs.append({
                        "neuron": u, "requires": v,
                        "reason": "never_reviewed",
                    })
                else:
                    success = sum(
                        1 for s in spikes if int(s.grade) >= int(Grade.FIRE)
                    )
                    if success == 0:
                        dangling_prereqs.append({
                            "neuron": u, "requires": v,
                            "reason": "weak",
                            "review_count": len(spikes),
                        })

        # -- Source freshness ----------------------------------------------
        sources = await self.list_sources(limit=100_000)
        source_stats = {
            "total": len(sources),
            "url_sources": 0,
            "unreachable": 0,
            "never_fetched": 0,
        }
        for s in sources:
            if s.url and s.url.startswith(("http://", "https://")):
                source_stats["url_sources"] += 1
                if s.status == "unreachable":
                    source_stats["unreachable"] += 1
                if s.fetched_at is None:
                    source_stats["never_fetched"] += 1

        # -- Surprise bridges: cross-community edges scored by rarity ------
        surprise_bridges = []
        if community_groups and inter_edges > 0:
            # Score = 1 / min(size_a, size_b) — smaller communities are more surprising
            for u, v, data in g.edges(data=True):
                cu = cmap.get(u)
                cv = cmap.get(v)
                if cu is not None and cv is not None and cu != cv:
                    size_a = len(community_groups[cu])
                    size_b = len(community_groups[cv])
                    surprise = 1.0 / min(size_a, size_b)
                    surprise_bridges.append({
                        "pre": u, "post": v,
                        "type": data.get("type", "relates_to"),
                        "communities": [cu, cv],
                        "surprise_score": round(surprise, 4),
                    })
            surprise_bridges.sort(key=lambda x: x["surprise_score"], reverse=True)
            surprise_bridges = surprise_bridges[:20]  # Top 20

        return {
            "orphans": orphans,
            "weak_synapses": weak_synapses,
            "domain_balance": domain_balance,
            "community_cohesion": community_cohesion,
            "isolated_communities": isolated_communities,
            "dangling_prerequisites": dangling_prereqs,
            "source_freshness": source_stats,
            "surprise_bridges": surprise_bridges,
        }

    async def domain_audit(self) -> dict:
        """Analyze domain ↔ community alignment and suggest actions.

        Compares the user-assigned domain labels against the graph's
        natural community structure (Louvain) to find mismatches:

        - **split**: a domain spans multiple communities → suggest sub-domains
        - **merge**: multiple domains converge in one community → suggest merging
        - **rename**: keyword extraction hints at a better name

        Returns a dict with domain_map, community_map, suggestions[].
        """
        from collections import Counter
        import math

        g = self._graph
        cmap = self.community_map()

        # -- Build mappings ------------------------------------------------
        # domain → {community_id: [neuron_ids]}
        domain_to_communities: dict[str, dict[int, list[str]]] = {}
        # community → {domain: [neuron_ids]}
        community_to_domains: dict[int, dict[str, list[str]]] = {}

        for nid in g.nodes:
            data = g.nodes[nid]
            dom = data.get("domain") or "(none)"
            if dom == "_meta":
                continue
            if data.get("type") == "community_summary":
                continue
            cid = cmap.get(nid)
            if cid is None:
                continue

            domain_to_communities.setdefault(dom, {}).setdefault(cid, []).append(nid)
            community_to_domains.setdefault(cid, {}).setdefault(dom, []).append(nid)

        # -- Pre-fetch neuron content for keyword extraction ----------------
        all_node_ids = list(g.nodes)
        content_map: dict[str, str] = {}
        for nid in all_node_ids:
            n = await self.get_neuron(nid)
            if n is not None:
                content_map[nid] = n.content

        # -- TF-IDF keyword extraction per community ----------------------
        def _extract_keywords(
            neuron_ids: list[str],
            content_map: dict[str, str],
            top_n: int = 5,
        ) -> list[str]:
            """Simple TF-IDF on neuron titles (first line of content)."""
            stop = {
                "the", "a", "an", "is", "are", "was", "were", "be", "been",
                "to", "of", "in", "for", "on", "with", "at", "by", "from",
                "and", "or", "not", "no", "but", "if", "so", "as", "it",
                "this", "that", "its", "than", "has", "have", "had", "do",
                "does", "did", "will", "would", "can", "could", "may",
                "shall", "should", "must", "need", "about", "into", "over",
                "such", "also", "each", "which", "their", "these", "those",
                "de", "la", "le", "les", "un", "une", "des", "du", "et",
                "en", "est", "que", "qui", "dans", "pour", "sur", "avec",
                "の", "は", "が", "を", "に", "で", "と", "も", "から",
            }

            # Term freq per document (neuron)
            doc_tfs: list[Counter] = []
            all_terms: Counter = Counter()
            for nid in neuron_ids:
                content = content_map.get(nid, "")
                title = content.split("\n")[0].strip("# ").strip() if content else ""
                words = [
                    w.lower().strip(".,;:!?()[]{}\"'`")
                    for w in title.split()
                    if len(w) > 1
                ]
                words = [w for w in words if w and w not in stop]
                tf = Counter(words)
                doc_tfs.append(tf)
                all_terms.update(set(words))  # DF: count each term once per doc

            n_docs = len(doc_tfs)
            if n_docs == 0:
                return []

            # TF-IDF score per term
            scores: Counter = Counter()
            for tf in doc_tfs:
                for term, count in tf.items():
                    df = all_terms[term]
                    idf = math.log(n_docs / df) if df > 0 else 0
                    scores[term] += count * idf

            return [term for term, _ in scores.most_common(top_n)]

        community_keywords: dict[int, list[str]] = {}
        for cid, dom_map in community_to_domains.items():
            all_nids = [nid for nids in dom_map.values() for nid in nids]
            community_keywords[cid] = _extract_keywords(all_nids, content_map)

        # -- Generate suggestions ------------------------------------------
        suggestions: list[dict] = []

        # Split: domain spans 2+ communities with significant presence in each
        for dom, comm_map in domain_to_communities.items():
            if len(comm_map) < 2:
                continue
            total = sum(len(nids) for nids in comm_map.values())
            # Only suggest split if at least 2 communities have ≥20% of the domain
            significant = {
                cid: nids for cid, nids in comm_map.items()
                if len(nids) / total >= 0.2
            }
            if len(significant) >= 2:
                communities_info = []
                for cid, nids in significant.items():
                    communities_info.append({
                        "community": cid,
                        "count": len(nids),
                        "keywords": community_keywords.get(cid, []),
                    })
                suggestions.append({
                    "action": "split",
                    "domain": dom,
                    "total_neurons": total,
                    "communities": communities_info,
                })

        # Merge: multiple domains in same community
        for cid, dom_map in community_to_domains.items():
            if len(dom_map) < 2:
                continue
            total_in_community = sum(len(nids) for nids in dom_map.values())
            # Only suggest merge if all domains in this community are small enough
            # to be considered fragments of a single topic
            domains_here = []
            for dom, nids in dom_map.items():
                pct = len(nids) / total_in_community
                domains_here.append({
                    "domain": dom,
                    "count": len(nids),
                    "pct_of_community": round(pct, 2),
                })
            # Suggest merge if no single domain dominates (>80%)
            max_pct = max(d["pct_of_community"] for d in domains_here)
            if max_pct <= 0.8:
                suggestions.append({
                    "action": "merge",
                    "community": cid,
                    "keywords": community_keywords.get(cid, []),
                    "domains": domains_here,
                })

        # -- Domain stats summary ------------------------------------------
        domain_summary = []
        for dom, comm_map in sorted(domain_to_communities.items()):
            total = sum(len(nids) for nids in comm_map.values())
            communities = sorted(comm_map.keys())
            domain_summary.append({
                "domain": dom,
                "neuron_count": total,
                "communities": communities,
                "spread": len(communities),
            })

        return {
            "domains": domain_summary,
            "community_keywords": {
                str(cid): kws for cid, kws in community_keywords.items()
            },
            "suggestions": suggestions,
        }
