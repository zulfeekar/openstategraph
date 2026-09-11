"""The mount families — another workflow run as one isolated step.

`CLAUDE.md`'s lexicon is the whole of this module's subject. A **package** is
the reusable definition; a **mount** is one instance of it, carrying its own
`data.overrides`; and what the mount builder compiles is *task in, answer out*
— never inline expansion, never shared state.

Two facts live here and nowhere else, and both have a census pointed at this
file by name:

- **The child inherits the parent's identity and overrides `workflow_slug`
  alone.** That is the single deliberate partial `configurable` literal in
  this codebase; "completing" it to four keys would sever a child run from the
  person it is for.
- **`GraphRecursionError` may be named here**, because a mount is the boundary
  where a child's exhaustion becomes a parent's recorded step rather than a
  vendor exception escaping to a door.

`compile/nodes/__init__.py` carries the argument for the package and the
binding mechanism.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openstategraph.compile.state import RunState
from langchain_core.runnables.config import ensure_config
from langgraph.errors import GraphRecursionError

from openstategraph.compile.context import _text, nested_record
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.mount_overrides import apply_mount_overrides
from openstategraph.compile.run_context import (
    mount_run_context,
    run_context,
    unsuppliable_context_keys,
)
from openstategraph.compile.runtime_services import PackageAssets, RuntimeServices
from openstategraph.compile.state import _upstream_text, published_answer
from openstategraph.errors import StepBudgetExhausted
from openstategraph.step_budget import (
    DEFAULT_STEP_BUDGET,
    mount_step_budget,
    record_overruled_mount,
    workflow_step_budget,
)
from openstategraph.compile.workflow_compiler import CompiledPlan

if TYPE_CHECKING:
    # The class this function is a method of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # it. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


@dataclass
class _ResolvedChild:
    """One mounted package, as far as compiling it is the same at every site.

    Everything here is a function of `(slug, overrides, persistence)` **and of
    the runtime doing the resolving** — which is what makes those three enough
    for a key. A parent runtime fixes the rest of what `_subgraph` reads: the
    services the child inherits, the ancestry that refuses a cycle, and the
    `settings` a context gap is measured against. Two sibling mounts of one
    package share all of it; two mounts under different parents share none of
    it, which is why the memo hangs off the runtime rather than off the module.

    What is deliberately **not** here is everything keyed by the mount's own
    node id — the override confirmations, the unenforced-outcome sentence, the
    `MountedGraph` record and the name fold. Those are replayed per site, so a
    memo that collapses two compiles never collapses two cards.
    """

    #: The child document with this mount's overrides already applied.
    document: dict[str, Any]
    #: What `apply_mount_overrides` could not do, and what it did.
    override_warnings: tuple[str, ...]
    applied_overrides: tuple[tuple[str, str], ...]
    #: Keys the child asks its callers for that this document cannot supply.
    unsuppliable: tuple[Any, ...]
    #: The child's own capabilities, and whether it brought them itself.
    assets: Any
    owns_its_assets: bool
    #: The child's runtime, and the graph it compiled.
    runtime: Any
    graph: Any
    #: Whether any grader in the child routes `revise`. `None` until somebody
    #: asks, because asking costs a `plan()` of the child and only a mount that
    #: writes an `outcome` has a reason to — the short-circuit this used to get
    #: from `and` in the caller. Once asked it is answered for every sibling
    #: mount too, which is the second `plan()` per document the ticket names.
    _closes_a_loop: bool | None = None

    def closes_a_loop(self, runtime: Any) -> bool:
        """Whether this child can enforce an outcome a mount's card promises."""
        if self._closes_a_loop is None:
            self._closes_a_loop = runtime._closes_a_loop_impl(self.document)
        return self._closes_a_loop


def _child_key(slug: str, overrides: Any, persistence: str) -> tuple[str, str, str]:
    """What actually determines the built child, canonically.

    Not the slug alone. `CLAUDE.md` fixes an *instance* as one mount carrying
    its own `data.overrides`, so a slug-keyed memo would hand one instance
    another's prompts — the shape of `launch-readiness/182` and of
    `the-boundary-nobody-checked/05`, both found in one week. `persistence` is
    in the key because it is what the child is compiled *with*
    (`mount_checkpointer`), and the overrides are serialised with sorted keys
    so two spellings of one configuration are one key. A mount whose overrides
    will not serialise falls to its own key and is compiled on its own, which
    is what this function did for every mount before it existed.
    """
    try:
        canonical = json.dumps(overrides, sort_keys=True, default=str)
    except Exception:
        canonical = repr(overrides)
    return (slug, canonical, persistence)


def _resolve_child(
    self: "NodeRuntime", slug: str, overrides: Any, persistence: str
) -> "_ResolvedChild | None":
    """Compile the mounted package — once per `(slug, overrides, persistence)`.

    **A memo, not a cache, and the difference is its lifetime.**
    `docs/decisions/per-request-compile-cost.md` declined a compiled-graph
    cache after measuring the setup path at 27 ms warm, and its recorded
    objection was never the architecture: it was an invalidation surface of
    nine items — the document, `tools/*.py`, `functions/`, `middlewares/`,
    `skills/*.md`, `knowledge/`, a capability refresh, every mounted child
    transitively, and provider state — against a repository whose named
    recurring defect is *two situations rendering identically*.

    This memo answers that list by not having one. It lives on the runtime
    that is doing the compiling and dies with it, so nothing it holds can go
    stale: a capability refresh, a saved document and an edited tool all
    produce a new runtime, and a new runtime has an empty memo. There is no
    lock either, for the same reason — a runtime is not shared between
    requests, so there is nothing to serialise (`docs/decisions/async-seam.md`
    asks for a concurrency proof, and the proof is that nothing is concurrent).

    What it buys is the whole of `the-cost-of-one-more` 02: the mount graph is
    a DAG, so resolving it per *site* cost `2^(d+1) - 1` compiles for `d`
    levels each mounting the next twice — 255 for eight packages on disk.
    Resolving it per distinct instance costs one compile per package.
    """
    # The one family that builds a *runtime*, not just a step: a mount
    # compiles its child with a `NodeRuntime` of the child's own assets. So
    # this is the single import in `compile/nodes/` that points back at
    # `node_runtime`, and it is local for the reason 30f17dc moved the leaves
    # out first — at module scope it would be a real cycle, because
    # `NodeRuntime`'s class body imports this module to bind `_subgraph`.
    from openstategraph.compile.node_runtime import NodeRuntime
    from openstategraph.compile.mount_persistence import mount_checkpointer
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    key = _child_key(slug, overrides, persistence)
    if key in self._mount_memo:
        return self._mount_memo[key]  # type: ignore[no-any-return]

    resolved: "_ResolvedChild | None" = None
    try:
        child_document = self.services.document_loader(slug)  # type: ignore[misc]
    except Exception:
        child_document = None
    if child_document is not None:
        # Per-mount overrides (docs/decisions/mount-overrides.md):
        # this mount's own configuration, merged onto a copy of the
        # shared package before the child compiles.
        applied_overrides: list[tuple[str, str]] = []
        child_document, mount_warnings = apply_mount_overrides(
            child_document, overrides, applied=applied_overrides
        )
        child_assets = PackageAssets(
            tools=self.services.tools,
            functions=self.services.functions,
            skills_context=self.services.skills_context,
            workflow_middleware=self.services.workflow_middleware,
            knowledge_dir=self.services.knowledge_package_dir,
        )
        child_owns_its_assets = False
        if self.services.package_loader is not None:
            try:
                child_assets = self.services.package_loader(slug)
                child_owns_its_assets = True
            except Exception:
                pass  # the parent assets remain the honest fallback
        child_runtime = NodeRuntime(
            services=RuntimeServices(
                model=self.services.model,
                tools={**self.services.tools, **child_assets.tools},
                functions={**self.services.functions, **child_assets.functions},
                document_loader=self.services.document_loader,
                package_loader=self.services.package_loader,
                memory_store=self.services.memory_store,
                skills_context=child_assets.skills_context,
                workflow_middleware=child_assets.workflow_middleware or {},
                # The child's OWN knowledge, never the parent's —
                # the same isolation as skills (ticket 67's lesson).
                knowledge_package_dir=child_assets.knowledge_dir,
                # ...and the child's OWN skills to disclose. Inheriting
                # the parent's directory here would hand a routed child
                # a skill list naming files it does not carry.
                skills_package_dir=child_assets.skills_dir,
                max_attempts=self.services.max_attempts,
                # Deliberately NOT inherited. A child subgraph's node
                # ids do not exist in the document open on the canvas,
                # so any `attachTo` it produced would name a node the
                # editor cannot find — an unappliable suggestion is
                # worse than none, since it reads as an offer.
                advisor_catalog="",
            ),
            _ancestry=(*self._ancestry, slug),
        )
        child_factory = child_runtime.factory(child_document)
        child_graph = WorkflowCompiler().build(
            child_document,
            RunState,
            child_factory,
            # The tri-state, and the first time this boundary has said
            # anything at all about it. `None` is the argument it
            # always passed by omission, so a mount that did not opt in
            # compiles exactly as it did before
            # (`compile/mount_persistence.py` carries the rest).
            checkpointer=mount_checkpointer(persistence),
            store=self.services.memory_store,
            # The child's own sink, which this mount absorbs below under the
            # package slug — so a compile-time finding about a node inside a
            # mounted workflow is said once, carrying the path it came from,
            # exactly as every other absorbed finding is
            # (`langchain-drift-watch` 01).
            diagnostics=child_runtime.diagnostics,
            # A child of a mount is **sealed**: a graph compiled with no
            # `context_schema` inherits its caller's run context whole
            # and no argument to `invoke` can take that away, so a child
            # that declares nothing gets an empty schema rather than
            # none (`organisms-first-class` 76).
            mounted=True,
        )
        resolved = _ResolvedChild(
            document=child_document,
            override_warnings=tuple(mount_warnings),
            applied_overrides=tuple(applied_overrides),
            # Taken against the effective (post-override) child, for the
            # reason the sizing and context documents are: an override that
            # rewrote a declaration would otherwise be narrowed against a
            # document the child never compiled from.
            unsuppliable=tuple(
                unsuppliable_context_keys(child_document, {"settings": self._settings})
            ),
            assets=child_assets,
            owns_its_assets=child_owns_its_assets,
            runtime=child_runtime,
            graph=child_graph,
        )

    self._mount_memo[key] = resolved
    return resolved


def _subgraph(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Another workflow, compiled and invoked as one node of this graph.

    This is what makes "workflow composition = subgraphs" real (ticket
    34). The child is compiled **at build time** — so a workflow that
    (transitively) includes itself is refused with a readable error
    instead of recursing at run time — and invoked with an explicit
    state mapping: the parent's upstream text becomes the child's
    question, and only the child's final answer flows back. The child
    never sees the parent's other state keys, mirroring the
    subagent-isolation rule: a subgraph receives a task and reports a
    result.
    """
    from openstategraph.compile.composition import MountedGraph

    from openstategraph.compile.mount_persistence import (
        STATELESS,
        carries_the_parents_dialogue,
        mount_persistence,
    )
    from openstategraph.compile.workflow_compiler import safe_name

    data = node.get("data") or {}
    slug = _text(data, "workflow").strip()
    # How long this child's own state lives (`organisms-first-class` 30).
    # Absent — every document saved before that ticket — is
    # `per-invocation`, which is what this boundary always did.
    persistence = mount_persistence(data.get("persistence"))
    upstream = [src for src, dst in plan.edges if dst == node_id]
    # A subgraph fed by a grader's `pass` (or an approval's `approved`)
    # arrives over a *conditional* edge, which `plan.edges` does not
    # carry — same situation `_output` already handles. Without this, a
    # review subgraph placed after a grader would receive the original
    # question instead of the candidate it is supposed to review
    # (found while wiring ticket 43's code-workshop, not hypothetically).
    conditional_upstream = [
        src for src, dests in plan.conditional.items() if node_id in dests.values()
    ]

    if slug and slug in self._ancestry:
        chain = " -> ".join((*self._ancestry, slug))
        # *Mount*, not "subgraph". This sentence is quoted verbatim by the
        # editor (`mountCycleRule.ts`), by the palette's hover text and by
        # the gallery page, so it was the single widest leak of a LangGraph
        # name into user-facing copy — and it was not even true internally:
        # this compiler emits no LangGraph subgraph, a mount is a closure
        # over the child's `invoke()` (consistency-sweep ticket 10).
        raise ValueError(
            f"Workflow {slug!r} mounts itself ({chain}); "
            "a mount cycle can never terminate"
        )

    child_graph = None
    #: The document the child will actually be compiled from, kept only
    #: so the closure can ask what size it saved for itself
    #: (`organisms-first-class` 61). `None` when there is no child at all,
    #: which `mount_step_budget` reads as "saved nothing" — the
    #: overwhelming majority, and byte-identical to before that ticket.
    child_sizing_document: dict[str, Any] | None = None
    #: The same document, read for what it declared its runs carry
    #: (`organisms-first-class` 76). `None` when there is no child at all.
    child_context_document: dict[str, Any] | None = None
    if slug and self.services.document_loader is not None:
        # **One compile per instance, not per site** (`the-cost-of-one-more`
        # 02). Everything a mount of this package with these overrides and
        # this persistence resolves to is the same at every site under this
        # runtime, so it is resolved once and replayed below. What is replayed
        # rather than shared is everything the mount's own node id names: two
        # sibling mounts are two cards, two `MountedGraph` records and two
        # sentences in the report, and a memo that quietly made them one would
        # be a worse defect than the exponent it removes.
        resolved = _resolve_child(self, slug, data.get("overrides"), persistence)
        if resolved is not None:
            child_document = resolved.document
            for warning in resolved.override_warnings:
                self.diagnostics.record(
                    Finding.OVERRIDE_PROBLEM, f"{slug or node_id}: {warning}"
                )
            # The confirmation `OVERRIDE_PROBLEM` never had a counterpart
            # for (`launch-readiness` 40): an override that DID reach its
            # target said nothing about which mount reached it. Recorded
            # here, on THIS document's own diagnostics, keyed by this
            # mount's own node id — not by `slug` — so two sibling mounts
            # of the same package (`same-package-twice`) produce two
            # distinct sentences rather than one `CompileDiagnostics.absorb`
            # would collapse by package identity. Folding upward through
            # nested mounts still names the whole path: because the
            # distinguishing node id is baked into THIS message's own
            # text, `absorb`'s `through=slug` prefix (this document's own
            # slug, as seen by whichever document mounts it) only adds a
            # level rather than erasing one — a grandparent's report reads
            # `Inside mounted workflow "<mid-slug>": ... "mount-inner" ->
            # "<leaf-slug>#shorten1.systemPrompt"`, the whole chain.
            #
            # Replayed from the memo rather than recorded inside it, and this
            # is the line that says why the memo is not keyed by slug: the
            # *pairs* are a property of the instance, the *sentence* is a
            # property of the site.
            for child_node_id, field in resolved.applied_overrides:
                self.diagnostics.record(
                    Finding.OVERRIDE_APPLIED,
                    f'"{node_id}" -> "{slug}#{child_node_id}.{field}"',
                )
            # Taken *after* the overrides above, so a mount that overrode
            # its way to a different size is sized against what it will
            # run rather than against the package as it sits on disk.
            child_sizing_document = child_document
            # And the same effective document, under the name the *other*
            # question asks it by: what this child declared its runs carry.
            # One object, two readers, and both must be the post-override
            # copy — an override that rewrote a declaration would otherwise
            # be narrowed against a document the child never compiled from.
            child_context_document = child_document
            # And the fact those two documents make together
            # (`organisms-first-class` 79). 76 narrowed what crosses a
            # mount — a key crosses only when both documents declare it —
            # which means a child requiring a key with no default that this
            # document does not name is a mount that raises before
            # `invoke`, on every run, for every input. Said here because
            # both documents are in hand; until now it was said only as the
            # run died at this node, a whole run late.
            #
            # Keyed by slug rather than by `node_id`: this document's
            # declaration is document-wide, so three mounts of one package
            # share one gap.
            for unsuppliable in resolved.unsuppliable:
                self.diagnostics.record(
                    Finding.UNSUPPLIABLE_CONTEXT, slug, unsuppliable
                )
            # A mount's card shows an outcome its child may have no way to
            # enforce. Keyed on *an outcome being written* rather than on
            # the node's type — since v3 there is one mount type, and what
            # makes a card a promise is the prose on it, not which card it
            # is (tickets 03 and 16). A mount with no outcome claims
            # nothing and is not warned about — which is why
            # `closes_a_loop` is asked lazily: the answer costs a `plan()`
            # of the child, and the `and` below is what used to save it.
            #
            # (That sentence began "# type: since v3…", which mypy read as
            # a PEP 484 type comment and rejected as invalid syntax. Do not
            # start a comment line with `type:`.)
            #
            # Asked of the *compiler's* plan rather than by re-scanning
            # edges here: `conditional` is where a grader's `revise`
            # destination becomes a fact, so this cannot drift from what
            # the graph actually does.
            if _text(data, "outcome").strip() and not resolved.closes_a_loop(self):
                self.diagnostics.record(Finding.UNENFORCED_OUTCOME, node_id, slug)
            if resolved.owns_its_assets:
                self._report_inherited_functions(slug, child_document, resolved.assets)
            child_runtime = resolved.runtime
            child_graph = resolved.graph

            # Inherited *upwards*, unlike everything else about a child
            # runtime, and deliberately: the child's frames ride the
            # PARENT's one SSE stream, so the parent's stream fold is the
            # only place that can withhold them.
            #
            # Taken after `build()`, not after `factory()`, and the
            # difference is a whole level of nesting. `factory()` populates
            # the set for the child's *own* document; a mount inside the
            # child is resolved during `build()`, so a grandchild's names
            # land on `child_runtime` only once that call has returned.
            # Reading the set before it — which this line used to do,
            # under a comment naming `factory()` as what populated it —
            # left ticket 25's leak open at exactly two levels down: for A
            # mounts B mounts C, C's router and grader names never reached
            # the fold, so C's raw branch name could still surface in a
            # customer's answer. The comment was the bug's best disguise,
            # since it described a true thing about the first level and
            # nothing about the rest.
            self.machinery_nodes |= child_runtime.machinery_nodes
            # And the same union for the other half of what a `token` frame's
            # text is (`every-workflow-green` 45). The reply on that ticket's
            # own recording streams from `model` inside `agent_sql` inside a
            # mounted `chinook-assistant`, judged by that child's `grader-sql`
            # — a node no surface above this one has heard of. Without the
            # union the draft is unmarked in exactly the composition where a
            # reader is least able to work it out.
            self.checked_nodes |= child_runtime.checked_nodes
            # Same direction and the same reason as `machinery_nodes`,
            # different question: which card of the CHILD's canvas a frame
            # from inside this mount is about. `GraphNames.absorb` owns
            # the two folding rules and why they differ; the timing is the
            # part that belongs here — taken after `build()`, not after
            # `factory()`, because a mount inside the child is resolved by
            # that build, so a grandchild's ids only exist on
            # `child_runtime` once it has run.
            self.names.absorb(child_runtime.names, through=node_id, slug=slug)
            # Third thing inherited upwards, and the last of them to be:
            # what the child's compile *noticed*. Until `workflow-gallery`
            # 75 the two lines above absorbed a child's names and its
            # machinery and left its findings where nobody reads them, so
            # a mounted package could report an unbindable tool, a stale
            # tool denial or an unwired grader into silence. Keyed by
            # `slug` rather than `node_id` — `CompileDiagnostics.absorb`
            # carries why, and it is the difference between one sentence
            # and three for a package mounted three times.
            #
            # After `build()` for the same reason as the two above: a
            # mount inside the child records on `child_runtime` only once
            # that call has returned.
            self.diagnostics.absorb(child_runtime.diagnostics, through=slug)
            # Fourth thing inherited upwards, and the narrowest: whether
            # anything below this mount waits for a person. Unioned so a
            # grandparent sees a gate two levels down, and taken after
            # `build()` for the reason the three lines above are.
            self._holds_a_gate = self._holds_a_gate or child_runtime._holds_a_gate
            # Fifth, and the same shape: a parent of nothing but mounts still
            # reaches a model when a child does, so the run door above it must
            # be told (`osg-agent-experience/48`). Unioned here for the same
            # reason the gate is — the question is asked one level up from
            # where the answer lives.
            self._drives_a_model = self._drives_a_model or child_runtime._drives_a_model
            # And the one question only this line can answer: a mount that
            # keeps no record, over a workflow that pauses. It *does*
            # pause — the closure hands the interrupt to the parent's
            # checkpointer — but there is no child checkpoint to resume
            # from, so answering re-runs the child from its first step and
            # every side effect before the gate happens twice
            # (`organisms-first-class` 65; the measurement is in
            # `tests/test_a_stateless_mount_redoes_its_work.py`).
            if persistence == STATELESS and child_runtime._holds_a_gate:
                self.diagnostics.record(
                    Finding.STATELESS_MOUNT_REDOES, node_id, slug
                )
            # And what the compiler alone knows: this mount runs THAT
            # graph. A closure is opaque to LangGraph's `xray`, so unless
            # the compiler records it, a composition can only be drawn by
            # hand — see `compile/composition.py` for why this is a
            # recording rather than a change to how the child is added.
            # Keyed by the GRAPH node name, which is what a drawing has.
            self.mounted_graphs[safe_name(node_id)] = MountedGraph(
                slug=slug,
                graph=child_graph,
                mounts=dict(child_runtime.mounted_graphs),
                # What this child asked to be sized at, for the worst case
                # `composition_step_budget` reports (63). The closure below
                # applies the same number at run time through
                # `mount_step_budget`; recording it here is what lets a
                # caller be told the total *before* the run rather than
                # after it.
                saved_step_budget=workflow_step_budget(child_sizing_document),
            )

    if child_graph is None:
        label = slug or "(no workflow selected)"
        self.diagnostics.record(Finding.UNRESOLVED_SUBGRAPH, label)
        captured = None
    else:
        captured = child_graph

    # **`async def`, third of Phase D** (`async-first/06`). A mount is the
    # longest step this compiler can schedule — a whole other workflow run
    # as one node — so the work abandoned when a run is stopped inside one
    # is everything the child had left to do.
    #
    # The three things that ride on this closure are each pinned in
    # `tests/test_a_mount_awaits_its_child.py`, because a mount is a
    # closure over the child's invoke rather than a LangGraph subgraph and
    # none of them is obviously safe across an `await`: the child's
    # inherited checkpointer, the `interrupt()` a gated child raises for
    # the PARENT's checkpointer to hold, and the `GraphRecursionError`
    # translated at this boundary into our own sentence.
    async def run(state: RunState) -> dict[str, Any]:
        if captured is None:
            return {"outputs": {node_id: ""}}
        plain = _upstream_text(state, upstream)
        # Conditional feeds split by WHO decided (found across two live
        # bugs): a ROUTER's output is its own rendered conversation block
        # — redundant now that real history crosses this boundary, and
        # forwarding it made the Architect face its dialogue twice and
        # re-ask its interview question verbatim. A GRADER's or an
        # approval's conditional edge carries real content (the
        # candidate under review — the code-workshop's review subgraph
        # broke the other way when this rule lumped them together).
        router_sources = [
            src for src in conditional_upstream
            if self._types.get(src) == "route.classifier"
        ]
        content_sources = [src for src in conditional_upstream if src not in router_sources]
        routed_content = _upstream_text(state, content_sources)
        if plain or routed_content:
            question = plain or routed_content
        elif router_sources:
            question = state.get("question", "") or _upstream_text(state, router_sources)
        else:
            question = state.get("answer", "") or state.get("question", "")
        # The spine rule: a mounted child owns its OWN memory namespace.
        # An invoke here inherits the parent's config through the runnable
        # context, so without an explicit override the child's
        # save_memory(scope="workflow") would land in the PARENT's slug —
        # the exact leak skills/knowledge isolation already closes for
        # their assets (ticket 67's lesson, applied to the Store). The
        # rest of `configurable` (user_email, thread_id, session_id)
        # crosses untouched: the person and the thread are the same on
        # both sides of the mount.
        #
        # **Override exactly one key, and rebuild nothing** (ticket 02).
        # This used to read the ambient config, drop every `__*` and
        # `checkpoint*` key, and pass the remainder as the child's whole
        # `configurable`. That reasoning was backwards on both counts:
        #
        # 1. A config passed to `invoke` is MERGED over the ambient one,
        #    never substituted for it — so listing the keys that may cross
        #    bought no isolation, while *omitting* one was the only way to
        #    say anything at all. The single key we actually mean to change
        #    is `workflow_slug`.
        # 2. `checkpoint_ns` is not "the parent's internals": it is the
        #    child's ADDRESS. LangGraph derives a nested graph's namespace
        #    from it (`"node_name:uuid"`, joined with `|` when nested —
        #    docs: Checkpointers > Checkpoint namespace), and that is what
        #    `stream(subgraphs=True)` reports as each frame's `ns`.
        #    Replacing `configurable` wholesale with a checkpoint-free copy
        #    made the child invoke look like a fresh ROOT graph, so every
        #    frame it emitted lost the `<mount>:<task-id>` head — measured
        #    live, and reproduced in `test_mounted_subgraph_namespace.py`.
        #    With a checkpointer present (the live path, never the unit
        #    tests) the child's frames stopped being attributable to the
        #    mount at all, which is precisely why the highlight sat on the
        #    router for the twenty seconds the mounted analyst worked.
        child_config: dict[str, Any] | None = (
            {"configurable": {"workflow_slug": slug}} if slug else None
        )
        # And the second key this boundary sets, for the first time in
        # `organisms-first-class` 61: how much of the run's budget this
        # mount may spend. `recursion_limit` is a STANDALONE `config` key,
        # not a member of `configurable` — putting it there would set an
        # ordinary configurable named `recursion_limit` that LangGraph
        # never reads, and the mount would silently keep the run's number.
        #
        # `ensure_config()` is what the ambient runnable context answers
        # with, so `inherited` is the number this superstep is itself
        # running under — the run's ceiling as the mount sees it. Never
        # raised, only lowered; `mount_step_budget` carries the argument
        # and the two readings it rejects.
        inherited_budget = int(ensure_config().get("recursion_limit") or DEFAULT_STEP_BUDGET)
        requested_budget = workflow_step_budget(child_sizing_document)
        child_budget = mount_step_budget(inherited_budget, child_sizing_document)
        if child_budget != inherited_budget:
            child_config = {**(child_config or {}), "recursion_limit": child_budget}
        # The child's CEILING is the run's; the child may only ask for
        # less. `organisms-first-class` 60 settled the first half — a mount
        # is one isolated step of this run, so it is budgeted like one, and
        # the number arrives through the ambient runnable config with the
        # `configurable` override of ticket 02 riding beside it. 61 settled
        # the second: before it, a child package's `settings.recursionLimit`
        # was consulted nowhere on this path in *either* direction, at any
        # depth, so a field that reaches every direct door
        # (`workflow-gallery` 26) was dead the moment the same package was
        # mounted. It now lowers this one invoke's ceiling and can never
        # raise it — `mount_step_budget` carries the argument and the two
        # readings it rejects.
        #
        # What 60 refused was the *report*: below the slack `56`'s guard
        # needs, the child cannot stop itself, and LangGraph's own exception
        # used to reach the caller whole, advising them to increase a limit
        # this product's pinned copy tells them not to. Translated at the
        # boundary instead, the way `credential_error_from` translates a
        # vendor's refusal — and now carrying, when it is true, the one
        # thing 61's rule costs a developer: the number they saved and the
        # smaller one the run could actually give.
        try:
            final = await captured.ainvoke(
                {
                    "question": question,
                    # The conversation crosses the boundary (found live: the
                    # Architect routed through the concierge re-asked its
                    # interview question every turn — the child was invoked
                    # with fresh state, so the parent thread's history never
                    # reached it). Graph state stays isolated; the DIALOGUE
                    # is precisely what a routed conversational child needs.
                    #
                    # Withheld from a **per-thread** child, and only from
                    # one (`organisms-first-class` 30): that child already
                    # holds its own history in its own checkpoint, so
                    # copying the parent's on top of it says every turn
                    # twice — measured at five messages where four had been
                    # said. A per-invocation or stateless child has no
                    # history of its own and this copy is the only
                    # continuity it can have, so it is unchanged for them.
                    "messages": (
                        list(state.get("messages") or [])
                        if carries_the_parents_dialogue(persistence)
                        else []
                    ),
                    "attempts": 0,
                    "decisions": {},
                    "outputs": {},
                },
                child_config,
                # **Inherit, then narrow** (`organisms-first-class` 76).
                # A mount is a closure, so the parent's runtime rides down
                # this call whether or not anyone asks it to: the child used
                # to read the parent's context object entire, including keys
                # it never declared, while its own defaults never
                # materialised because its own schema was never constructed.
                # `mount_run_context` narrows the run's values to the keys
                # the child's own document asks its callers for, and the
                # child's schema — minted `sealed`, above — fills the rest
                # from the child's own defaults. The same rule as the step
                # budget one screen down: the run supplies, the child's own
                # drawing decides.
                context=mount_run_context(
                    child_context_document or {}, run_context(), slug=slug
                ),
            )
        except GraphRecursionError as exc:
            # The field a developer set, and what it could not buy
            # (`organisms-first-class` 61). Only when the package asked for
            # MORE than the run allowed — that is the one case the mount
            # boundary overrules a saved field, and overruling one in
            # silence is what this ticket refused. A package that asked for
            # less got exactly what it asked for and there is nothing to
            # explain, so no sentence is invented for it.
            overruled = (
                f" The mounted workflow saved a step budget of {requested_budget} "
                f"supersteps, and a mount may only ask for less than the run's — "
                f"this run allowed {inherited_budget}."
            ) if requested_budget is not None and requested_budget > inherited_budget else ""
            raise StepBudgetExhausted(
                f'The mounted workflow "{slug or "no workflow selected"}" '
                "spent the whole of this run's step budget without producing an "
                "answer. A mount runs as one isolated "
                "step of this run and spends the same budget, and what that buys "
                "depends on the mounted workflow's own drawing — every node on a "
                "cycle costs a superstep per lap. A loop that never settles needs a "
                "grader that can pass it, not more supersteps." + overruled
            ) from exc
        # The child is a run, so it is read through the run seam: a mounted
        # document with two exits of its own would otherwise lose one on
        # its way into the parent, which is `launch-readiness/174` one
        # level down and invisible from the parent entirely.
        answer = published_answer(final)
        # The child's loop cost is part of the parent's story: without
        # this, a Team that revised twice reports attempts=0 (ticket 60).
        update: dict[str, Any] = {"outputs": {node_id: answer}, "answer": answer}
        # What happened *inside* the mount, so the blocking door can report
        # on it too — see `nested_record` (`every-workflow-green` 16).
        # Both the child's own nodes and whatever *its* mounts recorded,
        # each gaining this mount's segment. That composition is the whole
        # of depth support: `nested-mounts` → `nested-mounts-mid` →
        # `chained-summarizer` produces
        # `mount-mid/mount-inner/summarise1`, which is exactly the key the
        # streaming door builds from the frame path. Without the second
        # line the innermost workflow was invisible on this door and
        # visible on the other — ticket 16 again, one level down.
        inside = {
            **nested_record(node_id, final.get("outputs")),
            **nested_record(node_id, final.get("nested_outputs")),
        }
        if inside:
            update["nested_outputs"] = inside
        # And what the child's tools were actually asked
        # (`osg-agent-experience/88`). `tool_use` is the run's only record of
        # the statements it sent — `executed_statements.statements_executed`
        # reads it and nothing else, and `runs.sqlite`'s `statements` column
        # is that reading — so a composition that did not fold it published a
        # breakdown from a warehouse beside an empty list of what it asked.
        # Measured across five recorded runs of one adopter's analyst workflow on 2026-09-06: the flat
        # workflow recorded its statement, the four routed through mounts
        # recorded none, and a card about one of their figures was closed on
        # a rule because the statement behind it could not be read.
        #
        # **One call, not two.** `outputs` needs both the child's own map and
        # its `nested_outputs`, because the child keeps those apart; the
        # child's `tool_use` is one map that already holds its own mounts'
        # folds, so prefixing it once carries every level — `mount-cargo/`
        # over `mount-inner/lens-sql`, which is the same path
        # `nested_record` mints for the other four keys and the same one the
        # streaming door builds from a frame's own path.
        #
        # The mount writes no row of its own: it called no tool, and a row
        # saying otherwise would make `used_no_tools` and every grounding
        # gate read a caller as a caller's tool.
        ran_inside = nested_record(node_id, final.get("tool_use"))
        if ran_inside:
            update["tool_use"] = ran_inside
        # And the child's force-passes. Found while verifying 16: the
        # streaming door reported `Grader "mount-web/grader1" ran out of
        # attempts…` and the blocking door said nothing, because `forced`
        # was discarded at this boundary exactly as `outputs` was. Same
        # prefix, same reason — two doors must not disagree about whether
        # a mounted grader gave up.
        forced_inside = nested_record(node_id, final.get("forced"))
        if forced_inside:
            update["forced"] = forced_inside
        # And the child's lost verdicts, for the identical reason
        # (`workflow-gallery` 31): a mounted grader whose revise edge is
        # unwired is exactly as invisible as a mounted grader that gave up,
        # and two doors must not disagree about either.
        unrouted_inside = nested_record(node_id, final.get("unrouted"))
        if unrouted_inside:
            update["unrouted"] = unrouted_inside
        # And the child's budget stops — the fourth key of the same set and
        # the one that arrived a ticket later. `56` gave a starved grader a
        # sentence on the silent channel; inside a mount it died here, so a
        # child that stopped its own loop and published what it had looked
        # exactly like a child that settled (`organisms-first-class` 60).
        # Same prefix as the three above, which is also the key
        # `streaming.py` folds from the child's own frames — so the fold
        # overwrites rather than doubles, and the two doors agree.
        starved_inside = nested_record(node_id, final.get("budget_stops"))
        if starved_inside:
            # And, when this boundary could not honour the child's own
            # saved number, that fact travels *inside* the value
            # (`organisms-first-class` 62). 61 made the overrule speak only
            # on the crash path, which is minted here and holds both
            # numbers; the graceful stop is minted in
            # `workflow_compiler.step_budget_warnings` out of this key,
            # where the requested number had no way to arrive. It rides the
            # absorb the other three keys ride rather than a fifth private
            # channel — the streaming door folds these values through
            # verbatim, so both doors gain it together.
            #
            # Only when the ceiling actually bit: the child stopped itself
            # AND asked for more than the run allowed. A child that asked
            # for less got what it asked for, and a child that asked for
            # more and never ran low is unharmed — neither is worth a
            # sentence, and manufacturing one would be noise on every run.
            if requested_budget is not None and requested_budget > inherited_budget:
                starved_inside = {
                    key: record_overruled_mount(
                        value,
                        slug or "no workflow selected",
                        requested_budget,
                        inherited_budget,
                    )
                    for key, value in starved_inside.items()
                }
            update["budget_stops"] = starved_inside
        child_attempts = final.get("attempts")
        if isinstance(child_attempts, int) and child_attempts > 0:
            update["attempts"] = child_attempts
        return update

    return run
