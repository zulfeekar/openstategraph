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

import copy
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
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

from langgraph.constants import TAG_NOSTREAM
from langchain_core.runnables.config import ensure_config
from langgraph.errors import GraphRecursionError

from openstategraph.abc.grader import Grader, Verdict
from openstategraph.errors import StepBudgetExhausted
from openstategraph.step_budget import (
    DEFAULT_STEP_BUDGET,
    record_overruled_mount,
    mount_step_budget,
    workflow_step_budget,
)
from openstategraph.abc.orchestrator import BaseOrchestrator, orchestrator_for
from openstategraph.abc.router import Router
from openstategraph.abc.node_family import INodeFamily, NodeBuildContext, NodeCapabilities
from openstategraph.compile.graph_names import GraphNames
from openstategraph.compile.node_families import discovered_node_families
from openstategraph.compile.node_types import NodeTypeRegistry
from openstategraph.compile.run_context import (
    mount_run_context,
    prompt_context_fields,
    render_run_context,
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
from openstategraph.compile.reducers import RESET as _RESET  # noqa: F401
from openstategraph.validation import MOUNT_NODE_TYPES
from openstategraph.compile.reducers import Reducer, reducer_for  # noqa: F401
from openstategraph.compile.workflow_compiler import (
    GUARDRAIL_TYPE,
    CompiledPlan,
    failure_marker,
    step_budget_floor_for,
    unrun_query_claim,
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
from openstategraph.compile.subagents import subagent_specs
from openstategraph import injection
from openstategraph.run_identity import run_identity
from openstategraph.developer_channel import transcript_text
from openstategraph.memory import MemorySettings
from openstategraph.messages import content_text
from openstategraph.reasoning import REASONING_EFFORT_KEY, apply_reasoning_effort

# Re-exported for the same reason `context.py`'s names are: `state.py` was
# carved out of this module and every one of these was importable from here
# before the move, underscore names included, because the tests import them.
from openstategraph.compile.state import (  # noqa: F401
    RESET,
    STEP_BUDGET_FLOOR,
    RunState,
    _silent_member_note,
    _thread_question,
    _upstream_text,
    _upstream_verdict,
    _wired_skill,
    keep_latest_nonempty,
    keep_max,
    merge_decisions,
)

#: What the output node says when it reached the end with nothing to say.
#:
#: A named constant, not a literal at the one site that writes it, because a
#: *consumer* has to be able to tell this apart from a real answer: `run`
#: exited 0 for a workflow whose mount did not resolve, since "is the answer
#: empty" was being asked of a sentence saying it was (ticket 53).
#:
#: It used to end "Check the run trace to see which step returned nothing" —
#: printed directly below the line that already names the step, pointing at a
#: trace the CLI cannot open. Advice a surface cannot honour is worse than
#: none, so the honest floor is the first sentence alone.
NO_ANSWER_PRODUCED = "The workflow finished without producing an answer."

#: Node-type prefixes whose step writes text that did not exist before it ran.
#:
#: Used by the unguarded-exit check, and by nothing else, so it is stated as
#: what that question needs rather than as a general taxonomy. Inputs echo,
#: routers and graders and approvals forward, guardrails rewrite — none of
#: them invent, so none of them is what an outbound policy exists to catch.
_PRODUCES_CONTENT: tuple[str, ...] = ("agent.", "orchestrate.", "function.", "workflow.")

#: Node types whose streamed text is machinery, not the reply.
#:
#: The compiler is what knows a node's type, so it is what answers this; who
#: is entitled to *see* machinery is `api/audience.AnswerChannel`'s question
#: and stays there. Two layers, one fact each — the same split
#: `developer_channel` already makes for the suggestion fence.
#:
#: Each entry earns its place from a frame QA read on screen (ticket 25):
#:
#: - `route.classifier` streams the branch NAME it chose — `music_store`,
#:   `data_query`, `general`, arriving glued to the sentence beside it.
#: - `route.grader` streams its verdict and rubric complaint — `FAIL Include
#:   the SQL SELECT statement...` on the end of a finished answer.
#: - `input.text` writes the turn's `HumanMessage` (see `_input`), so the
#:   question rides this stream and reads as the beginning of the reply.
#: - `input.markdown` / `input.skill` are static text sources: an instruction
#:   file or a skill, addressed to a model and to nobody else.
#:
#: `agent.llm`, `orchestrate.*` and `output.formatted` are deliberately
#: absent. Their prose IS the reply being written, and watching it appear is
#: the only thing that makes a 70-second run bearable.
MACHINERY_NODE_TYPES: frozenset[str] = frozenset(
    {
        "input.text",
        "input.markdown",
        "input.skill",
        "route.classifier",
        "route.grader",
    }
)

#: `workflow_compiler.ROUTER_TYPE`, restated here rather than imported: this
#: module already spells the literal out at each call site it needs
#: (`registry.register`, `_agent`'s `conditional_upstream`), so a new use adds
#: to an existing pattern rather than a new dependency.
ROUTER_NODE_TYPE = "route.classifier"


#: LangGraph's own tag for "run this model, but keep its tokens off the
#: `messages` stream". Read from the library rather than retyped, because a
#: misspelling here is silent — the invocation simply keeps streaming.
NOSTREAM_TAG: str = TAG_NOSTREAM


def silence_tokens(model: Any) -> Any:
    """The same model, with its tokens omitted from `stream_mode="messages"`.

    `MACHINERY_NODE_TYPES` above records *which* nodes produce text nobody
    asked to read; `api/audience.AnswerChannel` then empties their frames on
    the way out. That works, and its tests are untouched — but it is a curtain
    in front of a door. The bytes are still generated, streamed across the
    subgraph boundary and folded before anything blanks them, and a developer
    audience receives every one of them.

    LangGraph publishes the door. `pregel/_messages.py` gates the whole
    forward on `TAG_NOSTREAM not in tags`, so an invocation carrying the tag
    never reaches the stream at all.

    **This does not replace the fold**, and nothing here removes it. The fold
    guards three things the tag cannot: a mounted child's nodes (whose models
    this compiler never resolved), a tool's raw payload (a `ToolMessage`, not
    a model invocation), and the hand-rolled stand-ins this codebase passes
    around, which have no `with_config` at all. Those degrade to exactly
    today's behaviour, which is why the fallback below returns the model
    untouched rather than raising.

    Tags are **merged here, by hand, because the library replaces them.**
    Measured on the installed langchain-core 1.5.3 rather than assumed:

        r.with_config(tags=["mine"]).with_config(tags=["nostream"])
        # RunnableBinding config -> {'tags': ['nostream']}

    — `mine` is gone. Reasoning effort already binds these models
    (`_apply_effort`), so the naive spelling would silently drop a caller's
    tags on exactly the nodes this touches. Existing tags are read from both
    spellings for the same reason: a `BaseChatModel` carries them on `.tags`,
    a `RunnableBinding` in `.config["tags"]`, and both shapes reach here.

    **Every probe below is inside the `try`, and that is load-bearing rather
    than defensive habit.** `chat_model.UnconfiguredProvider` stands in for a
    model this machine has no credential for, and its rule is stated as *"a
    provider is required at the moment a model is used, not at the moment one
    is built"* — which it enforces by raising from `__getattr__`. So a bare
    `getattr(model, "with_config", None)` does not return `None` there, it
    raises `MissingProviderKey` **at compile time**, turning a workflow whose
    router never runs into one that cannot be built. Caught live by
    `test_behind_the_scenes.py`, not reasoned about here first.

    Any failure therefore leaves the model exactly as it was: a model that
    cannot be tagged still streams, which is today's behaviour, and the
    sentinel goes on raising at the moment it is genuinely used, with its own
    message rather than one from here.
    """
    if model is None:
        return None
    try:
        with_config = getattr(model, "with_config", None)
        if not callable(with_config):
            return model
        bound = getattr(model, "config", None)
        existing = tuple(
            getattr(model, "tags", None)
            or (bound.get("tags") if isinstance(bound, dict) else None)
            or ()
        )
        if NOSTREAM_TAG in existing:
            return model
        return with_config(tags=[*existing, NOSTREAM_TAG])
    except Exception:  # noqa: BLE001 — a model that cannot be tagged is not an error
        logger.debug("could not tag a model %s; its tokens still stream", NOSTREAM_TAG)
        return model


#: Maps a tool node type to the Python tool that implements it.
#:
#: Injectable, because tool discovery is workflow-scoped (ticket 18) and the
#: shared catalogue must not accumulate every workflow's tools. Passing an empty
#: registry is valid: the agent simply gets no tools, which is a degraded run
#: rather than a crash.
logger = logging.getLogger(__name__)

ToolRegistry = dict[str, Any]


def chinook_tool_registry() -> ToolRegistry:
    """The Chinook workflow's tools, keyed by node type."""
    from tools.chinook import ExecuteSqlTool, GetTableSchemaTool, ListTablesTool

    return {
        "tool.chinook-get-schema": GetTableSchemaTool(),
        "tool.chinook-get-all-tables": ListTablesTool(),
        "tool.chinook-execute-sql": ExecuteSqlTool(),
    }


class _DeepAgentAsChatModel:
    """Makes a compiled deep agent look like the chat model `BaseGrader.grade()`
    expects — a bare `.invoke(messages) -> object with .content`.

    `BaseGrader` (`openstategraph/abc/grader.py`) is deliberately model-agnostic: it
    knows nothing about `create_deep_agent`, tiers, or LangChain harness
    tiers, and should not have to. So the adaptation lives here, at the
    compiler/runtime boundary, rather than teaching the grader ladder about a
    concrete agent construction — the same boundary rule CLAUDE.md states for
    cross-family concerns (a collaborator, not a shared ancestor).

    Built fresh **per grading call**, not once at compile time, because the
    system prompt — `messages[0]` — varies with the question being judged
    (`BaseGrader.resolve_system_prompt` appends it as context). Mirrors the
    worker's own fix for the identical shape of problem: `create_agent`'s
    `system_prompt=` construction parameter is the proven-working way to
    deliver a directive prompt, not a hand-assembled message list.
    """

    def __init__(self, model: Any, name: str, tags: tuple[str, ...] = ()) -> None:
        self._model = model
        self._name = name
        #: Applied to the *invocation*, never bound onto the model — see
        #: `invoke`. Empty by default; the machinery nodes pass `nostream`.
        self._tags = tuple(tags)

    def invoke(self, messages: list[Any]) -> Any:
        from openstategraph._extras import require_extra

        create_deep_agent = require_extra(
            "deepagents", "deep", "the deep-agent grader"
        ).create_deep_agent

        system_prompt = messages[0].content if messages else ""
        candidate_message = messages[-1]
        agent = create_deep_agent(
            # Deliberately the model as resolved, with nothing bound onto it.
            # `create_deep_agent` does not accept a `RunnableBinding` here: a
            # non-`BaseChatModel` is treated as a model *identifier*, and the
            # failure is `AttributeError: 'RespondingModel' object has no
            # attribute 'count'` from deep inside the string handling — a
            # sentence that names neither this call nor the binding that
            # caused it. So a tag that must reach this tier travels on the
            # invocation below instead, where LangChain propagates it down to
            # the child LLM run, which is the run `nostream` is read from.
            model=self._model,
            tools=[],
            system_prompt=system_prompt,
            name=self._name,
        )
        result = agent.invoke(
            {"messages": [candidate_message]}, config={"tags": list(self._tags)}
        )
        out = result.get("messages") or []
        text = _final_text(out)
        return SimpleNamespace(content=text if isinstance(text, str) else str(text))



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


def _final_text(messages: list[Any]) -> str:
    """What the model said this turn — or "", never something else.

    An agent loop can legitimately end on a message with empty content — a
    dangling tool call the loop cut off, or a provider blip mid-stream — and
    `out[-1].content` then records "" as the worker's entire answer (observed
    live under concurrent fan-out, ticket 61). Walking back keeps whatever the
    agent actually said.

    **Two rules, and the walk-back is only the first.** The second exists
    because the first, alone, produced the worst bug this project has had
    (the-editor-makes-a-real-package ticket 03): `POST /api/runs` answered
    `49` while `POST /api/runs/stream` answered *the question*, on the same
    workflow, seconds apart — and both shipped UIs use the streaming endpoint,
    so every run a person could see was wrong while every run a test made was
    right.

    1. **Read the text, whatever shape it arrives in.** LangChain's `content`
       is documented as "loosely-typed, supporting strings and lists of
       untyped objects", and an Anthropic `AIMessage` in particular "can
       either be a single string or a list of content blocks". Adding
       `"messages"` to `stream_mode` is enough to switch a settled message
       from `"30"` to `[{"text": "30", "type": "text", "index": 0}]`. The old
       `isinstance(content, str)` test read that as *no text at all*, so the
       guard meant to skip empty messages skipped a full one.
       `openstategraph.messages.content_text` reads both shapes and joins
       only the `text` blocks — so a thinking model's private reasoning,
       which rides in the same list, stays out of the answer. It is the one
       reader in this codebase, and its module docstring is the account of
       why: until docs-and-gaps 14 this module carried a byte-identical
       private copy of it.

    2. **Never walk past the last human turn.** This is the floor, and it is
       about what a failure is *allowed to look like*. With rule 1 broken the
       walk continued past the AI message and returned the `HumanMessage` —
       the user's own question, handed back as the answer. That is the one
       wrong answer nothing downstream can catch: a grader reads it as a
       reply, a customer reads it as a reply, and the run reports success. An
       empty answer is visibly a failure; an echo is a lie. Rule 1 is fixed,
       and rule 2 means the next thing that breaks upstream degrades loudly
       instead.
    """
    for message in reversed(messages):
        # The floor. Anything at or before the current turn's question belongs
        # to the *conversation*, not to this turn's answer.
        if getattr(message, "type", None) in ("human", "system"):
            return ""
        # A message that *requests* tool calls is never the final answer —
        # its content is preamble or echoed arguments. Observed live: a
        # degraded loop ended on a dangling call and the "answer" rendered
        # as {"path": ...} in the customer chat.
        if getattr(message, "tool_calls", None):
            continue
        # And a message that *carries a tool's result* is never the answer
        # either — the third member of the same family, and the one that got
        # through (`every-workflow-green` 32). A loop ending on a tool result
        # published it verbatim: "Error: web_fetch is not a valid tool, try one
        # of [...]" was shown to the user as the answer to their question.
        #
        # A tool result is **evidence for the model, not prose for a person**,
        # and that holds whether it succeeded or failed: a page of search hits
        # is no more an answer than an error is.
        #
        # When nothing the model said remains, "" is correct. That is a silent
        # node and `silent_node_warnings` has a sentence for it (ticket 01).
        # Publishing the nearest string instead is how a completely broken run
        # looked completely healthy — no node failed, the output was non-empty,
        # and every health channel on this map saw nothing wrong.
        if getattr(message, "type", None) == "tool":
            continue
        text = content_text(getattr(message, "content", ""))
        if text.strip():
            return text
    return ""

def tool_report(node_id: str, messages: list[Any], bound: list[str]) -> dict[str, Any]:
    """What this node was given, what it used, and what it was refused.

    The seam every tool-binding factory shares. Ticket 33 built the
    deterministic route — read the name out of **our own** refusal, look it up,
    offer the tool — and wired it into `_agent` by hand. `_worker` binds tools
    the same way and got nothing, so `morning-brief` asked for `web_fetch`, was
    refused by name, and no card appeared for a tool we ship
    (`every-workflow-green` 36). The worker's own docstring already records
    this failure once, about `advisor_context`: composed into one factory and
    not the other.

    Read from the **messages**, never from the answer: the refusal is a
    `ToolMessage` in the middle and the answer that follows it usually says
    nothing about it, which is exactly what proved unreliable in 33.

    **`ran` names the tools this node's loop actually reached — a real tool
    that was invoked and returned, whether it answered or errored — and never a
    name the runtime refused because no such tool exists.** Both halves are
    load-bearing and both have been wrong once. An error is data and the tool
    is wired (`the-agent-asks-for-what-it-cannot-get` 01), so it counts; an
    invented `execute_sql?` reached nothing at all, so it does not
    (`production-ready` 98). The filter is the refusal, never membership of
    `bound` — `bound` is *canvas-wired only*, so filtering by it would drop a
    memory or knowledge tool the agent genuinely used, and a deep agent's
    preset tools with it.

    Returns no `unmet_tools` key rather than an empty map when nothing was
    refused, so a clean run writes nothing there — a node that reports `[]` and
    a node that reports nothing must not look the same to the reducer.

    **`tool_use` is written on every run, including the empty one**, and that
    asymmetry is the point (`every-workflow-green` 35). The verdict this feeds
    has to tell a workflow whose agent had tools and used none from a workflow
    that has no tools at all — the first is offered a door and the second must
    never be, or the card appears on every turn of a writer workflow and
    becomes something people learn to skip. Absent and empty therefore mean
    different things here and both have to be sayable.

    One function rather than two calls per site, because the cost of two is on
    the record: `advisor_context` was composed into `_agent` and not `_worker`,
    so a worker refused a tool we ship and no card appeared (36). A factory
    that binds tools now says all three things or none.
    """
    from openstategraph.compile.workflow_compiler import (
        arguments_were_rejected,
        looks_like_sql_query,
        rejected_tool_names,
    )

    #: Calls whose **arguments** a real tool refused, by `tool_call_id`
    #: (`production-ready` 100). Gathered in a pass of its own because the
    #: answer arrives *after* the call that has to be judged by it, and
    #: keyed by id rather than by tool name because the rejection is per
    #: call: the model's next lap usually fixes the argument name, and that
    #: query really was sent.
    unaccepted: set[str] = set()
    for message in messages or []:
        if getattr(message, "type", None) != "tool":
            continue
        if getattr(message, "status", None) != "error":
            continue
        if not arguments_were_rejected(
            getattr(message, "content", None), getattr(message, "name", None)
        ):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if call_id:
            unaccepted.add(call_id)

    refused: list[str] = []
    ran: list[str] = []
    #: Tools a **query** was actually handed to, read off the call arguments
    #: rather than the tool's name (`production-ready` 95). A name pattern —
    #: `execute_sql`, `query`, `run_*` — is a guess about how somebody spelled
    #: their tool; the argument is the query itself, so this says what happened
    #: for a tool called `warehouse` exactly as well as for `chinook_execute_sql`.
    #:
    #: **`queried` names the tools a query was actually handed to *and whose
    #: body ran with it*.** Both halves are load-bearing. The call arguments
    #: alone are only a claim that a query was written, and two shapes have
    #: already made that claim falsely: a name the runtime refused because no
    #: such tool exists (`production-ready` 98, filtered by `ran` below), and a
    #: real bound tool whose **arguments** failed their schema, so Pydantic
    #: rejected the call before the body opened anything (`production-ready`
    #: 100, filtered by `unaccepted` above). Any `queried` anywhere clears 95's
    #: check for the **whole run**, so either one is a silent miss.
    #:
    #: A tool that ran a query and *then* errored still counts — "errored" and
    #: "never executed" are different things, and that query did leave the
    #: building.
    queried: list[str] = []
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            args = call.get("args") if isinstance(call, dict) else None
            if not isinstance(args, dict):
                continue
            if not any(looks_like_sql_query(value) for value in args.values()):
                continue
            if str(call.get("id") or "") in unaccepted:
                continue
            name = str((call.get("name") if isinstance(call, dict) else "") or "")
            if name and name not in queried:
                queried.append(name)
        names = rejected_tool_names(getattr(message, "content", None))
        for name in names:
            if name not in refused:
                refused.append(name)
        if getattr(message, "type", None) != "tool" or names:
            # A refusal arrives as a `ToolMessage` too, and counting it as a
            # use would shut the door on precisely the run that needs it. A
            # tool that ran and returned an *error* is a use, though: errors
            # are data, and the tool is wired
            # (`the-agent-asks-for-what-it-cannot-get` 01).
            continue
        used = str(getattr(message, "name", "") or "")
        if used and used not in ran:
            ran.append(used)
    # A tool the runtime refused never ran, so it never sent anything either.
    queried = [name for name in queried if name in ran]
    row: dict[str, Any] = {"bound": list(bound), "ran": ran}
    # Absent rather than empty, for the reason the docstring gives about
    # `unmet_tools`: a node that sent no query and a node with no query to send
    # must not look the same, and only presence is a claim.
    if queried:
        row["queried"] = queried
    update: dict[str, Any] = {"tool_use": {node_id: row}}
    if refused:
        update["unmet_tools"] = {node_id: refused}
    return update






#: Override keys that are refused rather than applied.
#:
#: `workflow` names the package a mount runs, so overriding it does not
#: *configure* the mount — it replaces what the mount **is**, from a data field
#: nothing surfaces. The card would go on naming the original package while the
#: run executed a different one, and `MountEditScope` already refuses shape
#: changes per instance in the editor; this closes the same door on the data
#: path. Reserved rather than blessed (owner decision, 2026-08-13): an override
#: narrows a mount, it never redirects it.
#:
#: Safe as a bare key name: `workflow` is declared by `workflow.subgraph` and
#: by no other node type, so reserving it cannot shadow an unrelated field.
RESERVED_OVERRIDE_KEYS = frozenset({"workflow"})


def _as_override_map(value: Any) -> dict[str, Any] | None:
    """One override blob as a dict, accepting both spellings, or None.

    The inspector writes a JSON *string*; a hand-authored document and the
    compiler's own recursion write a dict. Both are one contract, so both are
    parsed in one place rather than at each call site.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return value if isinstance(value, dict) else None


def _merge_override_maps(existing: Any, incoming: Any) -> tuple[Any, list[str]]:
    """Merge two override blobs, field by field, with `incoming` winning ties.

    **`overrides` is the one key this system may merge**, and the distinction
    is the whole reason this function is narrow. Every other field is opaque
    node data — a developer's prompt, a threshold, a model name — and merging
    those would mean inventing semantics for lists and nested objects the
    document never promised. `mount-overrides.md` rejected that outright, and
    it still is rejected: a plain field is replaced, exactly as before.

    But `overrides` is *ours*. Its shape is `{childNodeId: {field: value}}`,
    defined by this module, and shallow-replacing it destroys information
    nobody asked to discard: a package that pins its own grandchild's setting
    loses it the moment an ancestor overrides any *other* field of that same
    mount. That is the defect this exists to fix — silent, and the run reported
    no warning at all.

    Recursive, because a nested `overrides` may itself contain one: an edit at
    the root can address a great-grandchild, and every level down is the same
    merge with the same rule.
    """
    base = _as_override_map(existing)
    over = _as_override_map(incoming)
    if over is None:
        # An unreadable incoming blob must not delete a readable existing one.
        return (existing if base is None else base), (
            [] if incoming in (None, "", {}) else
            ["a nested overrides value is not valid JSON — the deeper override was ignored"]
        )
    if base is None:
        return over, ([] if existing in (None, "", {}) else
                      ["a nested overrides value is not valid JSON — it was replaced"])

    merged = dict(base)
    warnings: list[str] = []
    for node_id, fields in over.items():
        current = merged.get(node_id)
        if not isinstance(current, dict) or not isinstance(fields, dict):
            merged[node_id] = fields
            continue
        combined = dict(current)
        for key, value in fields.items():
            if key == "overrides":
                combined[key], notes = _merge_override_maps(current.get(key), value)
                warnings += notes
            else:
                combined[key] = value
        merged[node_id] = combined
    return merged, warnings


def apply_mount_overrides(
    child_document: dict[str, Any],
    overrides: Any,
    *,
    applied: list[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Per-mount configuration for a shared package (docs/decisions/mount-overrides.md).

    ``overrides`` is the mount node's ``data.overrides``:
    ``{"<childNodeId>": {"<fieldKey>": value}}`` — plain JSON keyed by the
    child document's own vocabulary. Applied shallowly, per field, to a COPY;
    the package on disk is the single source of truth and the compile seam
    stays one-directional. An unknown child node id warns loudly and runs on
    the package default — a typo degrading audibly beats a run that cannot
    start.

    ``applied``, when passed, is appended to in place with one
    ``(child_node_id, field_key)`` pair per field this call actually wrote —
    this is the one place that knows which write succeeded, so it is the one
    place that can say so (`launch-readiness` 40). An out-parameter rather
    than a wider return, deliberately: this function is the single owner of
    the merge (`api/mount_resolution.py`'s docstring says so) and over a dozen
    call sites destructure a 2-tuple; widening the return would touch every
    one of them for a fact only the mount-resolution call site needs.
    """
    if not overrides:
        return child_document, []
    if isinstance(overrides, str):
        # The inspector edits this field as a JSON textarea, so a saved
        # document carries the string form; both spellings are one contract.
        try:
            overrides = json.loads(overrides)
        except ValueError:
            return child_document, ["overrides is not valid JSON — the package defaults ran"]
        if not overrides:
            return child_document, []
    if not isinstance(overrides, dict):
        return child_document, [
            f"overrides must be a mapping of child node id -> fields, got {type(overrides).__name__}"
        ]

    warnings: list[str] = []
    document = copy.deepcopy(child_document)
    by_id = {n.get("id"): n for n in document.get("nodes") or []}
    for node_id, fields in overrides.items():
        target = by_id.get(node_id)
        if target is None:
            warnings.append(
                f'override targets unknown child node "{node_id}" — the package default ran'
            )
            continue
        if not isinstance(fields, dict):
            warnings.append(
                f'override for "{node_id}" must be a mapping of field -> value — ignored'
            )
            continue
        data = target.setdefault("data", {})
        for key, value in fields.items():
            if key in RESERVED_OVERRIDE_KEYS:
                warnings.append(
                    f'override for "{node_id}" tried to set "{key}" — that field '
                    "selects which workflow the mount runs, and an override may "
                    "narrow a mount, never replace it. Ignored."
                )
                continue
            if key == "overrides":
                # The one key whose shape this module owns, so the one key it
                # may merge rather than replace. See `_merge_override_maps`.
                data[key], notes = _merge_override_maps(data.get(key), value)
                warnings += notes
                if applied is not None:
                    applied.append((node_id, key))
                continue
            if value is None:
                # Applied, not skipped — `None` may be a legitimate value for a
                # nullable field and this module does not get to decide the
                # author meant something else. But it is reported, because the
                # editor never writes one: `MountContext.clearOverride` removes
                # the key instead, precisely so a "cleared" field is not an
                # override of `null` that the card keeps counting. A `null`
                # here is therefore always hand-written, and ambiguous between
                # "make it null" and "I meant to remove this".
                warnings.append(
                    f'override sets "{node_id}.{key}" to null, which overrides the '
                    "package value rather than restoring it — remove the key to "
                    "restore the default"
                )
            data[key] = value
            if applied is not None:
                applied.append((node_id, key))
    return document, warnings




def _replaces_rules(data: dict[str, Any]) -> bool:
    """`rulesMode` — the one extend/replace switch every prompted node has.

    `criteriaMode` is the grader's older spelling of the same field and is
    still read, so documents saved before the skill layer keep their behaviour
    exactly (`docs/decisions/skill-layer.md` records the generalisation and
    the condition for dropping this fallback). It is a *fallback*, never a
    second setting: `rulesMode` wins wherever both appear.
    """
    return (_text(data, "rulesMode") or _text(data, "criteriaMode")) == "replace"


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


def _summarizes(data: dict[str, Any]) -> bool:
    """Whether this agent manages its own context. **Default: yes.**

    Absent means on, which is the owner's decision of 2026-08-15 and is what
    makes the 22 shipped examples — none of which mentions the key — summarize
    at all. An explicit `false` still means off, and that is not a rounding
    error: the editor materialises every field default into `data`, so a
    document saved before the default flipped carries a literal
    `"summarize": false`. Reading absent-as-on and false-as-off keeps the
    promise `withMigratedRulesMode` states on the TypeScript side — opening a
    document must never change what it does.
    """
    value = data.get("summarize")
    return True if value is None else bool(value)


@dataclass(frozen=True)
class PackageAssets:
    """Everything one workflow package contributes to a runtime.

    The child-subgraph contract (ticket 67, completed properly after the
    user found the gap live): a routed child must run with its OWN package's
    assets — tools, functions, skills AND middleware. The first version
    loaded only tools+functions; skills stayed inherited from the parent, so
    the Architect routed through the concierge ran without its interview
    skill or document grammar and composed blind.
    """

    tools: ToolRegistry
    functions: dict[str, Any]
    skills_context: str = ""
    workflow_middleware: dict[str, Any] | None = None
    #: The package directory whose `knowledge/` powers ambient knowledge
    #: seeking (see `NodeRuntime.knowledge_package_dir`). A child gets ITS
    #: OWN package's knowledge, never the parent's — the same isolation as
    #: skills after the ticket-67 lesson.
    knowledge_dir: Any = None
    #: The package directory whose `skills/*.md` a child's agents disclose
    #: progressively. Same isolation, same reason: a routed child discloses
    #: its own package's skills or none at all.
    skills_dir: Any = None


@dataclass(frozen=True)
class RuntimeServices:
    """Everything a `NodeRuntime` collaborates with, as one named object.

    Ticket 72's parameter-object fix: the keyword constructor had grown to
    nine parameters and every new capability (store, skills, workflow
    middleware...) widened it again at two production call sites and the
    child-runtime clone. New capabilities now land HERE once; `NodeRuntime`'s
    keyword form remains as the test-facing compatibility surface.
    """

    model: Any = None
    #: Non-optional, with an empty default. `NodeRuntime` normalises `None`
    #: to `{}` on the way in, so the stored object never holds one — and
    #: while these were declared optional, every read inside the class had to
    #: be written as though it might be (reviews-2026-08-14 ticket 07).
    #: `document_loader`, `package_loader` and `memory_store` stay optional
    #: because for those, absent genuinely means something: no subgraph
    #: resolution, no memory.
    tools: ToolRegistry = field(default_factory=dict)
    functions: dict[str, Any] = field(default_factory=dict)
    document_loader: Callable[[str], dict[str, Any]] | None = None
    package_loader: Callable[[str], 'PackageAssets'] | None = None
    #: Long-term memory — LangGraph's `BaseStore`, what `compile(store=)` is
    #: given and what the prebuilt `save_memory`/`search_memory` tools write
    #: to. **Named `memory_store`, and typed, on purpose** (install-experience
    #: ticket 12): it was `store: Any`, one word from `WorkflowServices.store`
    #: (the filesystem `WorkflowStore`, packages on disk), and the statement
    #: `store = services.store` appeared verbatim in this file and in
    #: `mcp_server.py` meaning opposite objects. `Any` made swapping them a
    #: one-token edit mypy accepted, the downstream guard is a bare
    #: `is not None`, and the two classes share exactly one method name
    #: (`delete`, different arity) — so the failure surfaced at run time,
    #: inside LangGraph, naming no code of ours.
    memory_store: 'BaseStore | None' = None
    #: What the document's `settings.memory` declared (ticket 03). The
    #: default is every scope enabled, so a document with no block behaves
    #: exactly as it did before the block existed.
    memory: MemorySettings = field(default_factory=MemorySettings)
    skills_context: str = ""
    workflow_middleware: dict[str, Any] = field(default_factory=dict)
    #: The open workflow's package directory, for ambient knowledge seeking
    #: (a non-empty `knowledge/` under it auto-binds the lookup tool).
    knowledge_package_dir: Any = None
    #: The open workflow's package directory, for **progressive skill
    #: disclosure** (`launch-readiness/111`). The same value as
    #: `knowledge_package_dir` today and deliberately a separate field: that
    #: one is the second brain and carries an override
    #: (`knowledge_dir_override`) that must never redirect where skills are
    #: read from, and two capabilities sharing one field is how an override
    #: aimed at one silently moves the other.
    skills_package_dir: Any = None
    #: `load_workflow(knowledge_dir=...)`'s explicit override — the directory
    #: of topic files itself, replacing the `<package>/knowledge` convention.
    #: Deliberately NOT inherited by a child subgraph: a routed child seeks
    #: its own second brain (ticket 67's isolation lesson), and an override
    #: aimed at the parent must not silently redirect the child's.
    knowledge_dir_override: Any = None
    max_attempts: int = 3
    #: The editor-advisor tool catalogue, or "" for a normal run. See
    #: `advisor_context` — one field rather than a `bool` + the text it needs,
    #: because a flag and its data can disagree and this pair never should:
    #: an advisor with nothing to suggest is not an advisor.
    advisor_catalog: str = ""


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
        # run's entry point — see `_static_text`.
        registry.register("input.markdown", self._static_text)
        registry.register("input.skill", self._static_text)
        registry.register("agent.llm", self._agent)
        registry.register("route.classifier", self._router)
        registry.register("route.grader", self._grader)
        registry.register("human.approval", self._human_approval)
        registry.register("guard.policy", self._guardrail)
        registry.register("guard.check", self._guard_check)
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

    def _static_text(self, node_id: str, node: dict[str, Any], _plan: CompiledPlan) -> Any:
        """A node whose text **is** its configuration: a skill, an instruction file.

        Split out of `_input`, which does two jobs that turn out to be one job
        too many. `_input` seeds `state["question"] or configured` — right for
        the node that *starts* a run, and catastrophic for one that does not:
        a Skill wired to an agent's `skill` port emitted **the user's question
        as the skill**, so the instructions never reached the model at all.
        Reported live: a skill reading "when the user asks something, first
        greet HELLO ZULU then continue" had no effect, because what arrived on
        the wire was the question itself.

        Two further consequences of sharing a builder, both silent:

        - **It reset the turn.** `_input` clears `answer`, `attempts`,
          `decisions` and the fan-out channels — the turn boundary, which is
          exactly right *once*, at the entry. A document with a Skill node ran
          that reset a second time, mid-graph.
        - **It logged a second user message.** Every skill source appended its
          text to `messages` as a `HumanMessage`, putting the question into the
          conversation twice.

        None of that is configuration a developer could get wrong; it followed
        from a static source being asked to behave like an entry point. So the
        two roles are two builders, and this one holds still: no question, no
        reset, no message, just the text it was configured with.
        """
        configured = (
            _text(node.get("data") or {}, "instruction")
            or _text(node.get("data") or {}, "instructions")
            or _text(node.get("data") or {}, "content")
        )

        def run(_state: RunState) -> dict[str, Any]:
            # The author's own text, so the author's own `{{key}}` slots are
            # filled from the run's context (organisms-first-class/71). A
            # workflow declaring nothing gets its text back byte-identical.
            return {"outputs": {node_id: render_run_context(configured)}}

        return run

    def _input(self, node_id: str, node: dict[str, Any], _plan: CompiledPlan) -> Any:
        """The run's entry: the caller's question, or its configured prompt.

        Preferring the question means a saved workflow answers *this* run rather
        than replaying whatever prompt was typed when it was saved.

        Only the entry does this. A node that merely *holds* text — a skill, an
        instruction file — is `_static_text`, and the difference is not
        cosmetic: see that method for what sharing one builder cost.
        """
        configured = _text(node.get("data") or {}, "prompt")

        def run(state: RunState) -> dict[str, Any]:
            from langchain_core.messages import HumanMessage

            # `configured` is the author's text and is rendered; the
            # question is the *caller's* words and is not. A caller who typed
            # `{{tenant}}` typed a string, not a slot, and rendering it would
            # let them read a value the author never chose to show.
            text = state.get("question") or render_run_context(configured)
            # Turn boundary: wipe per-run scratch a checkpointed thread would
            # otherwise carry over (stale outputs replayed as answers, spent
            # attempts, dead decisions re-arming feedback). `messages` is
            # deliberately NOT reset — that is the conversation. A mid-run
            # resume never re-enters this node, so within-run state survives
            # approval pauses untouched.
            update: dict[str, Any] = {
                "outputs": {RESET: "", node_id: text},
                "decisions": {RESET: ""},
                "answer": RESET,
                "feedback": RESET,
                "attempts": -1,
                # The fan-out channels are per-run scratch too (audit
                # 2026-08): a second turn replans from attempts=0, so its
                # ids (`task-1`...) alias the first turn's — a turn-2 worker
                # that died before writing would let `_format_report_function`
                # silently blend turn 1's stale result in under the same key,
                # and stale plans would render phantom "failed before
                # reporting" gaps.
                "subtasks": {RESET: ""},
                "worker_results": {RESET: ""},
                # Per-grader revision budgets, same reasoning as `attempts`
                # above and the same failure if it is forgotten
                # (`workflow-gallery` 21).
                "revisions": {RESET: ""},
                # `tool_use` now accumulates across laps of one run
                # (`production-ready` 106), which makes this reset load-bearing
                # in a way it was not before: without it a second turn's first
                # lap would merge into the first turn's standing row instead of
                # starting clean, understating what changed and, worse, still
                # carrying a `queried` claim from a run that is over.
                "tool_use": {RESET: ""},
            }
            prior = state.get("messages") or []
            already_recorded = bool(
                prior
                and getattr(prior[-1], "type", "") == "human"
                and getattr(prior[-1], "content", None) == text
            )
            if text and not already_recorded:
                # The thread's record of THIS user turn — written at the one
                # node every path shares, so conversation history exists
                # whether the branch runs an agent, a supervisor, or neither
                # (ticket 73's general case, found live: "oslo" after
                # "which city?" arrived context-free at a supervisor).
                update["messages"] = [HumanMessage(content=text)]
            return update

        return run

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
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool = self._bound_tool(tool_node_id)
            if tool is None:
                continue
            try:
                lc_tools.extend(tool.as_langchain_tools(warnings=warnings))
            except Exception as exc:
                warnings.append(
                    f'Tool "{tool_node_id}" (type "{self._types.get(tool_node_id, "")}") '
                    f"could not be bound and is missing from this node's tools "
                    f"({type(exc).__name__}: {exc}) — the other tools wired to it are "
                    "unaffected, but its answer will not be grounded in that data source."
                )
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

        Deduplicated by type: `support-triage` wires three `tool.email-send`
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
            skill = _wired_skill(state, skills, self._nodes)
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
                **tool_report(node_id, result.get("messages") or [], wired),
            }

        return run

    def _router(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Classifies, and writes the branch for the conditional edge to read.

        `tier` (react/deep/custom) was declared on `RouterNode.ts` but never
        read here — found by the same field diff that caught the grader's
        equivalent gap before this file's own `_DeepAgentAsChatModel` comment
        was written. `tier: "deep"` now does exactly what it already does
        for the grader: wraps the classifying model in a compiled deep agent
        rather than teaching `BaseRouter` about one.
        """
        data = node.get("data") or {}
        branches = _branch_entries(data.get("branches"))
        base_model = self._resolve_model(data, node_id)
        # A router streams the branch NAME it chose, which QA read glued to the
        # sentence beside it. The fold blanks it for a customer; `nostream`
        # stops it being produced at all (ticket 21). Two spellings because the
        # deep tier cannot take a bound model — see `_DeepAgentAsChatModel`.
        classifying_model = silence_tokens(base_model)
        if _text(data, "tier") == "deep" and base_model is not None:
            classifying_model = _DeepAgentAsChatModel(
                base_model, name=f"router_{node_id}", tags=(NOSTREAM_TAG,)
            )
        upstream = [src for src, dst in plan.edges if dst == node_id]
        skills = plan.skill_bindings.get(node_id, [])
        # `workflow-gallery` 48: a grader downstream of this router's branches
        # may send a `revise` verdict back here rather than onto a branch
        # agent directly (`docs/decisions/router-feedback-input.md` — "feedback
        # follows the branch"). This router is the direct target, so the
        # unwidened check is right: it does not need `_feedback_sources`'
        # router-relay case, only the same direct check every feedback-trusting
        # node has always made.
        feedback_sources = self._direct_feedback_sources(node_id, plan)

        def router_for(skill: str, run_ctx: str = "") -> Router:
            """Built per skill value, for the same reason `_agent` is: the
            wired text arrives through state, not through the document.

            The branch validation `Router.__init__` performs still happens at
            compile time via the construction below, so a router with no
            branches is rejected when the graph is built, not on first run.
            """
            return Router(
                branches,
                fallback=_text(data, "fallback") or None,
                rules=_text(data, "rules"),
                skill=skill,
                replace_rules=_replaces_rules(data),
                model=classifying_model,
                match_mode=_text(data, "matchMode") or "best",
                context=run_ctx,
            )

        prebuilt = router_for("")

        def run(state: RunState) -> dict[str, Any]:
            turn = _upstream_text(state, upstream) or state.get("question", "")
            # The conversation is what the classification needs (ticket 11) —
            # and *only* the classification. What this node produced is a
            # decision about `turn`; the history it read is not its work, and
            # publishing it made every earlier turn look like this turn's
            # evidence. Ticket 24, traced in-process: a turn that ran no SQL
            # at all had a previous turn's query recovered from this field,
            # which on an `expects: "refusal"` case scores
            # `should_have_refused` for a run that never touched the database.
            # The branch downstream reads `messages` for its history anyway,
            # so it loses nothing and stops being handed the transcript twice.
            # A trusted `revise` here does not reclassify: it re-dispatches to
            # whichever branch this router's own last decision named, which is
            # the whole mechanism (`workflow-gallery` 48). Skipping
            # `router.classify()` is not merely an optimisation — a fresh
            # classification could legally choose a *different* branch than
            # the one that wrote the rejected draft (the model is not
            # deterministic), which would hand the grader's correction to a
            # desk that never saw the question. The same trust rule every
            # feedback-consuming node already applies: only a source whose
            # revise/rejected edge names this node AND whose latest decision
            # still stands.
            decisions = state.get("decisions") or {}
            replaying = any(
                decisions.get(src) in ("revise", "rejected") for src in feedback_sources
            )
            replay_branch = decisions.get(node_id) if replaying else None
            if replay_branch:
                return {
                    "decisions": {node_id: replay_branch},
                    "outputs": {node_id: turn},
                }

            classified = (
                _thread_question(state) if turn == state.get("question", "") else turn
            )
            skill = _wired_skill(state, skills, self._nodes)
            # `prebuilt` is the compile-time construction, kept for the common
            # case where nothing varies per run. A wired skill or a run-context
            # block does vary, so either one forces a rebuild.
            run_ctx = self._run_context_section()
            router = router_for(skill, run_ctx) if (skill or run_ctx) else prebuilt
            decision = router.classify(classified)
            return {
                # The conditional edge dispatches on the *stable id* — the
                # `branch:<id>` port the canvas edge actually leaves from —
                # while the model classified by human-readable *name*.
                # `route_key` is the one place that mapping lives.
                "decisions": {node_id: router.route_key(decision.branch)},
                # Every branch it matched, when it matched more than one. Only
                # written when there is something extra to say, so a document
                # that never asked for this carries no such key and takes the
                # identical path it always did.
                **(
                    {"routes": {node_id: [router.route_key(b) for b in decision.branches]}}
                    if len(decision.branches) > 1
                    else {}
                ),
                "outputs": {node_id: turn},
            }

        return run

    def _grader(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Judges, and chooses `pass` or `revise`.

        The card's `tier` field (react/deep/custom) previously did nothing on
        this side — `Grader.grade()` always made one bare chat-model call
        regardless of what a developer picked. `tier: "deep"` now actually
        builds a `create_deep_agent` for the judgement, via
        `_DeepAgentAsChatModel` rather than by teaching `BaseGrader` about
        deep agents.
        """
        data = node.get("data") or {}
        base_model = self._resolve_model(data, node_id)
        # See the router's line: a grader streams `FAIL Include the SQL SELECT
        # statement…` onto the end of a finished answer.
        grading_model = silence_tokens(base_model)
        if _text(data, "tier") == "deep" and base_model is not None:
            grading_model = _DeepAgentAsChatModel(
                base_model, name=f"grader_{node_id}", tags=(NOSTREAM_TAG,)
            )
        raw_rubric = data.get("rubric")
        rubric_rows = [
            {"criterion": str(row.get("criterion") or row.get("name") or ""),
             "required": bool(row.get("required", True))}
            for row in raw_rubric
        ] if isinstance(raw_rubric, list) else []
        cap = int(data.get("maxAttempts") or self.services.max_attempts)
        upstream = [src for src, dst in plan.edges if dst == node_id]
        skills = plan.skill_bindings.get(node_id, [])
        # Whether this grader can actually send anything back
        # (`workflow-gallery` 31). Read from the plan at build time, which is
        # the only place both the node id and the drawn destinations are known
        # — `_router_for` sees the destinations and cannot write state, and the
        # node sees the state and would otherwise not know what was drawn.
        #
        # Reported and not refused: a grader used as a recorder is a legal
        # graph, and `support-triage` ships exactly that on purpose because
        # `agent.feedback` is `maxConnections: 1` and a revise edge behind a
        # three-way classifier would have to pick one desk.
        revise_wired = "revise" in (plan.conditional.get(node_id) or {})
        if not revise_wired:
            self.diagnostics.record(Finding.UNWIRED_REVISE, node_id)
        # How few supersteps this grader may see and still stop safely — one
        # more lap, then the whole `pass` tail (`organisms-first-class` 59).
        # Read from the plan here, at build time, for the same reason
        # `revise_wired` is: the drawn destinations are known here and the
        # state is known inside `run`, and neither place knows both.
        floor = step_budget_floor_for(plan, node_id)

        def grader_for(skill: str, run_ctx: str = "") -> Grader:
            """A grader is cheap to build, so it is built per skill value.

            The skill text arrives through *state* (the port's upstream node
            writes it), so it cannot be known at compile time — the same
            reason `_agent` rebuilds. With nothing wired this is one
            construction per invocation of a plain dataclass-ish object, and
            with something wired it is the only correct order of events.
            """
            return Grader(
                criteria=_text(data, "criteria"),
                rubric=rubric_rows,
                skill=skill,
                replace_defaults=_replaces_rules(data),
                model=grading_model,
                context=run_ctx,
            )

        def run(state: RunState) -> dict[str, Any]:
            # The best candidate *this* grader has already seen, when the
            # producer has just gone quiet (`one-chinook-honest` 25).
            #
            # A revise lap can return less than the lap before it — the traced
            # run refused honestly on attempt one and returned `""` on two and
            # three — and an empty candidate at the cap would publish nothing
            # over an answer the workflow genuinely produced.
            #
            # `outputs[node_id]` is this node's own last outcome, so the text
            # kept is the one this grader judged, on the branch that reached
            # it, this turn — `_input` resets `outputs` at the turn boundary
            # with every other per-run channel.
            #
            # **Not `state["answer"]`, which is what this line used to read.**
            # That saved the traced run only by accident of shape: the
            # document has one agent, so the graph-wide answer happened to be
            # that agent's own attempt one. `_agent` already refuses the same
            # key a few hundred lines up, and names why — in a multi-agent
            # document it "may belong to somebody else". Measured, it does: a
            # chain whose *second* agent returned nothing had this grader
            # judge, force-pass and publish the **first** agent's text as the
            # second's answer, with `outputs[a2]` still empty beside it.
            previous = str((state.get("outputs") or {}).get(node_id) or "")
            candidate = _upstream_text(state, upstream) or previous
            grader = grader_for(
                _wired_skill(state, skills, self._nodes), self._run_context_section()
            )

            # A deterministic check the *grader* cannot make, because it needs
            # the run and a `BaseGrader` sees only the candidate
            # (`production-ready` 95). "The answer shows a SELECT and nothing
            # ever sent one" is a fact about `tool_use`, so it is answered here
            # and dressed as an ordinary `Verdict.reject` — which is what makes
            # it print like every other rule-based rejection, `check` and all.
            #
            # It belongs beside `deterministic_checks` in spirit and cannot
            # live there in code: putting state on `BaseGrader.grade` would
            # teach the grader ladder about `tool_use`, and a grader is a
            # judgement over a text.
            unrun = unrun_query_claim(candidate, state.get("tool_use"), upstream)
            verdict = (
                Verdict.reject(unrun, check="unrun_query")
                if unrun
                else grader.grade(candidate, question=state.get("question", ""))
            )

            # Budget check before routing: a grader that keeps rejecting must
            # still let the run finish with an honest answer rather than spin.
            #
            # Counted **per grader**, against this node's own row in
            # `revisions`, and incremented here rather than at every agent
            # (`workflow-gallery` 21). `judged` includes the candidate in hand,
            # so `maxAttempts: 1` means the first candidate is also the last —
            # which is what the graph-wide check happened to do for the single
            # -agent loop, and the shape every other graph did not get.
            judged = int((state.get("revisions") or {}).get(node_id, 0)) + 1

            # The *other* budget, and the one that used to end the run with an
            # exception rather than an answer (`organisms-first-class` 56).
            #
            # `maxAttempts` above is this grader's own lap count; the **step
            # budget** (`recursion_limit`) is the workflow's ceiling on
            # supersteps, and a lap costs one per node on the cycle — so a cap
            # the step budget cannot pay for is an ordinary drawing, not an
            # exotic one. Before this, that graph raised
            # `GraphRecursionError` and every door lost the answer the
            # workflow had already produced.
            #
            # Read off `remaining_steps`, which LangGraph populates; the docs
            # call this proactive read the recommended approach over catching
            # the error outside, because the graph completes normally. `None`
            # when a caller invoked the compiled graph without the managed key
            # in play, and then this changes nothing.
            remaining = state.get("remaining_steps")
            starved = isinstance(remaining, int) and remaining <= floor
            exhausted = judged >= cap or starved
            branch = "pass" if verdict.passed or exhausted else "revise"

            # The ceiling reports itself when it has nothing to hand on.
            #
            # Forcing `pass` at the cap is right — a loop that cannot finish is
            # worse than a mediocre answer — but when the last attempt produced
            # *nothing*, passing an empty string makes every surface downstream
            # claim success and show a blank. Found live in the editor: a
            # mounted analyst exhausted three attempts and the chat panel said
            # "No answer was produced" directly above "3 attempts before the
            # grader passed it", which is two contradictory sentences and no way
            # to act on either.
            #
            # Only when the candidate is empty. A candidate the grader merely
            # disliked is still the answer the workflow produced, and replacing
            # it with our commentary would be worse than passing it on.
            outcome = candidate
            if branch == "pass" and not candidate.strip() and not verdict.passed:
                # Which ceiling was hit changes what a reader can do about it:
                # a cap is a number on this card, the step budget is a number
                # on the workflow. Saying "after 500 attempts" for a run that
                # made four laps would be a false sentence.
                outcome = (
                    "I could not produce an answer before the workflow's step "
                    "budget ran out. The last review said: "
                    f"{verdict.feedback or 'no reason given'}"
                ) if starved else (
                    f"I could not produce an answer after {cap} "
                    f"{'attempt' if cap == 1 else 'attempts'}. "
                    f"The last review said: {verdict.feedback or 'no reason given'}"
                )

            # A pass the budget forced, not one the grader gave. `feedback`
            # is cleared on a pass, so without this the rejection is discarded
            # here and no surface can ever report it (`every-workflow-green`
            # 09). What is published does not change.
            update: dict[str, Any] = {
                "decisions": {node_id: branch},
                "revisions": {node_id: judged},
                "feedback": "" if branch == "pass" else verdict.feedback,
                "outputs": {node_id: outcome},
                # The judgement itself, beside the branch it produced. Written
                # unconditionally — unlike `forced` and `unrouted`, whose
                # presence is the signal — because a downstream reader asking
                # "what did the machine think of this text" needs an answer for
                # an ordinary pass too (`workflow-gallery` 32).
                #
                # `reason` first, `feedback` as the fallback: `Verdict` splits
                # them deliberately (the reason explains the verdict to a human,
                # the feedback is written for the agent that must retry), and a
                # deterministic rejection fills only one of the two.
                # `check` names *which* deterministic check rejected the
                # candidate, and is empty for every model judgement — which is
                # what makes the grader's two paths distinguishable downstream
                # (`production-ready` 92). `Verdict.failed_check` had named it
                # since the field was added and it was dropped here, so a
                # rejection costing 0.021 ms and one costing two seconds
                # produced byte-identical frames and ticket 84 spent a session
                # plus a live model run establishing which had happened.
                #
                # The marker travels beside the reason rather than instead of
                # it: the check name is an internal token an open set of
                # subclasses may extend (`test_grader.py`'s stricter grader
                # adds `no_figure`; this node adds `unrun_query`), so no
                # reader may map it to a sentence — the sentence is `reason`,
                # and `check` is only the fact that no model was asked.
                "verdicts": {
                    node_id: {
                        "verdict": "pass" if verdict.passed else "revise",
                        "reason": verdict.reason or verdict.feedback,
                        "check": verdict.failed_check,
                    }
                },
            }
            if branch == "pass" and not verdict.passed:
                # A budget stop is a force-pass too, and the *publication* is
                # identical — so it stays out of `forced`, whose sentence
                # names the attempts cap. Two ceilings, two sentences, one
                # channel (`workflow_compiler.step_budget_warnings`).
                if starved:
                    update["budget_stops"] = {node_id: remaining}
                else:
                    update["forced"] = {node_id: verdict.feedback or ""}
            # A verdict with nowhere to go. `_router_for` will fall back to the
            # first declared destination — correct, and it must not be the only
            # thing that happens. Only on `revise`: at the cap the branch is
            # `pass`, the answer really was published, and `forced` above is
            # already the sentence for that (gallery ticket 22's case, which is
            # a different mechanism and stays a different key).
            if branch == "revise" and not revise_wired:
                update["unrouted"] = {node_id: branch}
            return update

        return run

    def _human_approval(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Pauses the run and waits for a person, via LangGraph's own `interrupt()`.

        Same node-decides/edge-dispatches split as the router and the
        grader — this node *decides* `approved`/`rejected`, and the
        compiler's conditional edge (`workflow_compiler.py`) *dispatches* on
        whichever label it wrote to `state["decisions"]`. The difference
        from the grader is only *who* decides: a human, resumed via
        `Command(resume=...)`, instead of an LLM's own judgement.

        `interrupt()` requires the compiled graph to have a checkpointer
        (`WorkflowCompiler.build`'s `checkpointer` param) — without one,
        LangGraph raises before this ever pauses. Calling it more than once
        per node invocation is the documented anti-pattern (a resume re-runs
        the node from its own start), which is exactly why this calls it
        **exactly once**, unconditionally, rather than inside a retry loop.
        """
        # Recorded as the executor is built, so a caller one level up can ask
        # whether this document waits for anybody (`organisms-first-class` 65).
        self._holds_a_gate = True
        # The gate is the only node that can ask whether it is *below* the
        # thing it claims to authorise (`launch-readiness` 121).
        self._report_late_approval(node_id, plan)
        data = node.get("data") or {}
        message = _text(data, "message") or "Approve this result?"
        upstream = [src for src, dst in plan.edges if dst == node_id]
        # A grader reaches a gate along its `pass` branch, which is a
        # **conditional** edge and therefore absent from `plan.edges` — the
        # list above is empty for the shape this whole feature is about
        # (`workflow-gallery` 32, found by running it: the verdict was in state
        # and the lookup had nowhere to look). Static producers first, so the
        # node that actually wrote the candidate is preferred where both exist.
        producers = upstream + [
            src
            for src, branches in (plan.conditional or {}).items()
            if node_id in (branches or {}).values()
        ]

        def run(state: RunState) -> dict[str, Any]:
            from langgraph.types import interrupt

            candidate = _upstream_text(state, upstream) or state.get("answer", "")
            payload = {"message": message, "candidate": candidate}
            judgement = _upstream_verdict(state, producers)
            if judgement:
                payload.update(judgement)
            decision = interrupt(payload)

            approved = isinstance(decision, dict) and decision.get("decision") == "approve"
            feedback = ""
            if not approved:
                note = (decision or {}).get("feedback", "") if isinstance(decision, dict) else ""
                feedback = rejection_feedback(str(note))
            return {
                "decisions": {node_id: "approved" if approved else "rejected"},
                "feedback": feedback,
                "outputs": {node_id: candidate},
            }

        return run

    def _guardrail(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Applies a PII/content policy, and decides `allowed` or `blocked`.

        A **real state-transforming graph node**, not middleware and not a
        degenerate agent. Ticket 01 asked whether `PIIMiddleware`'s detection
        is separable, and it is: `RedactionRule` is public, its resolved form
        applies to a plain string, so `abc.guardrail` borrows every detector
        and every strategy from the library without importing an agent.

        ## Position is the scope, and this is where that stops being a slogan

        There is no `apply_to_input` / `apply_to_output` flag here, and there
        must never be one — the map settled that the canvas already says which
        direction an instance is, and a flag that can disagree with the wire
        is the `advisor`/`audience` defect again (`api/audience.py`). What
        makes an outbound instance behave differently is not configuration: it
        is that by the time it runs there is a settled `answer` and a
        populated `outputs` map for its policy to reach, and an inbound one
        has neither. One behaviour; the wire decides the consequence.

        ## Why it scrubs more than its own output

        `outputs` is not private state. `api/audience.py`'s table puts
        `decisions` / `outputs` on the **customer's** `done` frame — they are
        facts about their own turn — and every surface renders the map per
        node. So an outbound guard that rewrote only its own text would hand
        a customer a clean answer beside `outputs["agent-sql"]` carrying the
        59 real addresses `SELECT Email FROM Customer` returned. Scrubbing
        every entry it can see is not spooky action: it is this node doing
        exactly what its card says, at the confluence, which is the same
        argument `_output`'s never-blank floor makes.

        ## What it cannot reach, stated rather than implied

        `token` frames. The agent streams its prose while it is still typing
        and this node runs afterwards, so the live wire is already past. That
        is not a gap to paper over here — LangChain draws the identical line
        and answers the second half with `PIIMiddleware(apply_to_output=True)`,
        whose stream transformer sits *inside* the agent. Middleware on the
        agent base, never a node; see `.scratch/guardrails/map.md`.
        """
        from openstategraph.abc.guardrail import Guardrail

        data = node.get("data") or {}
        raw_policy = data.get("policy")
        policy = [row for row in raw_policy if isinstance(row, dict)] if isinstance(
            raw_policy, list
        ) else []
        guardrail = Guardrail(rules=policy, refusal=_text(data, "blockedMessage"))
        # Compile time, not run time (guardrails ticket 05). A `detector` is
        # the one regex a developer writes, and until this line nothing looked
        # at it until `screen()` did — so a missing `)` was an exception in the
        # middle of somebody's run rather than a sentence beside the card that
        # caused it. `problems()` parses the patterns and reads the strategies;
        # it compiles nothing of LangChain's and matches nothing, so a document
        # pays a parse per row for the whole class of "this row is not the
        # protection it looks like".
        for entity, problem in guardrail.problems():
            self.diagnostics.record(
                Finding.INVALID_GUARDRAIL_RULE, node_id, entity, problem
            )
        upstream = [src for src, dst in plan.edges if dst == node_id]
        # A guard placed after another guard, a grader or an approval arrives
        # over a *conditional* edge, which `plan.edges` does not carry — the
        # same situation `_output` and `_subgraph` already handle.
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]
        #: The nodes whose `outputs` entry this guard may rewrite — see the
        #: scrub below. Resolved once, at build time, because the document's
        #: types do not change during a run.
        producers = {
            candidate
            for candidate, node_type in self._types.items()
            if node_type.startswith(_PRODUCES_CONTENT)
        }

        def run(state: RunState) -> dict[str, Any]:
            text = _upstream_text(state, upstream + conditional_upstream) or state.get(
                "question", ""
            )
            try:
                screening = guardrail.screen(text)
            except ValueError as exc:
                # A table naming a strategy nobody implements, or a custom
                # entity with no pattern. Reported as this node's output
                # rather than raised: a card that claims a protection it
                # cannot deliver must be loud (`errors.py`), and taking the
                # whole run down would be a denial of service written by a
                # typo. It is deliberately NOT passed through — a guardrail
                # that fails open is the one failure mode worse than noisy.
                return {
                    "decisions": {node_id: "blocked"},
                    "outputs": {node_id: failure_marker(node_id, str(exc))},
                }

            update: dict[str, Any] = {
                "decisions": {node_id: "blocked" if screening.blocked else "allowed"},
                "outputs": {node_id: screening.text},
            }
            if screening.redactions:
                update["redactions"] = {
                    node_id: [
                        {"entity": r.entity, "strategy": r.strategy, "count": r.count}
                        for r in screening.redactions
                    ]
                }
            if not screening.changed:
                return update

            # A block scrubs exactly as a redaction does, and that was found
            # by a test rather than reasoned about: stopping at "the offending
            # text does not continue" left `outputs["in1"]` — the input node's
            # own echo — carrying the card number onto the customer's `done`
            # frame. Harmless when the customer typed it and a disclosure the
            # moment the blocked text is the *model's* answer, which is the
            # outbound instance of this very node. One rule, both outcomes.

            # What is already settled, brought into line with the policy.
            # Only the entries it actually changes are written, so a guard
            # finding nothing costs one key.
            #
            # **How far the scrub reaches depends on the verdict, and the
            # scope was found by a live run rather than reasoned about.**
            # Scrubbing every entry made an outbound guard rewrite
            # `outputs["in1"]` — the echo of the user's own question — to
            # `[REDACTED_EMAIL]`, in a document whose inbound card says
            # `email → pass`. That protects nobody (ticket 02's asymmetry:
            # inbound PII is the user's own, they typed it) and it destroys
            # the evidence that the machine ever received the true address,
            # which is the whole thing this design is for.
            #
            # So a transforming rule covers what was **produced** — an input
            # echoes, a router forwards, a guard rewrites; none of them
            # invent, and none is what an outbound policy exists to catch.
            # A **block** covers everything, because the two say different
            # things: `redact` means the reader must not see it, and `block`
            # means this workflow must not hold it at all — including in a
            # checkpointed trace that outlives the run.
            reach = (state.get("outputs") or {}).items()
            scrubbed = {
                key: screened
                for key, value in reach
                if (screening.blocked or key in producers)
                and isinstance(value, str)
                and (screened := guardrail.screen(value).text) != value
            }
            if scrubbed:
                update["outputs"] = {**scrubbed, **update["outputs"]}
            # Written **only** when there is already an answer to correct.
            # `answer` is `keep_latest_nonempty`, so writing it unconditionally
            # would make an inbound guard announce the user's own question as
            # the run's answer on any path where the agent produced nothing.
            settled = str(state.get("answer") or "")
            if settled:
                corrected = guardrail.screen(settled).text
                if corrected != settled:
                    update["answer"] = corrected
            return update

        return run

    def _orchestrator(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Splits its instruction into subtasks and writes the plan to state.

        Does **not** dispatch. Dispatch is the compiler's `_fan_out_router`,
        reading exactly what this writes — the same node-decides /
        edge-dispatches split as the router and the grader.
        """
        from openstategraph.abc.orchestrator import (
            Archetype,
            archetype_key,
            default_worker_node,
        )

        data = node.get("data") or {}
        cap = int(data.get("maxSubtasks") or 8)
        # The model makes up to two calls: the plan itself, where the card
        # carries rules (ticket 15), and archetype labelling where more than
        # one worker is wired (ticket 37's hybrid routing). A rule-less card
        # with one archetype still makes neither, which is what keeps the
        # deterministic path free.
        supervisor_model = self._resolve_model(data, node_id)

        def planner_for(skill: str, run_ctx: str = "") -> BaseOrchestrator:
            return orchestrator_for(
                max_subtasks=cap,
                # `"rules"`, not `"instruction"`. `instruction` is this node's
                # input *port* id (`src/nodes/orchestrate/OrchestratorNode.ts`),
                # and a port id is not a data key — no card, inspector or
                # document could write it, so this argument was `""` for every
                # supervisor ever built and a developer had no way to shape
                # dispatch at all. `backend/tests/test_data_key_contract.py` is
                # the general guard that now makes the whole class of this
                # mistake fail a test.
                rules=_text(data, "rules"),
                skill=skill,
                replace_rules=_replaces_rules(data),
                model=supervisor_model,
                context=run_ctx,
            )

        # The wired worker archetypes, in edge order — the same roster the
        # compiler's dispatch map is built from, keyed by the same
        # `archetype_key`, so a label the planning prompt offered is exactly
        # a key the fan-out router can resolve.
        archetypes = []
        worker_nodes = [
            {**(self._nodes.get(worker_id) or {}), "id": worker_id}
            for worker_id in plan.fan_out.get(node_id, [])
        ]
        # Which archetype an unlabelled subtask actually reaches, resolved by
        # the same function the compiler's fan-out router uses, so the record
        # this node writes (ticket 17) cannot disagree with the dispatch.
        default_key = archetype_key(default_worker_node(worker_nodes) or {})
        for worker_node in worker_nodes:
            worker_id = str(worker_node.get("id") or "")
            worker_data = worker_node.get("data") or {}
            # A labelling model can only route what it can see: with no
            # `role` set, describe the worker by the tools actually bound to
            # it — observed live (ticket 61): four undescribed archetypes had
            # GDP routed to Wikipedia and weather to a tool-less worker.
            role = _text(worker_data, "role")
            if not role:
                described = []
                for tool_node_id in plan.tool_bindings.get(worker_id, []):
                    tool_type = str((self._nodes.get(tool_node_id) or {}).get("type", ""))
                    tool = self.services.tools.get(tool_type)
                    described.append(
                        getattr(tool, "description", None) or tool_type or tool_node_id
                    )
                role = "handles: " + "; ".join(described) if described else ""
            archetypes.append(
                Archetype(
                    key=archetype_key(worker_node),
                    name=str(worker_node.get("title") or "").strip() or worker_id,
                    description=role,
                )
            )
        upstream = [src for src, dst in plan.edges if dst == node_id]
        # Same feedback-trust rule as `_agent` (audit 2026-08): `feedback` is
        # `keep_latest_nonempty`, so a later pass's "" can never clear it.
        # Only feedback whose deciding node's revise/rejected edge targets
        # THIS orchestrator — and whose latest decision is still that label —
        # may be folded into a replan; anything else is a stale rejection (or
        # another branch's) dispatched into every subtask as if it were live.
        feedback_sources = self._feedback_sources(node_id, plan)
        skills = plan.skill_bindings.get(node_id, [])

        def run(state: RunState) -> dict[str, Any]:
            instruction = _upstream_text(state, upstream) or state.get("question", "")
            if instruction == state.get("question", ""):
                instruction = _thread_question(state)
            decisions = state.get("decisions") or {}
            feedback = state.get("feedback", "")
            if not any(
                decisions.get(src) in ("revise", "rejected") for src in feedback_sources
            ):
                feedback = ""
            generation = state.get("attempts", 0)
            skill = _wired_skill(state, skills, self._nodes)
            # Rebuilt per run rather than once at compile time: the wired skill
            # text can vary by run, and `notes` below is a per-run sink that
            # must not be shared between two concurrent runs of one graph.
            planner = planner_for(skill, self._run_context_section())
            notes: list[str] = []
            subtasks = planner.plan(
                instruction,
                generation=generation,
                archetypes=archetypes,
                # Into the plan, not appended after it (ticket 23). A
                # deterministic splitter ignores it and behaves exactly as it
                # always has; a model-driven one can come back with a
                # different division of labour, which is the only thing that
                # makes this port's name true.
                feedback=feedback,
                notes=notes,
            )
            if feedback:
                # Refines every subtask the *original* instruction split
                # into — it does not add one of its own.
                #
                # Found live: an earlier version appended feedback as a new
                # semicolon-delimited clause to the instruction *before*
                # splitting, reasoning that `Orchestrator.split()` is
                # deterministic and needs a structural separator to
                # "incorporate" anything. That reasoning was backwards — a
                # semicolon there does not revise a subtask, it hands the
                # deterministic splitter one MORE clause to split on, so the
                # grader's own rejection text became its own independent
                # `Subtask` and got dispatched to a worker as if it were a
                # fresh user question. On a single-subtask instruction ("who
                # is the best artist of all time?") this produced two
                # workers answering two unrelated things — one the real
                # question, one literally the feedback sentence — joined
                # into one self-contradictory report. Appending to each
                # subtask's own instruction *after* splitting keeps the
                # subtask count exactly what the split of the real
                # instruction implies, with the "why it was rejected"
                # context carried into the retry rather than dispatched as
                # a task of its own.
                subtasks = [
                    t.model_copy(
                        update={
                            "instruction": f"{t.instruction}\n\nYour previous attempt was rejected: {feedback}"
                        }
                    )
                    for t in subtasks
                ]
            # Which archetype each subtask was dispatched to (ticket 17). A
            # run of a two-archetype supervisor — a node whose entire
            # behaviour is a *choice* — used to return `decisions: {}`, so the
            # one thing it decided was the one thing nowhere in the result.
            #
            # `<node id>#<task id>`, flat and string-valued, because that is
            # what `decisions` is at the run/stream seam (`dict[str, str]`, in
            # Pydantic and in `RuntimeClient.ts`): a nested map here would be
            # a contract change on both. `#` and not `/` — a `/` in one of
            # these maps already means a *mount path* (`RunResult.nested`),
            # and one separator cannot mean two things.
            #
            # An unlabelled subtask records the archetype it actually reached
            # *and* says it got there by default, so the case ticket 17 calls
            # unobservable — a label the model invented, validated away, and
            # collapsed onto the default worker — reads differently from a
            # label the model chose.
            dispatch = {
                f"{node_id}#{task.id}": task.archetype
                or (f"{default_key} (default)" if default_key else "(default)")
                for task in subtasks
            }
            planned = f"Planned {len(subtasks)} subtask(s)."
            return {
                "subtasks": {node_id: [t.model_dump() for t in subtasks]},
                "decisions": dispatch,
                # The ceiling's casualties ride the node's own output because
                # that is the run-time channel every surface already renders:
                # `.warnings` is materialised at load time on the library path
                # (`loader.load_workflow`), so nothing a *run* discovers can
                # reach it without a new state key. Silence was the bug.
                "outputs": {node_id: " ".join([planned, *notes])},
                "attempts": generation + 1,
            }

        return run

    def _worker(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """One dispatched instance of the static worker node.

        Every `Send` targets this same node id, so this factory runs **once**
        at compile time and the closure it returns runs **once per dispatched
        task** — the tools it binds are shared by every instance, which is
        correct: they are the worker archetype's capabilities, not a
        per-instance choice.

        Reads only `task_id` / `task_instruction` from state, because a `Send`
        payload does not inherit the parent's other state keys (verified
        against the installed langgraph — see `_fan_out_router`). If a worker
        needed the original question too, the orchestrator would have to pack
        it into every subtask's instruction explicitly; there is no other way
        for it to arrive.

        **Ships a default system prompt, unlike a bare tool-bound agent.**
        Found live: a worker given SQL tools but no instruction to use them
        answered a Chinook question from general knowledge about the
        entertainment industry rather than querying the database — the tools
        were resolved and available, the model simply had no reason to reach
        for them over its own training data. `_agent` has the same exposure
        whenever no skill is wired to it, so a worker needs a floor. The
        directive is the `default_rules` layer: a wired skill is added to it,
        and only `rulesMode: "replace"` drops it.

        **The prompt is passed as `create_agent(system_prompt=...)`, not
        prepended as a message.** The first version of this fix kept the
        prompt text but delivered it as a `SystemMessage` stitched into the
        per-invocation `messages` list, on an agent built once with no
        `system_prompt` at all — unlike `workflows/chinook-assistant/agents.py`'s
        `build_sql_agent`, the one place this exact directive style was
        already proven to work, which passes its prompt as `create_agent`'s
        own `system_prompt` parameter. Matching that shape (agent built fresh
        per invocation, since the skill text can vary by run) rather than
        approximating it with a hand-assembled message list removes a
        variable between the working case and this one.
        """
        from langchain_core.messages import HumanMessage

        lc_tools = self._bind_tools(node_id, plan)
        #: Canvas-wired only, snapshotted before the ambient tools below — see
        #: the identical line in `_agent` for why the finished list would have
        #: made almost every workflow look tool-bearing.
        wired = [t.name for t in lc_tools]

        # Workers are agents too: the ambient knowledge rule applies (deduped
        # against an explicitly wired atom, same as `_agent`).
        self._attach_ambient_knowledge(lc_tools)

        skills = plan.skill_bindings.get(node_id, [])
        # The worker is an agent too: its card carries the same `model` select
        # as every model-driven node, and `_resolve_model`'s docstring records
        # exactly this class of bug — a visible per-node choice silently
        # ignored for the graph-wide default (audit 2026-08).
        data = node.get("data") or {}
        # Same statement about a worker as about an agent (ticket 89); a
        # worker writes its prose in `role`.
        self._report_stale_tool_denial(node_id, data, wired)
        model = self._resolve_model(data, node_id)
        # **The `role` field reaches the worker itself** (ticket 16). It used
        # to reach exactly one place — `_orchestrator`, which packs it into
        # `Archetype.description` for the *supervisor's* labelling call — so
        # it described the worker to the router and said nothing to the
        # worker. A card reading "at most three short bullet points, no
        # headings" returned a ten-row Markdown table, live, and nothing was
        # wrong: the text was never sent. With a single archetype wired,
        # `label()` returns early and the field was inert entirely.
        #
        # **Context, not rules.** It is what this worker *is* — the same
        # sentence the roster shows the supervisor — so it sits above the
        # rules layers and outside what `rulesMode: replace` can delete. A
        # wired skill still customises behaviour and still wins ties; the
        # worker's identity is not something a skill should have to restate.
        role = _text(data, "role")
        # Directive, not a nudge. A weaker version of this ("use tools if
        # available") was tried live first and the model answered a database
        # question from general industry knowledge anyway — a vague
        # instruction competes with a large model's confident training-data
        # recall and loses. Naming the tools and the exact sequence, the way
        # the proven-reliable Chinook skill text does, is what actually
        # changes the behaviour; a preference stated in the abstract does not.
        default_prompt = (
            "You have tools that give you the REAL, current answer — you do "
            "not have this information memorised, and any figure you recall "
            "without calling a tool is almost certainly wrong for this "
            "specific dataset. Always work in this order:\n"
            "1. Call the list-tables tool to see what exists.\n"
            "2. Call the schema tool on the tables you need.\n"
            "3. Call the SQL tool with a single query that answers the question.\n"
            "Only after that sequence, answer using the numbers the tools "
            "returned. Do not answer from general knowledge, and do not "
            "invent a table or column name the schema tool did not show you."
            if lc_tools
            else ""
        )

        # **`async def`, second of Phase D** (`async-first/06`), and the family
        # where the abandoned-work bill is largest: a `Send` fan-out dispatches
        # N copies of this one node, so a stop mid-fan-out abandons N model
        # calls rather than one. That is the ~75 s in `_stream_run`'s
        # `GeneratorExit` handler — seconds of model work billed after the run
        # was stopped, per `async-first/09`'s relabelling, never latency a user
        # waits through. The same reasoning as `_agent`'s: on this version of
        # LangGraph only an `async def` body can be cancelled at all.
        async def run(state: RunState) -> dict[str, Any]:
            task_id = state.get("task_id", "")
            instruction = state.get("task_instruction", "")

            if model is None:
                # `worker_results` stays empty — it is the join's input, and a
                # sentence about our configuration published there would reach
                # `format_report` as if it were the subtask's answer. The
                # record of the step goes in `outputs`, where every surface
                # already reads it, carrying the marker that tells the silent
                # channel *which* kind of nothing this is. Before this the
                # branch wrote no `outputs` entry at all, so the step was
                # invisible everywhere (`workflow-gallery` 18).
                from openstategraph.compile.workflow_compiler import NO_MODEL_MARKER

                return {
                    "worker_results": {task_id: ""},
                    "outputs": {f"{node_id}#{task_id}": NO_MODEL_MARKER},
                }

            # Same ladder as `_agent`: the family owns construction, this
            # factory owns state plumbing. The workflow's skills text is
            # generated *context*, and SystemPrompt owns the ordering (context
            # above rules, contract last) — concatenating it into `rules`
            # bypassed that composition (audit 2026-08).
            #
            # The tool directive is the **default_rules** layer and the wired
            # file is the **skill** layer, exactly as
            # `docs/decisions/skill-layer.md` names them — that document cites
            # this worker's directive as the archetypal `default_rules`, and
            # cites extending it as the safe direction, because the directive
            # is what stopped a worker answering a database question from
            # parametric memory. This used to be `wired or default`, i.e.
            # `replace` hardcoded: a skill silently deleted the directive, and
            # `rulesMode` was the one prompted node's switch that reached
            # nothing (ticket 05).
            from openstategraph.abc import agent as agent_family

            agent = agent_family.ReactAgentNode(
                name=f"worker_{node_id}",
                model=model,
                tools=lc_tools,
                default_rules=default_prompt,
                skill=_wired_skill(state, skills, self._nodes),
                replace_rules=_replaces_rules(data),
                context="\n\n".join(
                    part
                    for part in (
                        f"Your role on this team:\n{role}" if role else "",
                        # Ambient, package-wide `skills/*.md`: house style for
                        # every model-driven node here, not a choice about
                        # this one. Context, and it stays context.
                        self.services.skills_context,
                        # And what it holds (production-ready 88). Composed
                        # here as well as in `_agent` for the reason the block
                        # below already records about `advisor_context`: a
                        # sentence that exists in one factory and not the other
                        # is a worker deserving less for no reason anybody
                        # chose.
                        held_tools_context(lc_tools),
                        # The same way out of a capability gap `_agent` has
                        # had all along, and the reason this was added
                        # (`every-workflow-green` 19): a worker with no tools
                        # wired had no way to say it was stuck, so it narrated
                        # instead — "Let's search.Let's actually run the
                        # search.Search." was published as the report on
                        # `archetype-orchestrator-report`, which wires no tool
                        # nodes at all.
                        #
                        # An agent in the identical position already answers
                        # "I don't have a tool that can do that" and emits one
                        # suggestion the editor turns into an Add & re-run
                        # card. Nothing about a worker made it deserve less;
                        # `advisor_context` was simply composed into one
                        # factory and not the other. Same call, same
                        # arguments, same position — above the rules, so
                        # `SystemPrompt` still keeps the output contract last.
                        advisor_context(node_id, self.services.advisor_catalog),
                        # And what this run was started with
                        # (`organisms-first-class/72`). Composed here as well
                        # as in `_agent` for the reason the block above already
                        # records: a sentence in one factory and not the other
                        # is a worker deserving less for no reason anybody
                        # chose.
                        self._run_context_section(),
                    )
                    if part
                ),
            ).build()
            result = await agent.ainvoke({"messages": [HumanMessage(content=instruction)]})
            out = result.get("messages") or []
            text = _final_text(out)
            return {
                "worker_results": {task_id: text if isinstance(text, str) else str(text)},
                # What this worker was refused, keyed by **node** id and not by
                # task id — `suggestion_from_rejection` builds an `attachTo`
                # out of it, and a card can only be applied if it names a node
                # that is actually on the canvas. Every dispatched instance
                # shares one node id, so two subtasks refused the same tool
                # merge to one offer, which is the right number of cards
                # (ticket 36).
                **tool_report(node_id, out, wired),
                # Which worker node ran which subtask (ticket 17). Every
                # dispatched instance shares one node id, so the task id is
                # what keeps them apart — the same reason `worker_results` is
                # keyed that way. Separate from `worker_results` because that
                # map is the join's input and this is the run's record.
                "outputs": {
                    f"{node_id}#{task_id}": text if isinstance(text, str) else str(text)
                },
            }

        return run

    def _memory_segment(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """A tollbooth: what crosses is furnished, recorded and passed onward.

        A **real state-transforming graph node**, and the deterministic half of
        memory. The other half — a write the *model* decides to make — is
        `save_memory`, bound to every agent when a store is present, and the
        atom-forge interview's first redirect is what keeps the two apart. A
        node whose position on the canvas implies a guarantee the model was
        free to ignore is the drawn thing that lies.

        ## What makes it a node and not configuration

        It reads and appends a workflow-scoped Store namespace **at a drawn
        position**, which nothing else in the catalogue does. Everything about
        the ledger itself lives in `openstategraph.memory_segment`; this
        factory is state plumbing and nothing else.

        ## The store is fetched at run time, not held from compile time

        `get_store()` reads the store the compiled graph was built with, which
        is what makes one implementation work identically in a parent and in a
        mounted child — and a child resolves its *own* `workflow_slug`, so a
        mount's segments are the mount's, exactly as isolation implies.

        `self.services.memory_store` is deliberately not used: it is the parent's
        object, and reading it here would make a subgraph's tollbooth write to
        the wrong ledger in the one case nobody tests by hand.

        ## What it cannot reach, stated rather than implied

        An outbound Guardrail scrubs `outputs`; it does not reach the Store. A
        segment placed downstream of unredacted content records that content
        durably, and the redaction that happens later cannot retrieve it. This
        is the guardrail work's own "a node cannot act on what left before it
        ran", pointed the other way, and the card says so.
        """
        from openstategraph.memory_segment import MemorySegment, parse_retention

        data = node.get("data") or {}
        segment = MemorySegment(
            name=_text(data, "segment"),
            retention=parse_retention(data.get("retention")),
        )
        upstream = [src for src, dst in plan.edges if dst == node_id]
        # A tollbooth placed after a grader, an approval or a guardrail is
        # reached over a *conditional* edge, which `plan.edges` does not
        # carry — the same gap `_agent`, `_output` and `_guardrail` close.
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]

        def run(state: RunState) -> dict[str, Any]:
            from langgraph.config import get_store

            from openstategraph.memory import UNSAVED_SLUG, workflow_scope_slug

            text = _upstream_text(state, upstream + conditional_upstream) or state.get(
                "question", ""
            )
            try:
                store = get_store()
            except Exception:
                # No store configured for this run. `MemorySegment.cross`
                # owns what that means and says it in the one sentence a
                # model can act on; taking the run down instead would make a
                # missing optional backend into an outage.
                store = None
            # A ledger key, not a memory namespace, so the fallback is spelled
            # here (2026-08-16). `workflow_scope_slug()` answers None for a run
            # that does not know its workflow, and `("workflow-memory", ...)`
            # now refuses rather than bucketing such a run — but a placed
            # segment card must still record what crossed it on an unsaved
            # canvas, which is the case the editor exercises most. So this one
            # keeps the shared bucket, visibly and on purpose. It is the last
            # place a nameless run shares a key.
            slug = workflow_scope_slug() or UNSAVED_SLUG
            crossing = segment.cross(store, slug, text=text, node=node_id)
            # `outputs` only. The node introduces no state key, so there is no
            # multi-writer question to answer and no reducer to name — the
            # cheapest way to satisfy that rule is not to need it.
            return {"outputs": {node_id: crossing.text}}

        return run

    def _format_report_function(
        self, node_id: str, node: dict[str, Any], plan: CompiledPlan
    ) -> Any:
        """A deterministic **function** node — distinct from a *tool*.

        The distinction the cookbook (ticket 27) drew and this makes concrete: a
        *tool* is model-callable, chosen by an agent mid-loop; a *function* is a
        graph step the compiler always runs, with no model in the decision. This
        one has nothing to decide — it joins whatever worker results exist into
        one report, in task-id order, with no LLM call and therefore no
        variance. Determinism here is a feature: the same worker results always
        produce the same report text, which is what makes the graph-engineering
        proof below assertable byte-for-byte.
        """
        # The TS field schema (`FormatReportNode.ts`) calls this key
        # `reportTitle`, not `title` — found via a TS-schema-vs-Python-factory
        # diff, not live: a canvas-authored document could never have reached
        # this field at all, since every real document produces `reportTitle`
        # and this read silently fell through to the "Report" default every
        # time.
        title = (node.get("data") or {}).get("reportTitle") or "Report"

        def run(state: RunState) -> dict[str, Any]:
            results = state.get("worker_results") or {}
            # Scoped to ids the *current* plan(s) declared, not every id ever
            # written across every past attempt. `subtasks[orchestrator_id]` is
            # overwritten (not accumulated) on each replan, so this discards
            # stale results from a rejected attempt rather than silently
            # blending them into a report about the latest one.
            current_ids = {
                task["id"]
                for plan_list in (state.get("subtasks") or {}).values()
                for task in plan_list
            }
            scoped = {k: v for k, v in results.items() if k in current_ids}
            # No worker fan-out reached this join — so gather what its own
            # upstream nodes produced instead (`every-workflow-green` 27).
            #
            # This is the shape the `empty` message below has always described
            # and refused: "an edge into `candidate` from anything else
            # sequences this step without carrying data". It is now the shape a
            # classifier in `matchMode: "all"` produces on every compound
            # question, so refusing it would mean two desks running in parallel
            # and one of them being thrown away by `answer`'s LATEST_NONEMPTY —
            # the same silent loss the mode exists to end, moved one node
            # along.
            #
            # A fallback rather than a merge, and preferred in that order: an
            # orchestrator fan-out and a classifier fan-out do not share a join
            # in practice, and reading `worker_results` first keeps every
            # shipped report byte-identical.
            if not scoped:
                outputs = state.get("outputs") or {}
                scoped = {
                    src: str(outputs[src])
                    for src, dst in plan.edges
                    if dst == node_id and str(outputs.get(src) or "").strip()
                }
            # A task that died (retries exhausted → error handler wrote to
            # outputs, which carries no task identity) must appear as a
            # named gap, not vanish from the join (ticket 61 residual #2).
            for missing in sorted(current_ids - scoped.keys()):
                scoped[missing] = "_(this task failed before reporting a result)_" 
            body = "\n\n".join(
                # An empty member result renders as an explicit gap — a blank
                # section reads like formatting, and the grader (and the
                # human) must see the miss to act on it (ticket 61).
                f"### {task_id}\n{text or _silent_member_note(task_id, state)}"
                for task_id, text in sorted(scoped.items())
            )
            # An empty body means the *plan* was empty, not that the workers
            # were quiet: a dispatched task that died is filled in above as a
            # named gap. So the only way to get here is that nothing ever
            # dispatched to this join — the shape `docs/patterns.md` §4 warns
            # about, where agents are wired straight into `candidate` and the
            # edges sequence the join without carrying anything. Saying which
            # of the two happened is the difference between a debuggable run
            # and a shrug (production-ready ticket 31).
            empty = (
                "_No results — nothing was dispatched to this join. It reports the "
                "worker results of a supervisor's fan-out; an edge into `candidate` "
                "from anything else sequences this step without carrying data "
                "(docs/patterns.md §4)._"
            )
            report = f"# {title}\n\n{body}" if body else f"# {title}\n\n{empty}"
            return {"outputs": {node_id: report}, "answer": report}

        return run

    def _discovered_function(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """A workflow-discovered function as a deterministic graph step.

        The signature contract is `fn(text: str) -> str` — a transform of the
        node's upstream text, no model, no state access (ticket 35: code is
        referenced by name, never given the raw state to hide control flow
        in). A raised exception becomes readable output — the same
        errors-are-data rule `BaseTool.run` applies: retrying a deterministic
        function reproduces the same failure, so the useful move is to carry
        the message downstream where a grader or a person can read it.
        """
        node_type = str(node.get("type", ""))
        fn = self.services.functions.get(node_type)
        if fn is None:
            self.diagnostics.record(Finding.UNRESOLVED_FUNCTION, node_type)
            return self._passthrough(node_id, node, plan)

        upstream = [src for src, dst in plan.edges if dst == node_id]
        # A function node fed by a grader's `pass` (or a guard's `pass`, or an
        # approval's `approved`) arrives over a *conditional* edge, which
        # `plan.edges` does not carry — `_agent`, `_output`, `_guardrail` and
        # `_subgraph` already close this gap; this handler was the one left
        # open (`launch-readiness` 66). Without it, a function node placed
        # behind a routed edge silently read the turn's original question
        # instead of its wired upstream — found live, with `execute_sql`
        # reading a natural-language question where SQL should have been, and
        # nothing reporting it.
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]

        def run(state: RunState) -> dict[str, Any]:
            text = _upstream_text(state, upstream + conditional_upstream) or state.get(
                "question", ""
            )
            try:
                result = fn(text)
            except Exception as exc:
                return {"outputs": {node_id: f"[{node_id} failed: {type(exc).__name__}: {exc}]"}}
            output = result if isinstance(result, str) else str(result)
            return {"outputs": {node_id: output}, "answer": output}

        return run

    def _guard_check(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """A grader's mechanical sibling (`launch-readiness` 65).

        Answers the same `pass`/`revise` question a grader does, over the
        same conditional-edge shape (`workflow_compiler.py` routes
        `GUARD_CHECK_TYPE` exactly where it routes `GRADER_TYPE`), but by
        calling a package function instead of a model — the decision was
        already made deterministically and for free by
        e.g. `function.validate_sql`, and this node hands its verdict back
        without paying for a model call to re-emit it.

        The function contract is the same `fn(text: str) -> str` every
        `function.*` node already uses (`_discovered_function`): an empty
        return is a pass, a non-empty return is both the `revise` reason and
        the feedback text sent upstream. No new contract, no new registry —
        `check` just names one of the same functions by its short name (the
        part after `function.`).

        Termination mirrors the grader's own two ceilings exactly, because a
        guard that always emitted `revise` would violate "a cycle must
        contain a conditional edge that can end it": `maxAttempts` (this
        node's own lap budget, forcing a pass once exhausted) and the step
        budget floor (`step_budget_floor_for`, forcing a pass before the
        graph's own recursion limit would raise). A mechanical lap is cheaper
        than a model lap, so a runaway is more likely here, not less — which
        is exactly why both ceilings apply here unweakened.
        """
        data = node.get("data") or {}
        check_name = _text(data, "check").strip()
        fn = self.services.functions.get(f"function.{check_name}") if check_name else None
        upstream = [src for src, dst in plan.edges if dst == node_id]
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]
        cap = int(data.get("maxAttempts") or self.services.max_attempts)
        revise_wired = "revise" in (plan.conditional.get(node_id) or {})
        if not revise_wired:
            self.diagnostics.record(Finding.UNWIRED_REVISE, node_id)
        floor = step_budget_floor_for(plan, node_id)

        def run(state: RunState) -> dict[str, Any]:
            candidate = _upstream_text(state, upstream + conditional_upstream) or state.get(
                "question", ""
            )
            if fn is None:
                self.diagnostics.record(Finding.UNRESOLVED_FUNCTION, f"guard.check:{check_name}")
                return {
                    "decisions": {node_id: "pass"},
                    "outputs": {node_id: candidate},
                    "feedback": "",
                }

            try:
                reason = fn(candidate)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
            reason = reason.strip() if isinstance(reason, str) else str(reason or "")

            judged = int((state.get("revisions") or {}).get(node_id, 0)) + 1
            remaining = state.get("remaining_steps")
            starved = isinstance(remaining, int) and remaining <= floor
            exhausted = judged >= cap or starved
            passed = not reason
            branch = "pass" if passed or exhausted else "revise"

            return {
                "decisions": {node_id: branch},
                "revisions": {node_id: judged},
                "feedback": "" if branch == "pass" else reason,
                "outputs": {node_id: candidate},
                "verdicts": {
                    node_id: {
                        "verdict": "pass" if passed else "revise",
                        "reason": reason,
                        "check": check_name,
                    }
                },
            }

        return run

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
            answer = final.get("answer", "")
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

    def _output(self, node_id: str, _node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Collects whatever reached it as the run's answer."""
        upstream = [src for src, dst in plan.edges if dst == node_id]
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]
        # Guardrails ticket 02: the outbound guard is a node you place, and
        # what makes its absence loud is here. Only reported when the document
        # *has* a policy — see `Finding.UNGUARDED_EXIT` for why the absent
        # case is deliberately silent.
        if GUARDRAIL_TYPE in self._types.values() and not self._guarded_upstream(node_id, plan):
            self.diagnostics.record(Finding.UNGUARDED_EXIT, node_id)

        def run(state: RunState) -> dict[str, Any]:
            from langchain_core.messages import AIMessage

            text = _upstream_text(state, upstream + conditional_upstream)
            answer = text or state.get("answer", "")

            # This node is where "the run's answer" is *defined*, so it is the
            # one place that can promise the answer is never blank.
            #
            # A run that reaches here with nothing has already failed, and
            # every surface downstream — the chat panel, `RunResponse.answer`,
            # the terminal SSE frame — reports it as a success that happens to
            # say nothing. Observed live (exported trace, 2026-08-11): an
            # agent whose SQL tool had been detached refused honestly on
            # attempt one, the revise loop returned empty strings, and the run
            # delivered `answer: ""` alongside `decisions.grader-sql: "pass"`.
            #
            # The grader has its own guard for the exhaustion case and it
            # works — verified directly. This is not that guard moved or
            # duplicated: it is the floor beneath *every* route to this node,
            # including the ones with no grader in them at all (ticket 22's
            # fence-only reply reaches here the same way). A defect that can
            # arrive by several paths is fixed at the confluence, not at each
            # source.
            #
            # Deliberately not a *diagnosis*. Saying "no answer was produced"
            # is the honest floor; guessing *why* from here would invent a
            # cause this node cannot see, and a confident wrong reason is
            # worse than a plain one.
            if not answer.strip():
                answer = NO_ANSWER_PRODUCED

            # `answer`, not `text`: this node's own output IS the run's answer,
            # and the card on the canvas is fed from `outputs[node]` while the
            # chat is fed from `answer`. Publishing the raw upstream text here
            # made the two disagree in exactly the cases the fallback and the
            # floor exist for — an answer that arrived by another path (a
            # mount's, most often) or no answer at all showed a blank Answer
            # card beside a chat bubble that had one. Reported by a tester on
            # `?w=concierge`: "the end node answer remaining empty while the
            # answer is already produced."
            update: dict[str, Any] = {"answer": answer, "outputs": {node_id: answer}}
            if answer:
                # The thread record's other half (ticket 73): the answer is
                # logged where every path converges, agent or not.
                #
                # And the *only* place a turn enters the conversation, which
                # is why the developer channel is filtered out of it here
                # (ticket 27). An exported trace showed a ```suggestion fence
                # stored in `messages` and replayed into the router's prompt
                # the next turn: prompt budget spent on JSON the router cannot
                # act on, and a transcript that reads as a conversation about
                # a missing tool rather than about the user's question.
                #
                # Write-time, not read-time, and deliberately: there is one
                # writer and an open-ended set of readers (`_thread_question`,
                # an agent's payload, whatever composes context next), so a
                # read-time filter is a rule each future reader has to
                # remember — the condition that produced this ticket and 24.
                # `answer` keeps the fence, because the transport still owes
                # it to the developer channel; only the record is filtered.
                update["messages"] = [AIMessage(content=transcript_text(answer))]
            return update

        return run

    def _passthrough(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """An unknown node type forwards its input unchanged, and says so.

        Better than raising: a workflow containing one node this build does not
        know still runs and answers what it can, which is the "degrade loud,
        never silent" rule `errors.py` states for exactly this case.

        **The "loud" half was missing, and the docstring said otherwise.** It
        claimed the gap was "visible as an unchanged value" — but an unchanged
        value is what makes it invisible: the skipped node forwards its input,
        so the output node publishes the question as the answer and the run
        reports 200 with nothing amiss. Asked "what is 2+2?", a document with
        one unrecognised node answered "what is 2+2?". Found through the typo
        `agent.react` for `agent.llm`, which is the realistic way to meet it.

        A function node with no discovered callable reaches here too, and
        `_discovered_function` has already reported it in more useful terms —
        so it is not reported twice.
        """
        node_type = str(node.get("type", ""))
        # Recorded here rather than in `factory_for`, which is a pure lookup
        # that `test_data_key_contract.py` enumerates over every catalogue
        # type — a side effect there would report node types nobody wired.
        already_reported = (node_type,) in self.diagnostics.subjects(
            Finding.UNRESOLVED_FUNCTION
        )
        if node_type and not already_reported:
            self.diagnostics.record(Finding.UNKNOWN_NODE_TYPE, node_type, node_id)
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            if already_reported:
                # A function node whose callable was not discovered. It keeps
                # forwarding: `_discovered_function` has already said so in
                # better words, a second marker would report it twice, and the
                # developer channel's suggestion rides through this text.
                return {"outputs": {node_id: _upstream_text(state, upstream)}}
            return {
                "outputs": {
                    node_id: failure_marker(
                        node_id,
                        f'No runtime implements node type "{node_type}", '
                        "so this step produced nothing.",
                    )
                }
            }

        return run


__all__ = ["NodeRuntime", "PackageAssets", "RunState", "RuntimeServices", "ToolRegistry", "chinook_tool_registry", "merge_decisions"]
