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
from collections.abc import Mapping
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Literal

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

from langchain_core.runnables.config import ensure_config
from langgraph.errors import GraphRecursionError

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
from openstategraph.errors import StepBudgetExhausted
from openstategraph.step_budget import (
    DEFAULT_STEP_BUDGET,
    record_overruled_mount,
    mount_step_budget,
    workflow_step_budget,
)
from openstategraph.abc.router import Router  # noqa: F401
from openstategraph.abc.node_family import INodeFamily, NodeBuildContext, NodeCapabilities
from openstategraph.compile.graph_names import GraphNames
from openstategraph.compile.node_families import discovered_node_families
from openstategraph.compile.node_types import NodeTypeRegistry
from openstategraph.compile.run_context import (
    mount_run_context,
    prompt_context_fields,
    run_context,
    run_context_prompt_section,
    unsuppliable_context_keys,
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
from openstategraph.async_tasks import ASYNC_TASKS_KEY, ASYNC_TASKS_SLOT
from openstategraph.compile.subagents import async_subagent_specs, subagent_specs
from openstategraph import injection
from openstategraph.run_identity import run_identity
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
from openstategraph.compile.nodes import (
    approval,
    functions,
    grader,
    guard,
    io,
    memory,
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















#: The share of a model's own context window at which it summarizes. The
#: owner's number (2026-08-15); the library's own opinionated stack —
#: deepagents' — uses 0.85, so this is the more conservative of the two.
SUMMARIZE_FRACTION = 0.8

#: The absolute threshold, for every model that cannot answer the fraction.
#: `fraction` resolves against `model.profile["max_input_tokens"]`, which only
#: exists where the integration package ships profile data — and our standing
#: default provider does not: `ChatOllama(model="gpt-oss:120b-cloud").profile`
#: is `None`, verified on this machine. A fraction-only trigger would never
#: fire on the default install, which is this feature's own bug repeated one
#: layer up.
#:
#: 100,000 rather than deepagents' 170,000 fallback: that number is chosen for
#: frontier context windows, and on the models this product actually defaults
#: to the provider would refuse the call long before it was reached.
SUMMARIZE_TOKENS = 100_000


def _summarize_trigger(model: Any) -> list[Any]:
    """The OR list this model can actually be given.

    **The fraction clause is omitted when the model has no profile, and that is
    not an optimisation — it is the difference between working and raising.**
    The research for this wave read `_should_summarize`, which treats an
    unavailable profile as a clause that is simply not met, and concluded a
    plain `[("fraction", 0.8), ("tokens", N)]` was safe everywhere. It is not:
    `SummarizationMiddleware.__init__` (langchain 1.3.14) validates first and
    raises `ValueError` when any clause names `fraction` and the profile is
    absent — so the constant that was meant to close this bug would instead
    have failed the compile of every agent on the default provider.

    The intent is unchanged and the shape is the library's own: the fraction
    fires where a profile exists, the absolute fires everywhere else. Only the
    layer that enforces it moved, from evaluation to construction.

    Profile detection mirrors the library's own `_get_profile_limits` rather
    than guessing, so the two cannot disagree about what "has a profile" means.
    """
    trigger: list[Any] = []
    try:
        profile = getattr(model, "profile", None)
    except Exception:  # pragma: no cover - integrations may raise on access
        profile = None
    if isinstance(profile, Mapping) and isinstance(profile.get("max_input_tokens"), int):
        trigger.append(("fraction", SUMMARIZE_FRACTION))
    trigger.append(("tokens", SUMMARIZE_TOKENS))
    return trigger

#: How much survives. The library's own default, pinned rather than inherited:
#: what "keeps its recent tail" means is behaviour a user notices, and a
#: library default that moved would move it silently. Message-counted on
#: purpose — a `fraction` here would need the same model profile the trigger
#: cannot rely on.
SUMMARIZE_KEEP: tuple[Literal["messages"], int] = ("messages", 20)


#: What a node that discloses nothing gets: no slots filled, no store to
#: point a tier at, and `discover_skills`' flat concatenation kept. Spelled
#: here rather than imported as `DeepTierDisclosure()` because that class
#: lives beside `deepagents`, which is an optional extra — a react-tier agent
#: on an install without it must still compile, and an import for the *empty*
#: answer would take that away.
_NO_DISCLOSURE = SimpleNamespace(contributions={}, backend=None, disclosed=())





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

    def _agent(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """An agent-family loop with the tools the canvas bound to it.

        Construction is delegated to the ladder in `openstategraph.abc.agent` — the
        node's `tier` picks the class, `resolve_prompt()` is the single place
        the authored `systemPrompt` and the wired skill text become a prompt,
        and `resolve_middleware()` flattens into the library's own
        `create_agent(middleware=...)` seam. This factory keeps only the
        state plumbing: what flows in, what update flows out.

        The agent is built **per skill value**, not once at compile time,
        because the skill port's text arrives through state — the same reason
        `_worker` rebuilds per invocation. A memo keeps the common case (no
        skill wired, context never changes) at one construction total.
        """
        from openstategraph.abc import agent as agent_family
        from langchain_core.messages import HumanMessage

        lc_tools = self._bind_tools(node_id, plan)

        #: The tools **this canvas** wired to the node, snapshotted before the
        #: ambient ones are appended below. `capability_door` reads it to tell
        #: a tool-less workflow from one whose tools went untouched, and a
        #: memory store binds `save_memory` to every agent alive — so counting
        #: the finished list would have meant almost nothing was tool-less.
        #: Found in the browser: a rubric workflow that wires no tool at all
        #: drew the build card on a perfectly good answer
        #: (`every-workflow-green` 35).
        wired = [t.name for t in lc_tools]

        # A store's presence turns on the prebuilt memory tools for every
        # agent (ticket 65) — capability by configuration, no per-workflow
        # wiring, matching the minimum-viable-prebuilt rule.
        if self.services.memory_store is not None:
            from openstategraph.memory import memory_tools

            lc_tools.extend(memory_tools(self.services.memory))

        # Same rule for knowledge: a non-empty knowledge/ in this workflow's
        # package auto-binds the lookup tool. Deduped by tool name, so an
        # explicitly wired Knowledge atom plus the ambient rule is one tool,
        # never two.
        self._attach_ambient_knowledge(lc_tools)

        data = node.get("data") or {}
        # The other half of production-ready 88 (ticket 89): the run is right
        # because `held_tools_context` overrules the stale sentence, which is
        # precisely why nothing would ever prompt the author to fix it.
        self._report_stale_tool_denial(node_id, data, wired)
        model = self._resolve_model(data, node_id)
        #: Exposed so a test can assert the wiring produced the tools, without
        #: needing a model to prove it.
        self.last_bound_tools = [t.name for t in lc_tools]

        skills = plan.skill_bindings.get(node_id, [])
        upstream = [src for src, dst in plan.edges if dst == node_id]
        # An agent fed by a grader's `pass` or an approval's `approved` port
        # arrives over a *conditional* edge, which `plan.edges` does not
        # carry — the same gap `_subgraph` and `_output` already close. Found
        # live by the page-analytics dispatcher: an agent placed after
        # human.approval received the original question instead of the
        # approved report, and either fabricated figures or refused. Router
        # sources are excluded exactly as in `_subgraph`: a routed agent
        # keeps answering the user's question, not the router's rendering.
        conditional_upstream = [
            src
            for src, dests in plan.conditional.items()
            if node_id in dests.values() and self._types.get(src) != "route.classifier"
        ]
        # `feedback` is `keep_latest_nonempty`, so a grader's rejection text
        # survives in state even after the same grader later passes — the ""
        # written on pass can never clear it (that reducer exists to survive
        # two graders in one superstep). An agent must therefore not trust
        # the *presence* of feedback, only feedback whose deciding node still
        # stands by it: the ones whose revise/rejected edge targets this
        # agent AND whose latest decision is still that label. Found live:
        # the page-analytics dispatcher ran after one grader-revise lap and
        # received "Your previous answer was rejected" instead of the
        # human-approved report.
        feedback_sources = self._feedback_sources(node_id, plan)
        # Whether THIS node produced the text the rejecting node judged
        # (`organisms-first-class` 54). A `revise` edge may legally land
        # upstream of the producer — LangChain's agentic-RAG rewrites the
        # *question* — and `revision_request`'s preamble was written for the
        # evaluator-optimizer case where receiver and producer are one node.
        # Delivered to a rewriter it says "this is the answer that was
        # rejected ... revise it" about text the rewriter never wrote.
        #
        # Derived, never declared: a per-node config field would be a fifth
        # knob for a fact already in the plan, and a developer who set it
        # wrong would get this bug back. The rule is edge shape alone, so the
        # Orchestrator's `feedback` port and a human approval's `rejected`
        # edge are covered by the same sentence rather than by a name check.
        # Three roles, not two — the third was found by asking which shipped
        # packages this changes. `support-triage`'s holding-note agent sits on
        # a human approval's `rejected` edge, neither authoring the draft nor
        # feeding the gate: telling it "your last output produced this" would
        # swap one false sentence for another. So: direct producer, else a
        # node that can reach the rejector at all, else a bystander.
        def _role_towards(rejector: str) -> str:
            direct = {s for s, dst in plan.edges if dst == rejector}
            if node_id in direct:
                return "author"
            seen: set[str] = set()
            frontier = list(direct)
            while frontier:
                current = frontier.pop()
                if current in seen:
                    continue
                seen.add(current)
                frontier.extend(s for s, dst in plan.edges if dst == current)
            return "upstream" if node_id in seen else "bystander"

        rejector_roles = {src: _role_towards(src) for src in feedback_sources}
        built: dict[tuple[str, str], Any] = {}
        # `launch-readiness/106`: the `NarrationMiddleware` instance behind
        # each built agent, kept here because this is the compiler that made
        # it — exactly as `rubric` and `summarization` above are built here
        # and nowhere else. A retry reads this dict rather than the node,
        # so the node's public surface never grows for it. Keyed identically
        # to `built`; `None` where narration was silenced for this key.
        narration_by_key: dict[tuple[str, str], Any] = {}

        def agent_for(skill: str, run_ctx: str = "") -> Any:
            # Keyed by the run-context block as well as the wired skill
            # (`organisms-first-class/72`). One compiled graph serves many
            # runs, and this cache outlives all of them — keying on `skill`
            # alone would have handed the second caller the first caller's
            # tenant, which is the precise leak this ticket exists to prevent.
            key = (skill, run_ctx)
            if key not in built:
                contributions: dict[str, Any] = dict(self.services.workflow_middleware)
                # Prompt-injection screening, if this workflow asked for it and
                # the extra is installed (guardrails ticket 04). A *workflow*
                # setting rather than a field on this card: the dangerous
                # injection arrives mid-loop in a tool result, so it reaches
                # every agent or none, and a per-agent checkbox would be the
                # duplication the Guardrail node exists to abolish. Absent, the
                # run proceeds and the developer channel says so in one line —
                # refusing to run because an optional extra is missing would
                # turn a dependency gap into an outage.
                screening, screening_gap = injection.contribution(
                    requested=injection.requested(self._settings)
                )
                contributions.update(screening)
                if screening_gap is not None:
                    self.diagnostics.record(
                        Finding.CAPABILITY_FAILED, screening_gap.message
                    )
                if _text(data, "rubric").strip() and model is not None:
                    # deepagents' own LLM-as-judge (beta, >=0.6.5): a grader
                    # sub-agent inside the agent, iterating until the rubric
                    # is satisfied or max_iterations. The rubric *text* rides
                    # on invocation state (per the docs), so one middleware
                    # serves every question. This is the agent-internal atom;
                    # the Grader *node* stays the graph-level organism.
                    from openstategraph._extras import require_extra

                    RubricMiddleware = require_extra(
                        "deepagents", "deep", "an agent node with a rubric"
                    ).RubricMiddleware

                    contributions["rubric"] = RubricMiddleware(
                        model=model, max_iterations=3
                    )
                if _summarizes(data) and model is not None:
                    # LangChain's own prebuilt, never hand-rolled (ticket 66):
                    # summarizes older turns when the context bloats, keeping
                    # the recent tail verbatim.
                    #
                    # Built **here** and never on `AbstractAgentNode`, which
                    # only declares the slot. A base-filled slot would need a
                    # model at construction (`resolve_model()` may legitimately
                    # return `None`), would reach `CustomGraphNode`, which has
                    # no composition to receive — and would *downgrade*
                    # `DeepAgentNode`: `create_deep_agent` already carries a
                    # tuned `SummarizationMiddleware`, and a `middleware=`
                    # instance whose `.name` matches a built-in replaces that
                    # default in place. This is the compiler, which is the one
                    # place this node type's config becomes middleware.
                    from langchain.agents.middleware import SummarizationMiddleware

                    contributions["summarization"] = SummarizationMiddleware(
                        model=model,
                        # A *list*, and that is load-bearing: the library reads
                        # a tuple as one threshold and a list as OR across
                        # several. A tuple of tuples is accepted and means
                        # something else entirely.
                        trigger=_summarize_trigger(model),
                        keep=SUMMARIZE_KEEP,
                    )
                # `launch-readiness/106`: built here, the same way `rubric`
                # and `summarization` are — never on the node — so this
                # compiler keeps the one reference a retry needs. A workflow
                # that already named "narration" in `contributions` (the
                # declared way to silence or replace the slot) is left alone;
                # this only fills the slot when nothing already has.
                if "narration" not in contributions:
                    from openstategraph.abc.narration import build_narration_middleware

                    contributions["narration"] = build_narration_middleware()
                narration_mw = contributions.get("narration")
                tier_cls = agent_family.agent_node_for_tier(_text(data, "tier"))
                # Delegation (`organisms-first-class/84`). The pass-through has
                # existed since `DeepAgentNode` was written and nothing ever
                # filled it, so every deep agent could delegate to exactly one
                # anonymous `general-purpose` worker. Only the deep tier has a
                # parameter to reach — a declaration on any other tier is a
                # `plan.warnings` problem raised at plan time, never a silent
                # drop here, because a pass-through that appears wired and does
                # nothing is what 81 measured `skills=` doing.
                tier_kwargs: dict[str, Any] = {}
                if tier_cls is agent_family.DeepAgentNode:
                    specs = subagent_specs(data)
                    if specs:
                        tier_kwargs["subagents"] = specs
                # The other half of delegation (`async-first/08`): a row whose
                # `mode` is `async` becomes a **background worker** the agent
                # launches and collects later, not a blocking one. The slot is
                # filled here and only here, and only when a document asked for
                # it — an agent that declares none carries none of the five
                # tools, which is the narrow-interface rule taken literally.
                #
                # Built by the compiler for the same reason `rubric`,
                # `summarization` and `narration` above are: this is the one
                # place this node's config becomes middleware. The base declares
                # the slot and owns its order; it never fills it.
                async_specs = (
                    async_subagent_specs(data)
                    if tier_cls is agent_family.DeepAgentNode
                    else []
                )
                if async_specs:
                    contributions[ASYNC_TASKS_SLOT] = self._async_task_middleware(
                        node_id, async_specs, model, lc_tools
                    )
                # Progressive skill disclosure and tool-result offload
                # (`launch-readiness/111`, carrying `101` and `102`). **One
                # decision, not two**, and its default is the node's tool
                # surface rather than a setting somebody has to find: both
                # middlewares hand the model a *path*, so both are worthless —
                # worse than worthless, because the failure is a plausible
                # answer rather than an error — on an agent that cannot read a
                # file from the store this seam writes to.
                #
                # `shares_backend` is the half a name check would miss. Only
                # the deep tier's constructor takes `backend=`, so only there
                # can the harness' own `read_file`/`grep` be pointed at what
                # was written; a workflow's own tool called `read_file` reads
                # its own store and a pointer into ours means nothing to it.
                #
                # Built HERE, like `rubric` and `summarization` above and for
                # the same reason: this is the one place this node's config
                # becomes middleware. The base declares the slots and owns
                # their order; it never fills them.
                #
                # Imported inside the branch that can use it: `deepagents` is
                # an optional extra, and a react-tier agent on an install
                # without it must still compile.
                tier_is_deep = tier_cls is agent_family.DeepAgentNode
                wired_names = tuple(sorted({t.name for t in lc_tools}))
                disclosure: Any = _NO_DISCLOSURE
                if tier_is_deep:
                    from openstategraph.abc import deep_tier_offload

                    disclosure = deep_tier_offload.plan_disclosure(
                        package_dir=self.services.skills_package_dir,
                        tool_surface=(
                            wired_names + deep_tier_offload.DEEP_TIER_FILE_TOOLS
                        ),
                        shares_backend=True,
                        # Prefix-filtered, never blanket (`102`): the tools
                        # this canvas wired, and never the harness' own file
                        # tools — offloading a `read_file` result to a file
                        # and pointing at it is a loop, not a saving.
                        offload_prefixes=wired_names,
                    )
                for slot, middleware in disclosure.contributions.items():
                    # A workflow that named the slot itself keeps it, exactly
                    # as `narration` above: `middlewares/<slot>.py` is the
                    # declared way to replace a tier's slot, and a compiler
                    # that overwrote it would make that door decorative.
                    contributions.setdefault(slot, middleware)
                if disclosure.backend is not None and tier_is_deep:
                    tier_kwargs["backend"] = disclosure.backend
                # What is left to inject flat: everything the disclosure did
                # not take. Per skill, not per package — a skill the library
                # will not list (no `description` in its frontmatter, which is
                # two of the three this repository ships) must keep its body in
                # the prompt rather than disappear from it.
                skills_context = self.services.skills_context
                if disclosure.disclosed:
                    from openstategraph.api.capability_discovery import discover_skills

                    from pathlib import Path as _Path

                    skills_context = discover_skills(
                        _Path(self.services.skills_package_dir),
                        exclude=disclosure.disclosed,
                    )
                node_instance = tier_cls(
                    name=f"agent_{node_id}",
                    model=model,
                    tools=lc_tools,
                    rules=_text(data, "systemPrompt"),
                    # The wired skill is a RULES layer, above the inline
                    # `systemPrompt` and below the locked output contract
                    # (`docs/decisions/skill-layer.md`). It used to ride in
                    # `context` with the ambient package skills, which put the
                    # deliberate customisation *underneath* the prompt it was
                    # wired to customise — and later text wins ties, so the
                    # inline prompt quietly beat it every time.
                    skill=skill,
                    replace_rules=_replaces_rules(data),
                    context="\n\n".join(
                        part
                        for part in (
                            # Ambient, package-wide `skills/*.md`: house style
                            # for every agent here, not a choice about this
                            # node. Context, and it stays context.
                            #
                            # Minus whatever was disclosed above — otherwise
                            # a disclosed skill would arrive twice and the
                            # whole saving this seam exists for would be paid
                            # anyway (`launch-readiness/111`). With nothing
                            # disclosed this is exactly what it always was, so
                            # the state that needs no decision loses nothing.
                            skills_context,
                            # The branches this agent's own classifier can
                            # reach (ticket 11) — generated context, so an
                            # agent's suggestions are grounded in the graph
                            # rather than in what its prompt author guessed
                            # the graph contained.
                            branch_context(node_id, plan, self._nodes),
                            # What it *holds*, beside what could be *added*
                            # (production-ready 88). The pair has to travel
                            # together: an agent told only what it lacks, whose
                            # authored rules deny holding anything, answers
                            # "this workflow doesn't include that capability"
                            # about a tool sitting in its own schema.
                            held_tools_context(lc_tools),
                            advisor_context(node_id, self.services.advisor_catalog),
                            # What this *run* was started with, for the fields
                            # the author opted in (`organisms-first-class/72`).
                            # Generated, so it is context and never rules, and
                            # the locked output contract still renders last.
                            run_ctx,
                        )
                        if part
                    ),
                    middleware=contributions,
                    **tier_kwargs,
                )
                built[key] = node_instance.build()
                narration_by_key[key] = narration_mw
            return built[key]

        # **`async def`, and the first family to be** (`async-first/06`).
        # Not a style choice and not throughput: on the installed
        # `langgraph 1.2.10` an `async def` node body is the *only* place a
        # run can be cancelled. Measured twice by two independent routes
        # (`async-first/09`) — under `astream`, cancelling the driving task
        # leaves a `def` body running to completion in its worker thread and
        # stops an `async def` one outright; and `add_node(timeout=...)`, the
        # one construct that interrupts a node mid-flight, is rejected at
        # compile time for sync nodes. So the order of Phase D is by how long
        # a node *runs*, never by how simple it is, and this is the longest.
        #
        # Sync and async node bodies coexist — LangGraph wraps a `def` node in
        # `RunnableLambda` — so the half-migrated graph this leaves behind is
        # not a broken graph. Proven rather than assumed, in
        # `tests/test_a_half_migrated_graph_still_runs.py`, which also pins
        # that narration still reaches the wire from in here: it travels on
        # `get_stream_writer()`, which is context-local, and a migration that
        # dropped it would look exactly like `launch-readiness/110` did — a
        # blank panel, nothing in the logs, both suites green.
        async def run(state: RunState) -> dict[str, Any]:
            prompt = _upstream_text(state, upstream + conditional_upstream) or state.get(
                "question", ""
            )
            skill = _wired_skill(state, skills, self.static_sources)
            decisions = state.get("decisions") or {}
            feedback = state.get("feedback", "")
            if not any(decisions.get(src) in ("revise", "rejected") for src in feedback_sources):
                feedback = ""

            agent = (
                agent_for(skill, self._run_context_section())
                if model is not None
                else None
            )
            if agent is None:
                return {
                    "outputs": {node_id: ""},
                    "attempts": state.get("attempts", 0) + 1,
                }

            # Conversation memory (ticket 73, generalised): the thread record
            # is written centrally — the input node logs each user turn, the
            # output node logs each answer — so EVERY path accumulates
            # history, and this agent simply speaks into it. A rejection
            # becomes its own turn (the retry carries *why*); a prompt that
            # differs from the recorded turn (an upstream transform) is
            # appended; a fresh thread reduces to single-shot exactly as
            # before. Long threads are bounded by the summarize toggle.
            payload = list(state.get("messages") or [])
            if feedback:
                # The text the rejecting node actually judged, taken from the
                # sources still standing by their rejection — never from
                # `prompt`, which falls back to the question when the
                # candidate was empty, and never from `state["answer"]`, which
                # in a multi-agent document may belong to somebody else.
                standing = [
                    src
                    for src in feedback_sources
                    if decisions.get(src) in ("revise", "rejected")
                ]
                rejected = _upstream_text(state, standing)
                # The strongest claim any standing rejector supports, never
                # the weakest: one rejector this node authored for makes it
                # the author, whatever the others say. Claiming more than the
                # graph shows would be a false statement in a preamble no
                # developer can edit — which is the defect itself.
                roles = [rejector_roles[src] for src in standing]
                role = next(
                    (r for r in ("author", "upstream", "bystander") if r in roles),
                    "author",
                )
                payload.append(
                    HumanMessage(
                        content=revision_request(rejected, feedback, role=role)
                    )
                )
                # `launch-readiness/106`: a retry gets pointed at what this
                # run's own findings store already holds, not merely at what
                # was wrong. `narration_by_key` holds the exact instance this
                # compiler built for this skill/run-context key — never a
                # fresh one, and never one fetched back off the agent — so
                # the inventory reflects the store the retry's own tool calls
                # will read and write.
                retry_narration_mw = narration_by_key.get(
                    (skill, self._run_context_section())
                )
                inventory_fn = getattr(retry_narration_mw, "findings_inventory", None)
                if inventory_fn is not None:
                    thread_id = run_identity().get("thread_id", "")
                    if thread_id:
                        inventory_text = retry_inventory(inventory_fn(thread_id))
                        if inventory_text:
                            payload.append(HumanMessage(content=inventory_text))
            elif not payload or payload[-1].type != "human" or payload[-1].content != prompt:
                payload.append(HumanMessage(content=prompt))
            invocation: dict[str, Any] = {"messages": payload}
            rubric_text = _text(data, "rubric").strip()
            if rubric_text:
                invocation["rubric"] = rubric_text
            # `launch-readiness/106`: a `DeepAgentNode`'s compiled agent is a
            # bare `Runnable`, invoked here with no config and no
            # checkpointer of its own — its `StateBackend` keeps `files` in
            # *that* invocation's state only, so without this the agent's own
            # `ls`/`write_file` tools saw a blank store on every call,
            # including a retry lap of this same node in the same turn (the
            # write always landed in a dict nobody read again). `agent_files`
            # on the outer `RunState` — which the workflow's own checkpointer
            # does persist — is the store both calls actually share: seed the
            # sub-agent's `files` from what this node wrote last time, then
            # write back whatever it holds after this call.
            prior_files = (state.get("agent_files") or {}).get(node_id) or {}
            if prior_files:
                invocation["files"] = dict(prior_files)
            # The same threading for the same reason, one channel over
            # (`async-first/08`). A task id that lived only in the agent's own
            # state would be gone the moment this node returned, so the turn
            # that *collects* a background answer would have nothing to look it
            # up by — and a child that outlives the turn is the whole ticket.
            tracked_tasks = state.get(ASYNC_TASKS_KEY) or {}
            prior_tasks = (
                tracked_tasks.get(node_id) or {} if isinstance(tracked_tasks, dict) else {}
            )
            if prior_tasks:
                invocation[ASYNC_TASKS_KEY] = dict(prior_tasks)
            # `ainvoke`, and the `await` is the whole point of the migration:
            # an `async def` body that then blocked on `invoke()` would be
            # *worse* than the `def` body it replaced — it would hold the
            # event loop instead of a pool thread, and still be uncancellable.
            result = await agent.ainvoke(invocation)
            # `_final_text`, not `messages[-1]`: a loop can legitimately end on
            # a message with no content — a dangling tool call, or a provider
            # blip the retry swallowed — and the last message is then "" while
            # the answer sits one message back. `_worker` and `_ModelShim`
            # already read it this way; this node did not, which is how a
            # correct Chinook answer reached a grader as "the answer is empty"
            # and spent the whole retry budget re-asking an answered question.
            text = _final_text(result.get("messages") or [])
            answer = text if isinstance(text, str) else str(text)
            # What this agent was given, used and was refused. The extraction
            # is `tool_report` because `_worker` needs the identical thing and,
            # for one ticket, did not have it (36). `bound` and `ran` are the
            # shape `capability_door` reads when the model said nothing about
            # being blocked (`every-workflow-green` 35).
            new_files = result.get("files")
            return {
                "outputs": {node_id: answer},
                "answer": answer,
                "attempts": state.get("attempts", 0) + 1,
                **({"agent_files": {node_id: new_files}} if new_files else {}),
                **(
                    {ASYNC_TASKS_KEY: {node_id: new_tasks}}
                    if (new_tasks := result.get(ASYNC_TASKS_KEY))
                    else {}
                ),
                **tool_report(
                    node_id,
                    result.get("messages") or [],
                    wired,
                    self._unbound_capabilities.get(node_id, ()),
                ),
            }

        return run

    def _async_task_middleware(
        self,
        node_id: str,
        specs: list[dict[str, Any]],
        model: Any,
        tools: list[Any],
    ) -> Any:
        """The `async-tasks` slot for one deep agent (`async-first/08`).

        Each declared worker becomes a **launcher**: a coroutine that builds its
        own `create_agent` loop from the row's prompt and runs a conversation on
        it. The desk holds it; this method only says how to make one.

        **Isolation is structural here, not a rule anybody has to remember.** A
        launcher is handed a list of turn strings and nothing else — no parent
        state, no parent messages, no closure over either. There is no route by
        which the parent's conversation could reach a child even by accident,
        which is why `tests/test_an_async_subagent_is_isolated.py` can assert it
        on the launcher's own arguments.

        The child inherits the parent's **model and tools**, and that is a
        deliberate difference from the library, where an async subagent is a
        graph on a remote server with its own everything. Here there is no
        remote server to have anything, so the honest analogue of "its own tools
        and capabilities" is the surface this node was wired with. When the
        Agent Protocol desk lands, a row gains an optional `graphId` and this
        method stops being the one that answers the question.
        """
        from langchain.agents import create_agent

        from openstategraph.abc.async_task_middleware import AsyncTaskMiddleware
        from openstategraph.async_tasks import desk_for
        from openstategraph.run_identity import run_identity

        def launcher_for(prompt: str) -> Any:
            async def launch(turns: list[str], identity: dict[str, str]) -> str:
                child = create_agent(model=model, tools=list(tools), system_prompt=prompt)
                result = await child.ainvoke(
                    {"messages": [{"role": "user", "content": turn} for turn in turns]},
                    # The one thing that crosses. Without it a memory-scoped
                    # tool inside the child resolves `workflow_slug` and
                    # `thread_id` to nothing, and `memory.workflow_scope_slug`
                    # says a nameless run **shares a key** — so two
                    # conversations' children would write one namespace, which
                    # is the opposite of the isolation this is built around.
                    {"configurable": dict(identity)} if identity else None,
                )
                text = _final_text(result.get("messages") or [])
                return text if isinstance(text, str) else str(text)

            return launch

        launchers = {
            str(spec["name"]): launcher_for(str(spec.get("system_prompt") or ""))
            for spec in specs
        }

        def desk_factory() -> Any:
            # Keyed by workflow **and** node, resolved from the run rather than
            # from the compile: two documents in one process can both hold an
            # `agent_1`, and one agent must never be able to read another's
            # tasks. `run_identity()` answers `{}` outside a run, which keys a
            # scripted call under `":<node id>"` — deliberate, and the only
            # honest key available when nothing has said which workflow this is.
            slug = run_identity().get("workflow_slug", "")
            return desk_for(f"{slug}:{node_id}", launchers)

        return AsyncTaskMiddleware(subagents=specs, desk_factory=desk_factory)













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

    def _subgraph(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
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
            mount_checkpointer,
            mount_persistence,
        )
        from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

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
            try:
                child_document = self.services.document_loader(slug)
            except Exception:
                child_document = None
            if child_document is not None:
                # Per-mount overrides (docs/decisions/mount-overrides.md):
                # this mount's own configuration, merged onto a copy of the
                # shared package before the child compiles.
                applied_overrides: list[tuple[str, str]] = []
                child_document, mount_warnings = apply_mount_overrides(
                    child_document, data.get("overrides"), applied=applied_overrides
                )
                for warning in mount_warnings:
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
                for child_node_id, field in applied_overrides:
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
                # Recorded against the effective (post-override) child, for the
                # reason the two lines above are, and keyed by slug rather than
                # by `node_id`: this document's declaration is document-wide,
                # so three mounts of one package share one gap.
                for unsuppliable in unsuppliable_context_keys(
                    child_document, {"settings": self._settings}
                ):
                    self.diagnostics.record(
                        Finding.UNSUPPLIABLE_CONTEXT, slug, unsuppliable
                    )
                # A mount's card shows an outcome its child may have no way to
                # enforce. Keyed on *an outcome being written* rather than on
                # the node's type — since v3 there is one mount type, and what
                # makes a card a promise is the prose on it, not which card it
                # is (tickets 03 and 16). A mount with no outcome claims
                # nothing and is not warned about.
                #
                # (That sentence began "# type: since v3…", which mypy read as
                # a PEP 484 type comment and rejected as invalid syntax. Do not
                # start a comment line with `type:`.)
                #
                # Asked of the *compiler's* plan rather than by re-scanning
                # edges here: `conditional` is where a grader's `revise`
                # destination becomes a fact, so this cannot drift from what
                # the graph actually does.
                if _text(data, "outcome").strip() and not self._closes_a_loop_impl(child_document):
                    self.diagnostics.record(Finding.UNENFORCED_OUTCOME, node_id, slug)
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
                if child_owns_its_assets:
                    self._report_inherited_functions(slug, child_document, child_assets)
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
                    # A child of a mount is **sealed**: a graph compiled with no
                    # `context_schema` inherits its caller's run context whole
                    # and no argument to `invoke` can take that away, so a child
                    # that declares nothing gets an empty schema rather than
                    # none (`organisms-first-class` 76).
                    mounted=True,
                )
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
