"""Node behaviour: what each node *does* once the compiler has decided the shape.

The split with `workflow_compiler` is deliberate and load-bearing. The compiler
owns **topology** and knows nothing about models, prompts or tools; this file owns
**behaviour** and knows nothing about edges or entry points. That is what lets the
entire graph structure be tested with no API key, and it is why a new node type is
a factory entry here rather than a change to the compiler.

Routing decisions are written to `state["decisions"][node_id]`, which the
compiler's `path` function reads. So a router node *decides* and the conditional
edge *dispatches* — two responsibilities, two places, and neither has to know how
the other works.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    # Types only — `from __future__ import annotations` keeps langgraph's
    # store out of this module's import graph, the pattern `loader.py`
    # established. The name is what matters here: `BaseStore` is the memory
    # store, never the filesystem `WorkflowStore` (ticket 12).
    from langgraph.store.base import BaseStore

    # `mounted_graphs` is annotated with it below. The runtime import is
    # deliberately local to `builder_for` — `compile.composition` imports
    # back into this module — so the forward reference had nothing to
    # resolve against and both gates said so: ruff `F821` and mypy
    # `name-defined` (`organisms-first-class` 47).
    from openstategraph.compile.composition import MountedGraph


# `Grader` and `Router` are used by their families now (`compile/nodes/`) and
# are re-exported here for the reason every other name carved out of this
# module is: both were importable from `node_runtime` before the split, and the
# seam is ours while an importer's spelling is not. Nothing here calls them.
#
# What a re-export does **not** survive is a substitution.
# `monkeypatch.setattr(node_runtime, "Grader", …)` rebinds this name and not
# the one `nodes/grader.py` resolves, so the four ladder-substituting tests
# moved their patch target to the family module rather than keep patching a
# name the builder no longer reads.
from openstategraph.abc.grader import Grader  # noqa: F401
from openstategraph.abc.router import Router  # noqa: F401
from openstategraph.abc.node_family import INodeFamily, NodeBuildContext, NodeCapabilities
from openstategraph.compile.graph_names import GraphNames
from openstategraph.compile.node_families import discovered_node_families
from openstategraph.compile.node_types import NodeTypeRegistry
from openstategraph.compile.run_context import (
    prompt_context_fields,
    run_context_prompt_section,
)
from openstategraph.compile.diagnostics import (
    CompileDiagnostics,
    Finding,
    denies_holding_tools,
)
from openstategraph.compile.side_effects import (
    acts_outside_the_run,
    max_attempts,
    reaches_itself,
    repetition_clause,
    upstream_of,
)
from openstategraph.compile.grounding import (
    answers_from_outside_the_run,
    gated_by,
    reaches_without_passing,
)
from openstategraph.compile.reducers import RESET as _RESET  # noqa: F401
from openstategraph.validation import MOUNT_NODE_TYPES
from openstategraph.compile.reducers import Reducer, reducer_for  # noqa: F401
from openstategraph.compile.workflow_compiler import (
    GUARD_CHECK_TYPE,
    GUARDRAIL_TYPE,
    CompiledPlan,
    unrun_query_claim,  # noqa: F401 — re-exported; `test_a_cited_query_that_never_ran` imports it from here
)
# Re-exported, not merely used: `context.py` was carved out of this module and
# every one of these names was importable from here before the move. The seam
# is ours; an importer's spelling is not.
from openstategraph.compile.context import (  # noqa: F401
    _branch_entries,
    _text,
    advisor_context,
    branch_context,
    held_tools_context,
    nested_record,
    rejection_feedback,
    retry_inventory,
    revision_request,
)
from openstategraph.memory import MemorySettings
from openstategraph.reasoning import REASONING_EFFORT_KEY, apply_reasoning_effort

# Re-exported for the same reason `context.py`'s names are: `state.py` was
# carved out of this module and every one of these was importable from here
# before the move, underscore names included, because the tests import them.
from openstategraph.compile.state import (  # noqa: F401
    RESET,
    STEP_BUDGET_FLOOR,
    RunState,
    published_answer,
    published_exits,
    _silent_member_note,
    _thread_question,
    _upstream_text,
    _upstream_verdict,
    _wired_skill,
    keep_latest_nonempty,
    keep_max,
    merge_decisions,
)
from openstategraph.compile.state import NO_ANSWER_PRODUCED as _NO_ANSWER_PRODUCED
# Four more seams from the same split (`docs-and-gaps/03`), re-exported for the
# reason every block below is: every one of these was importable from here
# before the move, and the seam is ours while an importer's spelling is not.
# `ToolRegistry`, `PackageAssets`, `RuntimeServices` and `chinook_tool_registry`
# are named in this module's `__all__` and reached by name across the tests.
from openstategraph.compile.token_stream import (  # noqa: F401
    MACHINERY_NODE_TYPES,
    NOSTREAM_TAG,
    silence_tokens,
)
from openstategraph.compile.deep_tier import _DeepAgentAsChatModel  # noqa: F401
from openstategraph.compile.runtime_services import (  # noqa: F401
    PackageAssets,
    RuntimeServices,
    ToolRegistry,
    chinook_tool_registry,
)
from openstategraph.compile.fields import _replaces_rules, _summarizes  # noqa: F401
from openstategraph.compile.nodes.guard import _BUILT_IN_CHECKS  # noqa: F401
from openstategraph.compile.grounding import _PRODUCES_CONTENT  # noqa: F401
# Re-exported for the same reason the names below are: `reporting.py` was
# carved out of this module (`docs-and-gaps/03`) and every one of these was
# importable from here before the move, `_final_text` and `_values_never_sent`
# included — `test_the_emittable_prelude.py` records where `_final_text` now
# lives, and this line is why the old spelling still resolves.
from openstategraph.compile.reporting import (  # noqa: F401
    DECLARATION_RECORD_CAP,
    QUERY_RESULT_RECORD_CAP,
    _final_text,
    _values_never_sent,
    tool_report,
)
# Re-exported for the same reason `context.py`'s and `state.py`'s names are:
# `mount_overrides.py` was carved out of this module (`docs-and-gaps/03`) and
# every one of these was importable from here before the move, including the
# two underscore ones the adversarial tests reach for.
from openstategraph.compile.mount_overrides import (  # noqa: F401
    RESERVED_OVERRIDE_KEYS,
    _as_override_map,
    _merge_override_maps,
    apply_mount_overrides,
)
# `SUMMARIZE_KEEP` and the two constants beside it left with `_agent`, their
# only reader. Re-exported because they were importable from here before
# the split and the seam is ours while an importer's spelling is not.
from openstategraph.compile.nodes.agent import (  # noqa: F401
    SUMMARIZE_FRACTION,
    SUMMARIZE_KEEP,
    SUMMARIZE_TOKENS,
)
from openstategraph.compile.nodes import (
    agent,
    approval,
    functions,
    grader,
    guard,
    io,
    memory,
    mount,
    orchestration,
    resolvers,
    router,
)
from openstategraph.compile.static_source import (
    STATIC_TEXT_NODE_TYPES,
    StaticSource,
    resolve_static_sources,
)

# Moved to `compile/state.py` by `launch-readiness/174` and re-exported here,
# exactly as `NO_MODEL_MARKER` is: it is a value written into `RunState`, and
# `published_answer` has to recognise it without importing this module.
NO_ANSWER_PRODUCED = _NO_ANSWER_PRODUCED




#: `workflow_compiler.ROUTER_TYPE`, restated here rather than imported: this
#: module already spells the literal out at each call site it needs
#: (`registry.register`, `_agent`'s `conditional_upstream`), so a new use adds
#: to an existing pattern rather than a new dependency.
ROUTER_NODE_TYPE = "route.classifier"




#: Maps a tool node type to the Python tool that implements it.
#:
#: Injectable, because tool discovery is workflow-scoped (ticket 18) and the
#: shared catalogue must not accumulate every workflow's tools. Passing an empty
#: registry is valid: the agent simply gets no tools, which is a degraded run
#: rather than a crash.
logger = logging.getLogger(__name__)






def _split_model_selection(selection: str) -> tuple[str, str]:
    """`(provider, model_id)` from either separator the string might carry.

    The canvas writes `provider/modelId` (slash) — `ProviderRegistry.
    selectionFor`'s own format. `init_chat_model` takes a colon, and that is
    exactly what a human types by hand, which is how `launch-readiness` 45
    happened: `ollama:gpt-oss:120b-cloud` partitioned on `/` alone left
    `model_id` empty, discarded the selection, and ran the shared default in
    silence. Slash is tried first because it is the canonical, canvas-written
    form and a model id can itself contain a colon (`gpt-oss:120b-cloud`);
    trying colon first would cut that id at its own first colon.
    """
    if "/" in selection:
        provider, _, model_id = selection.partition("/")
    else:
        provider, _, model_id = selection.partition(":")
    return provider, model_id


def _safe_model_name(model: Any) -> str:
    """A human name for a fallback model, for a warning message that must not
    itself blow up.

    `openstategraph.reasoning._model_name` reads `model.model`/`model_name`
    via `getattr(..., default=None)` — safe for an ordinary `BaseChatModel`,
    and not safe here: the shared default handed to `validate`/`graph` is
    `_drawing_only_model()`, an `UnconfiguredProvider` whose `__getattr__`
    *raises* on every attribute rather than returning one, precisely so a
    real call surfaces the actionable reason instead of an `AttributeError`.
    Reading its name to report a **different** node's degraded selection hit
    exactly that raise and turned a warning into a crash
    (`launch-readiness` 45/62, found running the shipped examples). Naming an
    `UnconfiguredProvider` by its own diagnosis is more useful than the
    generic type name in any case — it already says which credential or
    package is missing.
    """
    from openstategraph.chat_model import UnconfiguredProvider

    if isinstance(model, UnconfiguredProvider):
        return f"nothing — the shared default is unconfigured too: {model._diagnosis}"
    try:
        from openstategraph.reasoning import _model_name

        return _model_name(model)
    except Exception:
        return type(model).__name__




















class NodeRuntime:
    """Builds the callable for each node type.

    A registry keyed by node type rather than an if-chain, so adding a node type
    is a registration and `core` stays closed for modification.
    """

    def __init__(
        self,
        *,
        services: RuntimeServices | None = None,
        model: Any = None,
        tools: ToolRegistry | None = None,
        functions: dict[str, Any] | None = None,
        document_loader: Callable[[str], dict[str, Any]] | None = None,
        package_loader: Callable[[str], 'PackageAssets'] | None = None,
        memory_store: 'BaseStore | None' = None,
        memory: MemorySettings | None = None,
        skills_context: str = "",
        workflow_middleware: dict[str, Any] | None = None,
        knowledge_package_dir: Any = None,
        skills_package_dir: Any = None,
        knowledge_dir_override: Any = None,
        max_attempts: int = 3,
        advisor_catalog: str = "",
        _ancestry: tuple[str, ...] = (),
    ) -> None:
        if services is not None:
            model = services.model
            tools = services.tools
            functions = services.functions
            document_loader = services.document_loader
            package_loader = services.package_loader
            memory_store = services.memory_store
            memory = services.memory
            skills_context = services.skills_context
            workflow_middleware = services.workflow_middleware
            knowledge_package_dir = services.knowledge_package_dir
            skills_package_dir = services.skills_package_dir
            knowledge_dir_override = services.knowledge_dir_override
            max_attempts = services.max_attempts
            advisor_catalog = services.advisor_catalog
        #: Everything this runtime collaborates with, as one named object.
        #:
        #: `RuntimeServices` is ticket 72's parameter object, built because
        #: the keyword constructor had grown to nine parameters. `__init__`
        #: then unpacked it straight back onto `self` as thirteen public
        #: attributes, so the grouping existed for exactly the length of the
        #: call and `NodeRuntime` carried the whole widening anyway
        #: (reviews-2026-08-14 ticket 07). Kept whole now, which is what
        #: CLAUDE.md means by extending a class with a collaborator rather
        #: than a member.
        #:
        #: Normalised here rather than at every read: `tools or {}` in
        #: forty-eight places is the same defect wearing a different hat.
        #: What each service *is* is documented on the dataclass' own fields.
        self.services = RuntimeServices(
            model=model,
            tools=tools or {},
            functions=functions or {},
            document_loader=document_loader,
            package_loader=package_loader,
            memory_store=memory_store,
            memory=memory or MemorySettings(),
            skills_context=skills_context,
            workflow_middleware=dict(workflow_middleware or {}),
            knowledge_package_dir=knowledge_package_dir,
            skills_package_dir=skills_package_dir,
            knowledge_dir_override=knowledge_dir_override,
            max_attempts=max_attempts,
            advisor_catalog=advisor_catalog,
        )
        #: The chain of subgraph slugs above this runtime — how a workflow
        #: that (transitively) includes itself is refused at build time
        #: instead of recursing forever at run time.
        self._ancestry = _ancestry
        #: One mounted package, compiled once — keyed by what actually
        #: determines the built child, `(slug, overrides, persistence)`.
        #:
        #: `the-cost-of-one-more` 02: the mount graph is a DAG, and resolving
        #: it per mount *site* cost `2^(d+1) - 1` compiles for `d` levels each
        #: mounting the next twice. It hangs off the runtime rather than off
        #: the module because that is what makes those three fields a
        #: sufficient key — a runtime fixes the services the child inherits,
        #: the ancestry that refuses a cycle, and the settings a context gap is
        #: measured against. And it is a memo rather than a cache because it
        #: dies here: `docs/decisions/per-request-compile-cost.md` declined a
        #: cache over an invalidation surface, and a thing with no lifetime has
        #: none. Written and read only by `compile/nodes/mount.py`.
        self._mount_memo: dict[tuple[str, str, str], Any] = {}
        #: Per-node model overrides, keyed by the resolved LangChain model
        #: string — cached so ten agents on the same non-default model share
        #: one client instance rather than each cold-starting its own.
        self._model_cache: dict[str, Any] = {}
        #: node id -> node type, populated by `factory()`.
        self._types: dict[str, str] = {}
        #: node id -> raw node dict, populated by `factory()`. A tool
        #: binding is resolved by *type* against `self.services.tools`, which has no
        #: access to that specific bound node's own `data` — this is how a
        #: tool factory (e.g. `tool.chinook-execute-sql`'s row cap) reads a
        #: per-node config value rather than only ever seeing its type.
        self._nodes: dict[str, dict[str, Any]] = {}
        #: The document's own `settings`, populated by `factory()`. Empty
        #: until then, so a runtime built and never handed a document reads
        #: as "asked for nothing" rather than raising.
        self._settings: dict[str, Any] = {}
        #: node id -> the resolved text of every static-text node, populated
        #: by `factory()`. The ninth public member and the same kind of thing
        #: as `machinery_nodes`: a fact this compile established that only the
        #: compiler knows — *which* of a skill's two sources this run actually
        #: used (`launch-readiness` 94, `compile/static_source.py`).
        #:
        #: Public because it is the seam. Two readers consult it —
        #: `_static_text`, building a graph node, and `state._wired_skill`,
        #: inside an agent's closure — and before this map existed both
        #: open-coded the field precedence in two modules, which is how one of
        #: them came to read a stale copy for as long as it did.
        self.static_sources: dict[str, StaticSource] = {}
        self._prompt_context: tuple[Any, ...] = ()
        #: What the compiler noticed and could not resolve — unresolved
        #: tools and functions, unknown node types, mounts whose outcome
        #: nothing enforces, capabilities that failed to load.
        #:
        #: These were seven separate lists here, read by
        #: `api/registries.runtime_warnings()` reaching across into all seven
        #: (reviews-2026-08-14 ticket 07). The reasoning behind each kind, and
        #: the sentence it produces, is on `Finding` in
        #: `compile/diagnostics.py`; recording is deduplicated there rather
        #: than at each call site here.
        #:
        #: `CAPABILITY_FAILED` is populated from outside, by
        #: `WorkflowServices.runtime_for`.
        self.diagnostics = CompileDiagnostics()
        #: Agent/worker node id -> the canvas-wired tool nodes that produced no
        #: tool at all (`launch-readiness` 103). Written by `_bind_tools` at
        #: build time — which is when a capability's absence is actually known —
        #: and read into the node's `tool_use` row so a downstream grader can
        #: tell a decline that is an answer from a decline that is a bug report.
        self._unbound_capabilities: dict[str, list[str]] = {}
        #: Graph node names whose streamed text is machinery rather than the
        #: reply — the compile half of the streaming audience boundary
        #: (ticket 25; `api/audience.AnswerChannel` is the other half).
        #:
        #: Populated by `factory()` from `MACHINERY_NODE_TYPES`, and unioned
        #: with every mounted child's set in `_subgraph`. The union is the
        #: part that was actually missing in the wild: a mount compiles a
        #: second document whose node names the parent has never heard of,
        #: and `data_query` — the loudest leak QA read — came from the
        #: *child's* router streaming through the parent's one stream.
        #:
        #: Both spellings of every name are recorded (the canvas id and its
        #: `safe_name`), because a `token` frame is reported under whichever
        #: the stream fold could resolve, and node ids legally carry colons
        #: that LangGraph node names may not.
        self.machinery_nodes: set[str] = set()
        #: Graph-node name -> canvas node id, for **this document and every
        #: document mounted under it** (tickets 33/34).
        #:
        #: The API already builds this map for the document being run, from
        #: its own plan. What it could not build is the same map for a *child*:
        #: a mount compiles a second document whose ids the parent has never
        #: heard of, so a frame from inside it reached the browser carrying
        #: `agent_sql` — `safe_name` of the child's `agent-sql` — which no
        #: document on the canvas contains. Opening the mount mid-run therefore
        #: showed a static diagram: every frame named a node that document did
        #: not have, and lighting nothing was the only honest answer left.
        #:
        #: Unioned upward in `_subgraph` for exactly the reason
        #: `machinery_nodes` is: the child's frames ride the PARENT's one SSE
        #: stream, so the parent's stream fold is the only place that can
        #: resolve them. The parent's own entries win a collision — `in1` and
        #: `router1` are shared by `concierge` and `chinook-assistant` today —
        #: Which canvas node, in which document, each compiled graph name
        #: refers to — see `compile/graph_names.py`, which holds the two maps
        #: and the rule for folding a mounted child's into this document's.
        #:
        #: They were two attributes here, always handed to `RunPathResolver`
        #: together and read defensively (reviews-2026-08-14 ticket 07).
        self.names = GraphNames()
        #: Graph node name -> the mount rendered under it, for previewing a
        #: composition (`workflow-gallery` 28). A mount is a **closure** over
        #: the child's `invoke()`, not a LangGraph subgraph, so `xray` has
        #: nothing to open and never will — this is the compiler saying what
        #: it built, since it is the only thing that knows. Recursive: each
        #: entry carries the child's own map, so depth costs nothing.
        #:
        #: Drawing only. Nothing here is read on a run path, and the closure
        #: keeps its own reference to the compiled child regardless.
        self.mounted_graphs: dict[str, "MountedGraph"] = {}
        #: Whether this document — or anything it mounts, at any depth — has
        #: a `human.approval` node in it (`organisms-first-class` 65).
        #:
        #: Private on purpose, unlike the three collaborators above it: the one
        #: reader is `_subgraph`, on a *child* runtime of this same class, and a
        #: public boolean would be a tenth member on a surface `CLAUDE.md` says
        #: to extend by collaborator rather than by attribute.
        #:
        #: Set by `_human_approval` as the executor is built, and unioned
        #: upward in `_subgraph` for the same reason `machinery_nodes` is: the
        #: question is asked one level *above* where the answer lives. A
        #: stateless mount is the only caller — it stores no checkpoint, so
        #: answering a gate anywhere below it re-runs the child from its first
        #: step, and the mount is the only place that knows both halves.
        self._holds_a_gate: bool = False

        #: The node types **this build implements itself**, as a registry
        #: rather than a dict literal (`export-and-eject/03`).
        #:
        #: Consulted before anything installed, because these are what a
        #: document's types *mean* — `input.text` resolving to somebody else's
        #: code would change every workflow in the venv, including the ones
        #: that never heard of the plugin. Contributed families live in
        #: `compile/node_families.py` and are consulted after this; see
        #: `builder_for`.
        #:
        #: The two arms that used to be `if`s inside `builder_for` are
        #: registrations here: the mount types by exact name, and
        #: `function.` as an **open namespace**, which is the one shape a
        #: plain dict could not hold — a `function.<name>` node binds a
        #: callable named in the *document*, so its keys are unknowable when
        #: this table is built. `NodeTypeRegistry` carries the reasoning.
        self._node_types = self._register_node_types()
        #: The families installed distributions contributed, and what failed
        #: to install. Resolved once per process by `extensions`' cache, so
        #: this costs a dict lookup per runtime rather than a `sys.path` walk.
        self._families, family_warnings = discovered_node_families()
        for shadowed in sorted(self._families.types() & self._node_types.types()):
            # Reported here rather than at discovery because this is the object
            # that holds the built-in table, and reported at all because the
            # alternative — a family that registered cleanly and is never
            # built — is the exact silence this seam exists to end.
            family_warnings.append(
                f'{self._families.source_of(shadowed)} contributes node type "{shadowed}", '
                "which this build implements itself. The built-in is used; that family "
                "will never be built."
            )
        # The same shadow, one namespace over. A package's `functions/` folder
        # binds by bare name (`function.<name>`) while a discovered *tool*
        # binds by a slug-qualified id, so a package defining
        # `def format_report` lands on a built-in's key. `builder_for`
        # consults the built-in table first — which is the right answer, and
        # was a silent one: the developer's function was simply never called
        # (`export-and-eject/11`). Reported here for the reason the family
        # loop above is: this is the object that holds the built-in table.
        for shadowed in sorted(
            key
            for key in set(self.services.functions) & self._node_types.types()
            if key.startswith("function.")
        ):
            self.diagnostics.record(
                Finding.CAPABILITY_FAILED,
                f'A function named "{shadowed[len("function."):]}" is discovered from this '
                f'package, but "{shadowed}" is a node type this build implements itself. '
                "The built-in is used; that function will never be called. Rename it.",
            )
        for warning in family_warnings:
            self.diagnostics.record(Finding.CAPABILITY_FAILED, warning)

    # ------------------------------------------------------------------
    # The node families. Each lives in its own module under `compile/nodes/`
    # and is bound here rather than defined here (`docs-and-gaps/03`). A
    # function assigned in a class body is a method, so every call site and
    # every `inspect.getsource` census still sees exactly what it saw before —
    # which is the whole reason it is a binding and not a delegating wrapper.
    # `compile/nodes/__init__.py` carries the argument in full.
    _router = router._router
    _grader = grader._grader
    _guardrail = guard._guardrail
    _guard_check = guard._guard_check
    _human_approval = approval._human_approval
    _input = io._input
    _static_text = io._static_text
    _output = io._output
    _passthrough = io._passthrough
    _resolve_vocabulary = resolvers._resolve_vocabulary
    _resolve_source = resolvers._resolve_source
    _memory_segment = memory._memory_segment
    _format_report_function = functions._format_report_function
    _discovered_function = functions._discovered_function
    _orchestrator = orchestration._orchestrator
    _worker = orchestration._worker
    _subgraph = mount._subgraph
    #: Written by `_agent` when it binds this node's tools — over in
    #: `compile/nodes/agent.py` now, which is the whole reason this line
    #: exists. An annotation with no value creates no attribute, so the
    #: public-surface census still counts what it counted (it follows the
    #: bound function to its own source and finds the assignment there); this
    #: is for mypy, which cannot type-check a write to an attribute the class
    #: never declares.
    last_bound_tools: list[str]

    _agent = agent._agent
    _async_task_middleware = agent._async_task_middleware

    def _register_node_types(self) -> NodeTypeRegistry:
        """One registration point per node type this build implements.

        A method rather than a table module because every value is a bound
        method of this object: a separate module would have to reach through
        thirteen private attributes to build the same table, which trades a
        readable list for a privacy leak and buys nothing.

        Adding a *built-in* node type is still a line in this method, and that
        is the honest reading of CLAUDE.md's **O** rather than a hole in it —
        a built-in is the engine. Extending the engine **from outside** is
        `openstategraph.node_families`, which needs no edit here at all
        (`compile/node_families.py`, install-experience 08).
        """
        registry = NodeTypeRegistry()
        registry.register("input.text", self._input)
        # NOT `_input`. A skill source is a *static text source*, not the
        # run's entry point — see `_static_text`. Registered from
        # `STATIC_TEXT_NODE_TYPES` rather than from literals here, so the
        # types that build through `_static_text` and the types
        # `resolve_static_sources` resolves a file for cannot drift apart —
        # which is the subject of `launch-readiness` 94 one level down.
        for static_type in sorted(STATIC_TEXT_NODE_TYPES):
            registry.register(static_type, self._static_text)
        registry.register("agent.llm", self._agent)
        registry.register("route.classifier", self._router)
        registry.register("route.grader", self._grader)
        registry.register("human.approval", self._human_approval)
        registry.register("guard.policy", self._guardrail)
        registry.register("guard.check", self._guard_check)
        # What a word means here, resolved before the model rather than
        # picked by it (`launch-readiness` 135).
        registry.register("resolve.vocabulary", self._resolve_vocabulary)
        # Which store answers, settled before the model rather than picked by
        # it (`launch-readiness` 150). The vocabulary resolver's sibling.
        registry.register("resolve.source", self._resolve_source)
        registry.register("memory.segment", self._memory_segment)
        registry.register("orchestrate.supervisor", self._orchestrator)
        registry.register("orchestrate.worker", self._worker)
        registry.register("function.format_report", self._format_report_function)
        registry.register("output.formatted", self._output)
        # The first convention arm, which was only ever a closed set nobody
        # had registered. The constant, not the literal (install-experience
        # 08): "which node types mount a child" is one fact, and this was one
        # of four places that spelled it.
        for mount_type in MOUNT_NODE_TYPES:
            registry.register(mount_type, self._subgraph)
        # The second, and the one a dict could not express. Registered after
        # `function.format_report` and losing to it by the registry's own
        # exact-beats-namespace rule, so a package's own `format_report` can
        # never shadow the built-in by accident.
        registry.register_namespace("function.", self._discovered_function)
        return registry

    @property
    def _builders(self) -> dict[str, Callable[..., Any]]:
        """The exact registrations as a dict, for readers that want one.

        Five tests walk "every built-in node type and its builder" through
        this name (`test_model_field_contract`, `test_skill_layer_contract`,
        `test_reasoning_effort`, `test_architect`, `test_schema_v3_team_collapse`).
        Kept as a read-only view rather than renamed at five call sites in a
        commit about the dispatch: a copy, so nothing can write the table back.
        """
        return self._node_types.mapping()

    def factory(
        self, document: dict[str, Any]
    ) -> Callable[[str, dict[str, Any], CompiledPlan], Any]:
        """The `node_factory` the compiler expects.

        Takes the whole document because a node's behaviour can depend on
        *another* node: an agent needs the **type** of each tool bound to it in
        order to resolve the implementation, and the plan carries only ids.
        """
        self._types = {
            n["id"]: str(n.get("type", "")) for n in document.get("nodes", [])
        }
        self._nodes = {n["id"]: n for n in document.get("nodes", [])}
        # Where a skill's text comes from, decided **once**, here, before any
        # node is built and before any closure runs. Resolving it in the
        # closure instead would re-read the file mid-run and report the same
        # disagreement once per lap; resolving it per builder would miss the
        # node entirely, because a node wired to a `skill` port is bound-only
        # and never reaches a builder at all.
        self.static_sources = resolve_static_sources(
            document, self.services.skills_package_dir
        )
        for source in self.static_sources.values():
            for finding, subjects in source.findings:
                self.diagnostics.record(finding, *subjects)
        #: The document's own settings — graph-assembly concerns, not node
        #: ones. `injectionScreening` reads from here for the same reason the
        #: checkpointer and the memory settings do.
        self._settings = document.get("settings") or {}
        #: The declared context fields a model may be shown, in document order
        #: (`organisms-first-class/72`). Read from the document **once, here**,
        #: because *which* fields opted in is a fact about the document and
        #: only the *values* are a fact about the run. Empty for every workflow
        #: that declares nothing and for every field that did not opt in — the
        #: default — so a document untouched by this feature composes the
        #: prompt it always did, byte for byte.
        self._prompt_context = prompt_context_fields(document)
        # Declared here rather than in each `_router`/`_grader`/`_input`
        # builder: a bound-only or unreachable control node never reaches a
        # builder, and it would still be able to stream if the graph later
        # scheduled it. The document is the honest source.
        from openstategraph.compile.workflow_compiler import safe_name

        for node_id, node_type in self._types.items():
            if node_type in MACHINERY_NODE_TYPES:
                self.machinery_nodes.update({node_id, safe_name(node_id)})
            # Recorded for every node, not only the machinery ones: this map
            # answers "which card is this frame about", and that question is
            # asked of every step a mounted document runs.
            self.names.remember(safe_name(node_id), node_id)

        def build(node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
            return self.builder_for(str(node.get("type", "")))(node_id, node, plan)

        return build

    def builder_for(self, node_type: str) -> Callable[..., Any]:
        """The factory that will build this node type. Total, never `None`.

        Public and separate from `factory` so the dispatch is one readable
        table rather than an if-chain inside a closure — and so a test can ask
        "which factory runs for this node type?" for every type in the
        catalogue without a hand-kept second list.
        `backend/tests/test_data_key_contract.py` does exactly that.

        Three sources, in a fixed order, and the order is the policy:

        1. the **built-in registry** — `_register_node_types`, which holds
           both the named types and the two conventions (`workflow.subgraph`
           by name, `function.` as an open namespace), so nothing installed
           can change what a shipped document's node types mean and both
           conventions stay reserved against a plugin. Inside it, an exact
           registration beats the namespace it falls under;
        2. **registered families** — the `openstategraph.node_families`
           entry-point group (install-experience ticket 08);
        3. `_passthrough`, for a type nothing implements, which reports itself
           rather than quietly forwarding.

        Until `export-and-eject/03` the first source was a dict literal and
        the conventions were two `if`s here, so the policy was half a table
        and half control flow and no test could enumerate it.

        A pure lookup, with no side effect: `test_data_key_contract.py`
        enumerates it over the whole catalogue, and a diagnostic recorded here
        would report node types nobody wired.
        """
        builder = self._node_types.resolve(node_type)
        if builder is not None:
            return builder
        family = self._families.get(node_type)
        if family is not None:
            return self._family_builder(family)
        return self._passthrough

    def _family_builder(self, family: INodeFamily) -> Callable[..., Any]:
        """Adapt a registered family to the `(node_id, node, plan)` factory.

        The adapter exists so that a family sees `NodeBuildContext` — a small,
        named, published object — instead of this class, which is a compiler
        internal with no stability guarantee and 2,000 lines of it.

        A family whose `build` raises is reported and degraded to
        `_passthrough`, never allowed to fail the compile: a plugin's bug must
        cost that node, not the whole document. That is `errors.py`'s rule
        applied one layer out from where `_passthrough` applies it.
        """

        def build(node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
            upstream = [src for src, dst in plan.edges if dst == node_id]
            context = NodeBuildContext(
                node_id=node_id,
                node=node,
                plan=plan,
                # The façade, never `self.services` (framework-packaging 09).
                # This dataclass is a compiler internal with thirteen fields
                # and no stability guarantee; `NodeCapabilities` is declared in
                # `abc` and names three. Widening what a plugin can reach is
                # now an edit to a published signature rather than a field
                # added here.
                capabilities=NodeCapabilities(
                    tools=self.services.tools,
                    functions=self.services.functions,
                    memory_store=self.services.memory_store,
                ),
                diagnostics=self.diagnostics,
                upstream_text=lambda state: _upstream_text(state, upstream),  # type: ignore[arg-type]
                resolve_model=lambda data: self._resolve_model(data, node_id),
            )
            try:
                return family.build(context)
            except Exception as exc:
                self.diagnostics.record(
                    Finding.CAPABILITY_FAILED,
                    f'The node family for "{family.node_type}" '
                    f"({self._families.source_of(family.node_type)}) failed to build "
                    f'node "{node_id}": {type(exc).__name__}: {exc}',
                )
                return self._passthrough(node_id, node, plan)

        return build

    def _resolve_model(self, data: dict[str, Any], node_id: str | None = None) -> Any:
        """This node's own model, falling back to the graph's shared default.

        Found via a TS-schema-vs-Python-factory diff: every model-calling
        node's card lets a developer pick its own model
        (`AgentNode.ts`'s `model` field, the same select `RouterNode.ts`/
        `GraderNode.ts` use), but this class only ever accepted one `model`
        for the *entire graph* — the canvas visibly showed three different
        AI Agent cards set to three different models while every one of
        them, run through the backend, used whichever single model the
        `/api/runs` request happened to resolve. This is the fix: read the
        node's own selection first, the shared default only when it has
        none.

        `data.get("model")` is the canvas's `provider/modelId` string
        (`ProviderRegistry.selectionFor`) — slash-separated, because that is
        the frontend's own format; `init_chat_model` expects a colon. Mock
        has no backend equivalent (it is a frontend-only deterministic
        simulator for the local canvas preview, not a real chat model), so a
        node configured for it falls back to the shared default exactly like
        a node with no override at all, rather than erroring.

        **Reasoning effort rides the same path**, and deliberately so: it is a
        property of *this call to this model*, not of a node family, so it is
        resolved in the one place a model becomes a model. `openstategraph.
        reasoning` decides whether the value can actually be carried; anything
        it refuses to send is reported through `capability_warnings` rather
        than swallowed — see `_apply_effort`.

        `node_id` names the node in a report when the selection cannot be
        resolved (`launch-readiness` 45/62) — optional because a handful of
        tests and the reasoning-effort suite call this directly against a
        bare `data` dict with no node in scope, and a blank or `mock`
        selection is not a failure at all, so those callers never need it.
        """
        return self._apply_effort(
            self._base_model(data, node_id), _text(data, REASONING_EFFORT_KEY)
        )

    def _base_model(self, data: dict[str, Any], node_id: str | None = None) -> Any:
        """The model itself, before any per-call parameter is applied.

        Falling back to the shared default is right (see `_resolve_model`'s
        docstring) — but doing it **silently** is not (`launch-readiness`
        45/62, found the same day, three times, all one defect): a colon
        instead of a slash, a blank selection on a grader, and an
        `UnconfiguredProvider` all discarded the node's own choice with no
        trace beyond a billing error naming a provider nobody had picked.

        The two remaining causes split by what they say about the document.
        A string with no separator this module recognises is wrong no matter
        where it runs, knowable with no credential — `_report_unparseable`
        keeps it on `CAPABILITY_FAILED`, which `validate` turns into an exit
        code (`launch-readiness` 45). A syntactically valid selection that
        *this installation* cannot serve — no key, no provider package — says
        nothing about the document; the identical selection succeeds the
        moment the credential is added, which is `validate`'s own
        zero-credential promise applied per node rather than once for the
        shared default. `_report_degraded` reports it on
        `MODEL_SELECTION_DEGRADED`, which `REPORT_ONLY` keeps off the exit
        code (`launch-readiness` 62) — otherwise every shipped package naming
        a real paid provider would fail `validate` in any environment,
        CI included, that does not carry that provider's key.
        """
        selection = _text(data, "model")
        if not selection:
            # Blank means "use the shared default", and that is deliberate
            # authoring, not a failure — never reported.
            return self.services.model
        provider, model_id = _split_model_selection(selection)
        if not model_id or provider == "mock":
            # Mock has no backend equivalent (see the docstring above); that
            # degrade is as deliberate as a blank selection. Anything else
            # with no model half is the unparseable-string case.
            if provider != "mock":
                self._report_unparseable(node_id, selection, self.services.model)
            return self.services.model
        key = f"{provider}:{model_id}"
        if key not in self._model_cache:
            from openstategraph.chat_model import UnconfiguredProvider, build_chat_model

            try:
                selected = build_chat_model(key)
                # An unconfigured provider comes back as a stand-in that raises
                # on first use, so a workflow needing no model still runs. It
                # must not reach a node here, though: the rule below is that a
                # bad per-node *selection* degrades to the shared default
                # rather than taking the run down, and a deferred raise would
                # do the opposite.
                if isinstance(selected, UnconfiguredProvider):
                    self._report_degraded(node_id, selection, self.services.model)
                    selected = self.services.model
                self._model_cache[key] = selected
            except Exception:
                # An unconfigured provider (no API key) or an unrecognised
                # model id must not take the whole run down — the shared
                # default still produces an answer, just not the node's own
                # choice. Cached too, so one bad selection does not retry
                # (and re-fail) on every node that shares it.
                self._report_degraded(node_id, selection, self.services.model)
                self._model_cache[key] = self.services.model
        return self._model_cache[key]

    def _report_unparseable(self, node_id: str | None, selection: str, fallback: Any) -> None:
        """A selection this module cannot even parse — a document defect.

        `node_id` is `None` only for the handful of direct-`data` test
        callers that predate node-id plumbing; skipping the report there is
        correct — those tests assert the fallback itself, not this report.
        """
        if node_id is None:
            return
        self.diagnostics.record(
            Finding.CAPABILITY_FAILED,
            f'Node "{node_id}" selected model "{selection}", which could not be '
            f'parsed. It ran on "{_safe_model_name(fallback)}" instead.',
        )

    def _report_degraded(self, node_id: str | None, selection: str, fallback: Any) -> None:
        """A selection this *installation* cannot serve — not a document defect.

        Same `node_id is None` exemption as `_report_unparseable`, plus one
        more: if `fallback` is itself an `UnconfiguredProvider` — the shared
        default handed to `validate`/`graph` by `_drawing_only_model()` — no
        model is ever actually going to run, in this build or any other node's.
        Reporting "it ran on X instead" when X will never be called is not a
        finding about the document, it is noise that fires on *every* real
        provider named in *any* credential-less environment (the shipped
        examples all compile with no key set, on purpose — `launch-readiness`
        45/62's own regression: this was first written unconditionally and
        turned every real-provider example into a spurious warning).
        `_report_unparseable` has no matching guard: an unparseable string is
        wrong regardless of environment, which is exactly why `validate` can
        catch it with no credential at all.
        """
        if node_id is None:
            return
        from openstategraph.chat_model import UnconfiguredProvider

        if isinstance(fallback, UnconfiguredProvider):
            return
        self.diagnostics.record(
            Finding.MODEL_SELECTION_DEGRADED,
            node_id,
            selection,
            _safe_model_name(fallback),
        )

    def _apply_effort(self, model: Any, effort: str) -> Any:
        """Sets reasoning effort where it is carried; says so where it is not.

        The whole feature is this method's second line. Passing an unsupported
        reasoning parameter has two failure shapes and they need opposite
        treatments: the provider that *rejects* it kills a run for a setting
        nobody meant to be load-bearing, and the provider that *ignores* it —
        `ChatOllama` has no such field, and Ollama is the zero-configuration
        default here — leaves a card reading "high" over a model that never
        heard it. `openstategraph.reasoning` refuses to send what cannot be
        carried, which fixes the first; this reports every refusal, which
        fixes the second.

        The channel is `capability_warnings` because that is precisely what
        this is: a capability the developer configured that did not reach the
        step. `runtime_warnings()` passes those through verbatim, so the
        sentence lands in the run response, the CLI and the MCP preview with
        no per-surface plumbing. Deduplicated — ten agents on one unsupporting
        model is one fact, not ten.
        """
        resolved, warning = apply_reasoning_effort(model, effort)
        if warning:
            self.diagnostics.record(Finding.CAPABILITY_FAILED, warning)
        return resolved

    # -- node kinds ------------------------------------------------------- #



    def _attach_ambient_knowledge(self, lc_tools: list[Any]) -> None:
        """Ambient knowledge seeking — capability by configuration.

        The exact mirror of the memory rule above (`self.services.memory_store is not None`
        → memory tools): when this workflow package's `knowledge/` directory
        is non-empty, the knowledge-lookup tool is bound to every agent and
        worker with no Knowledge atom wired. The atom remains the visible
        canvas declaration and the build button's home; an explicitly wired
        atom plus this rule is deduped by tool name to exactly one binding.
        """
        if not hasattr(self, "_ambient_knowledge_memo"):
            # One directory scan per runtime construction, not one per agent
            # or worker bound — the package cannot change mid-compile, and a
            # large canvas would otherwise re-glob knowledge/ for every node.
            from openstategraph import prebuilt_knowledge

            self._ambient_knowledge_memo = prebuilt_knowledge.ambient_knowledge_tool(
                self.services.knowledge_package_dir, knowledge_dir=self.services.knowledge_dir_override
            )
        ambient = self._ambient_knowledge_memo
        if ambient is None:
            return
        if any(getattr(t, "name", "") == ambient.name for t in lc_tools):
            return
        lc_tools.append(ambient.as_langchain_tool())

    def _bound_tool(self, tool_node_id: str) -> Any | None:
        """Resolves one bound tool node to the implementation it should use.

        The shared registry (`self.services.tools`) is keyed by *type*, one instance
        per type for the whole document — right for a stateless tool, wrong
        the moment a canvas field varies the instance's own behaviour.
        `tool.chinook-execute-sql`'s "Max rows" is exactly that case (found
        by a TS-schema-vs-Python-factory diff: the field was fully inert on
        the backend, always using the bare class default regardless of what
        a developer configured). Building a *fresh* instance here rather
        than mutating the shared one matters the moment a document has two
        SQL-tool nodes with two different row caps bound to two different
        agents — mutating the one shared object would let the second bind
        clobber the first's ceiling.
        """
        tool_type = self._types.get(tool_node_id, "")
        tool = self.services.tools.get(tool_type)
        if tool is None:
            self.diagnostics.record(Finding.UNRESOLVED_TOOL, tool_type)
            return None

        data = self._nodes.get(tool_node_id, {}).get("data") or {}
        configure = getattr(tool, "configure", None)
        if configure is None or not data:
            return tool
        # `configure` returns a fresh instance when config matters (the
        # BaseTool contract), so the shared registry instance is never
        # mutated — the row-cap special case that used to live here is now
        # each tool's own business.
        return configure(data)

    def _bind_tools(self, node_id: str, plan: CompiledPlan) -> list[Any]:
        """Every LangChain tool the canvas wired to this node.

        Resolved by the *type* of each bound node, so wiring a tool on the
        canvas is exactly what gives the agent that capability.

        **`extend`, not `append`.** A tool node contributes a *list* — one
        element for every atom in this repository, N for `tool.mcp`, whose one
        card carries a whole MCP server. `BaseTool.as_langchain_tools` carries
        the reasoning; here the consequence is that `last_bound_tools` reports
        the names actually bound rather than the nodes drawn, which for an MCP
        server is the more useful of the two.

        Discovery warnings travel the `CAPABILITY_FAILED` channel — the same
        one a plugin that would not import and a reasoning effort that could
        not be carried already use, so the sentence reaches the run response,
        the CLI and `CompiledWorkflow.warnings` with no per-surface plumbing.

        **One tool at a time, and the `try` is deliberately wide**
        (`production-ready` 93). `as_langchain_tools` is a *stranger's* method
        — a plugin's, an MCP server's — and until this guard existed one that
        raised took the whole list with it: the agent lost every other tool
        wired to it and the exception left the compile as a bare traceback.
        The contract this method already advertises is that a capability which
        cannot materialise costs one capability, and `tool.mcp` honours it by
        appending to `warnings` rather than raising; the wrapper is what makes
        the promise true for a tool that does not know about it. Nothing is
        swallowed — every exception becomes a sentence naming the node, its
        type and the exception, on the channel a lost capability already
        travels — so a real defect in a working tool is *louder* here, not
        quieter: it used to kill the run before anything could name it.
        """
        lc_tools: list[Any] = []
        warnings: list[str] = []
        #: The drawn capabilities that produced no tool at all (`launch-readiness`
        #: 103). Kept because this is the only place both halves are known — the
        #: tool nodes the canvas wired, and what each one actually handed back —
        #: and because losing it is what let a run reach a grader with no way to
        #: tell *"a writer agent has no tools"* from *"an MCP card was drawn and
        #: the server was down"*. `CAPABILITY_FAILED` below says it to a
        #: developer; this says it to the run.
        unbound: list[str] = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool = self._bound_tool(tool_node_id)
            if tool is None:
                # An unresolved type. `UNRESOLVED_TOOL` already says the true
                # thing about the node, and nothing is bound, so the capability
                # is just as absent as one whose server refused.
                unbound.append(tool_node_id)
                continue
            before = len(lc_tools)
            try:
                lc_tools.extend(tool.as_langchain_tools(warnings=warnings))
            except Exception as exc:
                warnings.append(
                    f'Tool "{tool_node_id}" (type "{self._types.get(tool_node_id, "")}") '
                    f"could not be bound and is missing from this node's tools "
                    f"({type(exc).__name__}: {exc}) — the other tools wired to it are "
                    "unaffected, but its answer will not be grounded in that data source."
                )
            if len(lc_tools) == before:
                # An empty list is how `tool.mcp` reports a server that would
                # not answer — it appends a warning rather than raising, which
                # is the contract. Counting the list rather than catching the
                # exception is therefore the only reading that covers both.
                unbound.append(tool_node_id)
        if unbound:
            # Absent rather than empty, the convention `queried` and
            # `unmet_tools` already follow: a node with nothing to report must
            # not look like a node reporting nothing.
            self._unbound_capabilities[node_id] = unbound
        for message in warnings:
            self.diagnostics.record(Finding.CAPABILITY_FAILED, message)
        self._report_repeated_side_effect(node_id, plan)
        return lc_tools

    def _acting_capabilities(self, node_id: str, plan: CompiledPlan) -> list[str]:
        """The distinct bound tool *types* on this node that act outside the run.

        **`plan.tool_bindings`, never the finished tool list** — the same
        distinction, for the same reason, as `_report_stale_tool_denial`'s
        `wired`: the ambient rules append `save_memory` and a knowledge lookup
        to nearly every agent alive, and the fix a developer would reach for
        is on the canvas.

        A type that resolved to nothing is skipped rather than assumed
        dangerous. `UNRESOLVED_TOOL` already says the true thing about that
        node, and nothing is bound, so nothing can act.

        Deduplicated by type: `support-triage` wired three `tool.email-send`
        nodes to one agent, and three identical sentences is the noise
        `absorb`'s slug key was written to avoid.
        """
        found: list[str] = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool_type = self._types.get(tool_node_id, "")
            tool = self.services.tools.get(tool_type)
            if tool is None or tool_type in found:
                continue
            if acts_outside_the_run(tool):
                found.append(tool_type)
        return found

    def _report_repeated_side_effect(self, node_id: str, plan: CompiledPlan) -> None:
        """Note a node that can act outside the run and can be run twice.

        Here rather than in either agent factory, for the reason
        `_report_stale_tool_denial` sits on the runtime: it is the identical
        statement about an agent and about a worker, and a sentence that
        exists in one factory and not the other is a defect waiting for the
        second family (`launch-readiness` 121).

        Both mechanisms are read, and both are named when both apply, because
        their fixes differ: `maxRetries` does nothing about a drawn loop.
        """
        capabilities = self._acting_capabilities(node_id, plan)
        if not capabilities:
            return
        data = self._nodes.get(node_id, {}).get("data") or {}
        clause = repetition_clause(
            max_attempts(data), cyclic=reaches_itself(node_id, plan)
        )
        if not clause:
            return
        self.diagnostics.record(
            Finding.REPEATED_SIDE_EFFECT, node_id, ", ".join(capabilities), clause
        )

    def _report_late_approval(self, node_id: str, plan: CompiledPlan) -> None:
        """Note an approval gate the action has already happened above.

        Sorted so a document with two acting nodes above one gate reports them
        in an order that does not depend on set iteration — a warning list
        that reshuffles between runs is one nobody can diff.
        """
        for source in sorted(upstream_of(node_id, plan)):
            capabilities = self._acting_capabilities(source, plan)
            if capabilities:
                self.diagnostics.record(
                    Finding.APPROVAL_COMES_TOO_LATE,
                    node_id,
                    source,
                    ", ".join(capabilities),
                )

    def _open_world_capabilities(self, node_id: str, plan: CompiledPlan) -> list[str]:
        """The distinct bound tool *types* on this node that answer from
        outside the run's own data.

        `plan.tool_bindings` read through `self._types`, exactly as
        `_acting_capabilities` reads it and for the same two reasons: the
        ambient rules append tools to nearly every agent alive, and the fix a
        developer would reach for is on the canvas. A type that resolved to
        nothing is skipped — nothing is bound, so nothing can answer.
        """
        found: list[str] = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool_type = self._types.get(tool_node_id, "")
            tool = self.services.tools.get(tool_type)
            if tool is None or tool_type in found:
                continue
            if answers_from_outside_the_run(tool):
                found.append(tool_type)
        return found

    def _report_undeclared_fallback(self, node_id: str, plan: CompiledPlan) -> None:
        """Note an Output a model-supplied quantity can reach ungated.

        Two narrowings, and they are the whole finding. It fires only where a
        bound capability *declares* `open_world = True`, so an agent holding
        the store's own query tools — the ordinary case — is never reported;
        and the walk stops at a `guard.check`, so a document that already
        gates its numbers is silent.

        Sorted, so a document with two such producers above one Output reports
        them in an order that does not depend on set iteration.
        """
        gates = gated_by(plan, self._types, GUARD_CHECK_TYPE)
        for source in sorted(reaches_without_passing(node_id, plan, gates)):
            capabilities = self._open_world_capabilities(source, plan)
            if capabilities:
                self.diagnostics.record(
                    Finding.UNDECLARED_FALLBACK,
                    node_id,
                    source,
                    ", ".join(capabilities),
                )

    def _report_stale_tool_denial(
        self, node_id: str, data: dict[str, Any], wired: list[str]
    ) -> None:
        """Note a node whose authored prose denies the tools the canvas wired.

        On the runtime rather than in either factory because it is the same
        statement about an agent and about a worker, and a sentence that exists
        in one factory and not the other is the defect `held_tools_context`'s
        own comment records one paragraph away.

        **`wired`, not the finished tool list.** The ambient rules append
        `save_memory` and a knowledge lookup to nearly every agent alive, so
        counting the finished list would flag every honest prompt in any
        package that has a memory store — and the fix a developer would reach
        for is on the canvas, which is what `wired` describes. Same
        distinction, same reason, as the `wired` snapshot `capability_door`
        reads.

        Both authored fields, because the families keep their prose in
        different places: an agent's rules are `systemPrompt`, a worker's
        identity is `role`. Generated context is never scanned — it is ours,
        and it says the opposite.
        """
        if not wired:
            return
        for key in ("systemPrompt", "role"):
            phrase = denies_holding_tools(_text(data, key))
            if phrase:
                self.diagnostics.record(Finding.STALE_TOOL_DENIAL, node_id, phrase)
                return

    def _run_context_section(self) -> str:
        """The generated **Context** block for this run, or `""`.

        Called from inside a node's `run` closure and never from a factory:
        the opted-in *fields* are known when the graph is built, but the
        *values* are ambient to the run (`run_context()` reads
        `get_runtime()`), and one compiled graph serves many runs. A section
        computed at build time would be one run's values frozen into every
        later run's prompt.
        """
        return run_context_prompt_section(self._prompt_context)

    def _direct_feedback_sources(self, node_id: str, plan: CompiledPlan) -> list[str]:
        """Graders (or approvals) whose `revise`/`rejected` edge names this
        node **directly** — the check every feedback-trusting node has always
        made, factored out so `_feedback_sources` below can widen it in one
        place instead of two.
        """
        return [
            src
            for src, dests in plan.conditional.items()
            if node_id in (dests.get("revise"), dests.get("rejected"))
        ]

    def _feedback_sources(self, node_id: str, plan: CompiledPlan) -> list[str]:
        """Graders whose rejection reaches this node — directly, or relayed
        through a router's re-dispatch of its own branch decision
        (`workflow-gallery` 48).

        A fan-out of branch agents has no expressible revision loop without
        this: a router's branches are unlimited going out while
        `agent.feedback` is `maxConnections: 1` coming in, so a `revise` edge
        cannot be drawn onto more than one branch agent at once. The owner's
        decision — feedback follows the branch — puts the edge on the
        *router* instead. The router does not reclassify on that edge; it
        replays the branch its own last decision named (`_router` below), and
        LangGraph's conditional dispatch then invokes only that branch's
        agent — so the agent that actually receives control this lap is
        always the one whose feedback should be trusted.

        This is why the widening only ever *adds* graders whose target is a
        router that can reach `node_id`: it never needs to also check which
        branch the router chose. Only the chosen branch's node runs at all;
        an agent this router does not currently route to is simply never
        invoked, trusted feedback or not.
        """
        direct = self._direct_feedback_sources(node_id, plan)
        relays = [
            r
            for r, dests in plan.conditional.items()
            if self._types.get(r) == ROUTER_NODE_TYPE and node_id in dests.values()
        ]
        if not relays:
            return direct
        seen = set(direct)
        widened = list(direct)
        for relay in relays:
            for src in self._direct_feedback_sources(relay, plan):
                if src not in seen:
                    seen.add(src)
                    widened.append(src)
        return widened















    @staticmethod
    def _closes_a_loop_impl(document: dict[str, Any]) -> bool:
        """Whether any grader in this document routes `revise` somewhere.

        Read off the compiled plan, not off the raw edges: `conditional` is
        where a grader's `revise` destination becomes a fact, and asking the
        compiler means this answer cannot disagree with what the graph does. A
        document that will not plan is not a loop question — it has a louder
        problem of its own.
        """
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        try:
            plan = WorkflowCompiler().plan(document)
        except Exception:
            return False
        return any("revise" in branches for branches in plan.conditional.values())

    def _report_inherited_functions(
        self, slug: str, child_document: dict[str, Any], child_assets: PackageAssets
    ) -> None:
        """Say when a mounted child bound a function its own package does not ship.

        The merge below — `{**parent.functions, **child.functions}` — settles a
        *collision*: two packages both shipping `shout` do not cross, because
        the child's is last and therefore highest (`export-and-eject/11`, and
        it is a test). It says nothing about a name only the **parent** ships.
        `function.` is a flat namespace and the parent's registry is the base
        of the child's, so a child naming `function.parent_only` runs the
        parent's Python — and the identical document, run on its own, reports
        `UNRESOLVED_FUNCTION` and passes its input through unchanged.

        That is the "this run silently reached outside its package" condition
        `runtime_warnings()` exists for, and it was the one case of it with no
        sentence. Whether the inheritance should exist at all is a separate,
        owner-level decision (`export-and-eject/14`): skills and knowledge are
        isolated to the child a few lines below the merge, tools and functions
        are not, and nothing shipped relies on the difference. This function
        does not settle that. It settles the silence, which is worse than
        either answer to it.

        Recorded on `CAPABILITY_FAILED` rather than as a twelfth `Finding`.
        The channel already carries "a capability you wrote is not where you
        think it is" — including the built-in shadow recorded in `__init__`, which is
        the same question about the other end of the same flat
        namespace — and a new member would have to earn its way past
        `test_public_surface_ceiling`'s recorded exception for `Finding`.

        Reported on the **parent's** diagnostics, not the child's, because the
        parent is the honest owner: the leak is a property of *this mount* —
        it is found by comparing the child's document against the registry the
        child's own package produced, which only the mounting side can do —
        and that is why the sentence names the mounted slug.

        That was originally the second of two reasons, the first being that a
        child runtime's findings were never absorbed upward and a sentence
        recorded there reached nobody. `workflow-gallery` 75 made that half
        false: `CompileDiagnostics.absorb` now folds a child's findings into
        the parent's, prefixed by the mounted package. This stayed where it is
        anyway, on the reason that survives — recording it on the child would
        attribute a mounting workflow's leak to the package that was leaked
        into, and would say it once for a package mounted three times when it
        is three separate mounts each reaching outside.

        Silent in the two cases that are not leaks: a child that ships the
        name binds its own, and a built-in (`function.format_report`) is in
        neither registry, so nobody's package was reached past.
        """
        parent_functions = self.services.functions
        if not parent_functions:
            return
        for node in child_document.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_type = str(node.get("type") or "")
            if not node_type.startswith("function."):
                continue
            if node_type in child_assets.functions or node_type not in parent_functions:
                continue
            self.diagnostics.record(
                Finding.CAPABILITY_FAILED,
                f'Mounted workflow "{slug}" uses "{node_type}", which its own '
                "package does not ship — it bound the mounting workflow's "
                "function instead, so this step does something the child "
                "package cannot do on its own. Move the function into "
                f'"{slug}", or read that step as belonging to this document '
                "rather than to that package.",
            )


    def _guarded_upstream(self, node_id: str, plan: CompiledPlan) -> bool:
        """Whether every path into this node meets a guardrail before a producer.

        Not "is there a guardrail anywhere upstream" — that was the first
        version and it was wrong in the one case worth catching: an *inbound*
        guard is upstream of every exit in the document, so a second Output
        wired straight off the agent looked protected by a guard that had
        already run before the agent wrote a word. What matters outbound is
        whether the policy sits between the thing that **produced new text**
        and the user.

        So the walk stops at a guardrail (that path is covered) and reports
        the moment it reaches a producer without having met one. Backwards
        over *both* kinds of edge, because a guardrail's own outputs are
        conditional ones — an Output on the `blocked` wire is the most
        guarded node in the document and `plan.edges` cannot see it.
        """
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            node_type = self._types.get(current, "")
            if node_type == GUARDRAIL_TYPE:
                continue
            if current != node_id and node_type.startswith(_PRODUCES_CONTENT):
                return False
            stack.extend(src for src, dst in plan.edges if dst == current)
            stack.extend(
                src for src, dests in plan.conditional.items() if current in dests.values()
            )
        return True




__all__ = ["NodeRuntime", "PackageAssets", "RunState", "RuntimeServices", "ToolRegistry", "chinook_tool_registry", "merge_decisions"]
