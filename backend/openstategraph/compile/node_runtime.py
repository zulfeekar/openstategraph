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
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Annotated, Any, Callable, TypedDict


from openstategraph.abc.grader import Grader
from openstategraph.abc.orchestrator import Orchestrator
from openstategraph.abc.router import Router
from openstategraph.compile.reducers import RESET as _RESET
from openstategraph.compile.reducers import Reducer, reducer_for
from openstategraph.compile.workflow_compiler import ROUTER_TYPE, CompiledPlan
from openstategraph.developer_channel import FENCE_CLOSE, FENCE_OPEN, transcript_text
from openstategraph.memory import MemorySettings
from openstategraph.reasoning import REASONING_EFFORT_KEY, apply_reasoning_effort


#: Turn-start reset marker. A checkpointed thread carries the whole state
#: forward between runs, which is exactly right for `messages` (that IS the
#: conversation) and exactly wrong for per-run scratch: `outputs`/`answer`
#: from turn 1 leaked into turn 2's output node (a follow-up replayed the
#: previous report — found live), stale `attempts` ate graders' retry
#: budgets, and stale `decisions` could re-arm dead feedback. Reducers can
#: only ever *add*, so clearing needs a vocabulary word the reducers
#: themselves understand; the input node — the one node every turn starts
#: at, and which a mid-run resume never revisits — emits it.
# The reducers live in `compile/reducers.py` now, as a named enum — CLAUDE.md's
# portability rule, and the one of the four that was broken. Re-exported here
# because both names are read across this package and by tests
# (reviews-2026-08-14 ticket 07).
RESET = _RESET
merge_decisions = reducer_for(Reducer.MERGE)
keep_max = reducer_for(Reducer.MAX)
keep_latest_nonempty = reducer_for(Reducer.LATEST_NONEMPTY)


class RunState(TypedDict, total=False):
    """The shared state schema for a compiled workflow."""

    messages: Annotated[list[Any], reducer_for(Reducer.ADD_MESSAGES)]
    question: str
    #: node id -> branch label chosen. Read by the compiler's `path` functions.
    decisions: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: node id -> that node's textual output, so a downstream node can read it.
    outputs: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    answer: Annotated[str, reducer_for(Reducer.LATEST_NONEMPTY)]
    #: Same hazard, same fix as `answer`: this document alone has four
    #: `_grader` instances (one per intent), each writing `feedback` on
    #: every step — "" on pass, real text on revise. Found live: two
    #: graders landed in the same superstep and LangGraph raised
    #: `InvalidUpdateError: At key 'feedback': Can receive only one value
    #: per step`, with the raw error then rendered into the chat panel as
    #: if it were the model's own answer.
    feedback: Annotated[str, reducer_for(Reducer.LATEST_NONEMPTY)]
    attempts: Annotated[int, reducer_for(Reducer.MAX)]
    #: orchestrator node id -> the subtasks it planned. Read by the compiler's
    #: fan-out routing function to build the `Send` list.
    subtasks: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: task id -> that worker instance's output. Joined by whatever reads it.
    #:
    #: Deliberately **not** keyed by node id: many dynamic worker *instances*
    #: share one static worker *node*, so node id would collide every one of
    #: them onto a single key. The task id — unique per dispatched Send — is
    #: what keeps every instance's result addressable.
    worker_results: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: Set only inside a dispatched worker instance, from the Send payload.
    #: Absent everywhere else — a worker cannot see the parent's other state,
    #: only what the orchestrator explicitly packed into its Send (see below).
    task_id: str
    task_instruction: str


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

    def __init__(self, model: Any, name: str) -> None:
        self._model = model
        self._name = name

    def invoke(self, messages: list[Any]) -> Any:
        from openstategraph._extras import require_extra

        create_deep_agent = require_extra(
            "deepagents", "deep", "the deep-agent grader"
        ).create_deep_agent

        system_prompt = messages[0].content if messages else ""
        candidate_message = messages[-1]
        agent = create_deep_agent(
            model=self._model,
            tools=[],
            system_prompt=system_prompt,
            name=self._name,
        )
        result = agent.invoke({"messages": [candidate_message]})
        out = result.get("messages") or []
        text = _final_text(out)
        return SimpleNamespace(content=text if isinstance(text, str) else str(text))



def _content_text(content: Any) -> str:
    """The human-readable text of a message's content, whichever shape it is.

    LangChain documents `content` as "loosely-typed, supporting strings and
    lists of untyped objects"; an Anthropic `AIMessage` in particular "can
    either be a single string or a list of content blocks". Both shapes are
    normal and which one arrives is not the caller's choice — adding
    `"messages"` to `stream_mode` is enough to switch it.

    Only `text` blocks are joined. A thinking model puts its reasoning in the
    same list, and concatenating blindly would hand a customer the model's
    private deliberation as if it were the answer.

    Written out rather than delegating to `message.text`: that accessor is a
    property on current message classes and a deprecated *method* on others,
    so reading it generically means guessing which — and the stand-ins this
    module is also handed have neither.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


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
       guard meant to skip empty messages skipped a full one. `_content_text`
       reads both shapes and joins only the `text` blocks — so a thinking
       model's private reasoning, which rides in the same list, stays out of
       the answer. (It does that itself rather than delegating to
       `message.text`; see its own docstring for why.)

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
        text = _content_text(getattr(message, "content", ""))
        if text.strip():
            return text
    return ""

def _text(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key)
    return value if isinstance(value, str) else default


def _branch_entries(raw: Any) -> list[Any]:
    """The router's branch table, in either of its two saved forms.

    v1 documents store a newline-separated string of names; v2 (ticket 20)
    stores ``[{id, name}]`` so edges survive renames. Anything unusable
    collapses to a single ``"default"`` branch rather than raising — a router
    is the entry point, and refusing to compile is a total outage where a
    misroute is recoverable. `Branch.of` handles per-entry normalisation.
    """
    if isinstance(raw, str):
        names = [line.strip() for line in raw.split("\n") if line.strip()]
        return names or ["default"]
    if isinstance(raw, list):
        entries = [entry for entry in raw if isinstance(entry, (str, dict))]
        return entries or ["default"]
    return ["default"]


def _thread_question(state: RunState, limit: int = 6) -> str:
    """The user's message *in conversation* — what intent-interpreting nodes
    (router, supervisor) must classify against.

    Found live (ticket 73's general case): "what is the weather?" →
    assistant asks which city → "oslo" arrives as a bare fragment; a
    context-free supervisor labelled it knowledge and returned a Wikipedia
    article. History is bounded to the last few turns; the current turn
    (recorded by the input node this same run) is excluded from the history
    block since it IS the new message; a fresh thread reduces to the plain
    question.
    """
    question = state.get("question", "")
    history = [
        m for m in (state.get("messages") or [])
        if isinstance(getattr(m, "content", None), str) and m.content.strip()
    ]
    if history and history[-1].type == "human" and history[-1].content == question:
        history = history[:-1]
    history = history[-limit:]
    if not history:
        return question
    lines = [
        f"{'User' if m.type == 'human' else 'Assistant'}: {m.content.strip()}"
        for m in history
    ]
    return (
        "Conversation so far:\n" + "\n".join(lines)
        # "this is the task" is deliberate and load-bearing (pinned by test):
        # a mounted team supervisor once echoed the PREVIOUS assistant turn
        # instead of executing the new message — with a softer framing, the
        # history block probabilistically dominates the fragment that follows.
        + "\n\nThe user's new message — this is the task; the conversation "
        + f"above is context only, never the task: {question}"
    )


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
    child_document: dict[str, Any], overrides: Any
) -> tuple[dict[str, Any], list[str]]:
    """Per-mount configuration for a shared package (docs/decisions/mount-overrides.md).

    ``overrides`` is the mount node's ``data.overrides``:
    ``{"<childNodeId>": {"<fieldKey>": value}}`` — plain JSON keyed by the
    child document's own vocabulary. Applied shallowly, per field, to a COPY;
    the package on disk is the single source of truth and the compile seam
    stays one-directional. An unknown child node id warns loudly and runs on
    the package default — a typo degrading audibly beats a run that cannot
    start.
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
    return document, warnings


def _upstream_text(state: RunState, node_ids: list[str]) -> str:
    outputs = state.get("outputs") or {}
    return "\n".join(outputs[n] for n in node_ids if n in outputs)


def _wired_skill(
    state: RunState, node_ids: list[str], nodes: dict[str, Any] | None = None
) -> str:
    """The prompt contribution of whatever is wired to a node's `skill` port.

    Frontmatter is stripped here rather than at the reading node: a skill can
    arrive from a picked `SKILL.md`, from a pasted instruction, or from a file
    an upstream node loaded, and only one of those has ever heard of YAML.

    **State first, then the document — and the document is the half that was
    missing.** A skill source is `bound_only`: it is deliberately kept out of
    `plan.nodes`, because it is configuration hanging off a port rather than a
    step in the graph. It therefore never runs, never writes `outputs`, and
    this function — reading only state — returned `""` for every wired skill on
    every node type, always. The shipped `sql-analyst.md` never reached the
    analyst; the whole layer was decorative at runtime.

    Reading the document is not a fallback bolted on, it is the correct source
    for this kind of node: `_static_text`'s output does not depend on state at
    all, and the `skill` port type is produced only by `input.markdown` and
    `input.skill`, both static. State is still consulted first, so a future
    dynamic producer keeps working without another change here.
    """
    from openstategraph.skills import skill_text

    live = _upstream_text(state, node_ids)
    if live.strip():
        return skill_text(live)

    if not nodes:
        return ""
    configured = "\n".join(
        text
        for text in (
            _text(nodes.get(node_id, {}).get("data") or {}, "instruction")
            or _text(nodes.get(node_id, {}).get("data") or {}, "instructions")
            or _text(nodes.get(node_id, {}).get("data") or {}, "content")
            for node_id in node_ids
        )
        if text
    )
    return skill_text(configured)


def _replaces_rules(data: dict[str, Any]) -> bool:
    """`rulesMode` — the one extend/replace switch every prompted node has.

    `criteriaMode` is the grader's older spelling of the same field and is
    still read, so documents saved before the skill layer keep their behaviour
    exactly (`docs/decisions/skill-layer.md` records the generalisation and
    the condition for dropping this fallback). It is a *fallback*, never a
    second setting: `rulesMode` wins wherever both appear.
    """
    return (_text(data, "rulesMode") or _text(data, "criteriaMode")) == "replace"


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
    tools: ToolRegistry | None = None
    functions: dict[str, Any] | None = None
    document_loader: Callable[[str], dict[str, Any]] | None = None
    package_loader: Callable[[str], 'PackageAssets'] | None = None
    store: Any = None
    #: What the document's `settings.memory` declared (ticket 03). The
    #: default is every scope enabled, so a document with no block behaves
    #: exactly as it did before the block existed.
    memory: MemorySettings = field(default_factory=MemorySettings)
    skills_context: str = ""
    workflow_middleware: dict[str, Any] | None = None
    #: The open workflow's package directory, for ambient knowledge seeking
    #: (a non-empty `knowledge/` under it auto-binds the lookup tool).
    knowledge_package_dir: Any = None
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


def advisor_context(node_id: str, catalog: str) -> str:
    """The editor-only "you may propose a fix" context block.

    *Context*, not rules and not a contract change: it is generated
    situational detail (this agent's own id, the tools this runtime could
    bind), so `SystemPrompt` places it above the developer's rules and the
    locked OUTPUT CONTRACT still renders last. That ordering is what lets the
    fence coexist with the contract instead of competing with it.

    `attachTo` is pre-filled with the agent's own node id rather than left to
    the model, because a hallucinated id is the one failure the editor cannot
    recover from: it would either wire the tool to the wrong agent or reject a
    genuinely correct suggestion.

    **The sentence before the block is required, and says so** (ticket 22).
    *"Say so briefly, then emit exactly one fenced block"* read as a single
    instruction with an optional first half: models sometimes emitted the block
    alone, and since the fence is split out of the answer for every audience,
    the reply a client rendered was the empty string. Asking for the shape of a
    reply is what a prompt is for, so the requirement belongs here —
    `developer_channel.NO_PROSE` is the guarantee, and this is what keeps it
    from ever being needed.
    """
    if not catalog:
        return ""
    return (
        "You are running inside the workflow editor. If you cannot properly "
        "answer because this workflow lacks a capability, first tell the user "
        "in plain words what you cannot do and why — always that sentence, "
        "never the block alone — and then emit exactly one fenced block:\n"
        f"{FENCE_OPEN}\n"
        '{"nodeType": "<one from the catalogue below>", '
        f'"attachTo": "{node_id}", '
        '"port": "tools", "label": "<short human label>", '
        '"reason": "<one sentence>"}\n'
        f"{FENCE_CLOSE}\n"
        "Only suggest when genuinely blocked — never when you can already "
        "answer, and never more than one block.\n"
        "Tools that could be added to you:\n"
        f"{catalog}"
    )


def branch_context(node_id: str, plan: CompiledPlan, nodes: dict[str, Any]) -> str:
    """What the classifier feeding this agent can actually route to (ticket 11).

    The **chainlogic** rule, made mechanical: a conversational branch that
    tells the user "just ask me for X" is writing the *next* question, and the
    router has to be able to place that question on a branch that can answer
    it. Found live on `page-analytics`: the conversation agent — whose prompt
    was hand-written and could see nothing but itself — offered "charts",
    "dashboards" and "copy/paste reports" that no branch produces, and phrased
    a data question ("Show trends: monthly sales, media-type mix, top genres")
    in wording the router then classified as `full_report`, the one branch
    that ends in a human approval gate and an email rather than an answer. The
    user got no answer at all.

    Its own prompt could never have prevented that, because the branch table
    is not knowledge the prompt author holds — it is a fact about the *graph*,
    and it changes whenever anyone renames a branch or draws an edge. So it is
    **generated context**, resolved from the compiled plan at build time and
    handed to `SystemPrompt` exactly like `advisor_context` and the skills
    text: above the developer's rules, below nothing the developer edits, with
    the locked output contract still rendering last.

    The router's `rules` text rides verbatim rather than being parsed into
    per-branch sentences. Splitting one free-text field into a table would be
    duplicating *knowledge* — the classifier reads that same string, and two
    renderings of it are two things that can disagree. Verbatim cannot.

    Returns "" for any agent no classifier routes to, which is most of them.
    """
    for router_id, destinations in plan.conditional.items():
        if (nodes.get(router_id) or {}).get("type") != ROUTER_TYPE:
            continue
        if node_id not in destinations.values():
            continue
        data = (nodes.get(router_id) or {}).get("data") or {}
        by_id = {}
        for entry in _branch_entries(data.get("branches")):
            if isinstance(entry, dict):
                by_id[str(entry.get("id") or entry.get("name") or "")] = str(
                    entry.get("name") or entry.get("id") or ""
                )
            else:
                by_id[str(entry)] = str(entry)
        names = [by_id.get(key, key) for key in destinations]
        mine = sorted(
            {by_id.get(key, key) for key, dst in destinations.items() if dst == node_id}
        )
        if not names:
            continue
        lines = [
            "This workflow routes every incoming question to exactly ONE of "
            "these branches, by classifying the question's wording:",
            "  " + ", ".join(names),
        ]
        if mine:
            lines.append(f"You are the '{', '.join(mine)}' branch.")
        rules = _text(data, "rules")
        if rules:
            lines.append("How the classifier decides:\n" + rules)
        lines.append(
            "So: never offer a capability no branch above provides, and when "
            "you suggest what to ask next, phrase each suggestion the way the "
            "branch that can answer it is described above — a suggestion the "
            "classifier sends to the wrong branch is a suggestion the user "
            "cannot get answered."
        )
        # ...and the other half of that instruction, which was missing (ticket
        # 23). The branch names are routing vocabulary, and an agent handed a
        # list it is told to phrase things by will read the list aloud: live
        # refusals offered to help with "off-topic questions" and to "let you
        # know the types of requests I can't handle" — the branch table recited
        # to the person asking. That is the very failure this block exists to
        # prevent, in the opposite direction, so the correction belongs in the
        # block that hands the names over rather than in each workflow's
        # prompt, where it would be one sentence copied into every document
        # that can disagree with the next.
        lines.append(
            "These branch names are this workflow's internal routing "
            "vocabulary: never name a branch to the user, and never read the "
            "list back as a menu. Describe what you can help with in the "
            "user's own words, as questions they could ask. When you cannot "
            "help, say what is missing — the fact, the data or the capability "
            "this workflow does not have — never merely that the request is "
            "one you do not handle."
        )
        return "\n".join(lines)
    return ""


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
        store: Any = None,
        memory: MemorySettings | None = None,
        skills_context: str = "",
        workflow_middleware: dict[str, Any] | None = None,
        knowledge_package_dir: Any = None,
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
            store = services.store
            memory = services.memory
            skills_context = services.skills_context
            workflow_middleware = services.workflow_middleware
            knowledge_package_dir = services.knowledge_package_dir
            knowledge_dir_override = services.knowledge_dir_override
            max_attempts = services.max_attempts
            advisor_catalog = services.advisor_catalog
        #: Non-empty only for a run whose audience is `developer`
        #: (`audience: "developer"` on the request — see `api/audience.py`,
        #: which is the generation half of that boundary). See
        #: `advisor_context`.
        self.advisor_catalog = advisor_catalog
        self.model = model
        self.tools = tools or {}
        #: `function.<name>` -> callable — deterministic graph steps
        #: discovered from the workflow's `functions/` (ticket 35).
        self.functions = functions or {}
        #: Loads another workflow's document by slug, for `workflow.subgraph`
        #: nodes (ticket 34). None means subgraphs cannot resolve — recorded
        #: loudly in `unresolved_subgraphs`, never silently.
        self.document_loader = document_loader
        #: Resolves a CHILD workflow's (tools, functions) from its own
        #: package, for subgraph/team nodes. Without this, a child inherits
        #: the parent's registries and a routed tabular question under the
        #: concierge (ticket 67) silently loses its tools — the
        #: parametric-answer failure this codebase treats as the worst kind.
        self.package_loader = package_loader
        #: The long-term memory store (ticket 65). Its presence is what turns
        #: the prebuilt save/search-memory tools on for every agent — the
        #: tools reach it through `langgraph.config.get_store()` at run time,
        #: so this reference is a capability flag, not a data path.
        self.store = store
        #: The document's memory declaration. Narrowing happens in the
        #: tools' own schema, so a scope this workflow does not use is one
        #: no agent is ever offered.
        self.memory = memory or MemorySettings()
        #: Procedural skills (`workflows/<slug>/skills/*.md`) — business
        #: rules, JOIN conventions, house style — joined once and given to
        #: every agent in this workflow as prompt *context* (above rules,
        #: below the locked preamble; SystemPrompt owns the ordering).
        self.skills_context = skills_context
        #: Ambient knowledge seeking (knowledge-architecture decision):
        #: mirroring how `store` turns the memory tools on, a non-empty
        #: `knowledge/` under this package directory auto-binds the
        #: knowledge-lookup tool to every agent and worker — capability by
        #: configuration, no Knowledge atom wiring required.
        self.knowledge_package_dir = knowledge_package_dir
        #: The explicit `load_workflow(knowledge_dir=...)` override, or None
        #: for the convention. Applies to this workflow's own agents only.
        self.knowledge_dir_override = knowledge_dir_override
        #: Slot-name -> middleware instance from `workflows/<slug>/middlewares/`
        #: (ticket 32): merged into every agent's slot table AFTER the tier
        #: preset and BEFORE per-node config, so a workflow file replaces a
        #: preset slot and a node's own setting still wins.
        self.workflow_middleware = dict(workflow_middleware or {})
        #: The chain of subgraph slugs above this runtime — how a workflow
        #: that (transitively) includes itself is refused at build time
        #: instead of recursing forever at run time.
        self._ancestry = _ancestry
        self.max_attempts = max_attempts
        #: Per-node model overrides, keyed by the resolved LangChain model
        #: string — cached so ten agents on the same non-default model share
        #: one client instance rather than each cold-starting its own.
        self._model_cache: dict[str, Any] = {}
        #: node id -> node type, populated by `factory()`.
        self._types: dict[str, str] = {}
        #: node id -> raw node dict, populated by `factory()`. A tool
        #: binding is resolved by *type* against `self.tools`, which has no
        #: access to that specific bound node's own `data` — this is how a
        #: tool factory (e.g. `tool.chinook-execute-sql`'s row cap) reads a
        #: per-node config value rather than only ever seeing its type.
        self._nodes: dict[str, dict[str, Any]] = {}
        #: Tool nodes wired on the canvas with no implementation available.
        #:
        #: Surfaced rather than swallowed. An agent that silently loses its tools
        #: does not fail — it answers from parametric knowledge, confidently and
        #: wrongly. Observed exactly that: a Reddit tool node wired to an agent
        #: produced an authoritative-sounding answer about global music revenue
        #: instead of querying anything. A visible warning beats a plausible lie.
        self.unresolved_tools: list[str] = []
        #: Function node types wired on the canvas with no discovered callable,
        #: and subgraph nodes whose workflow could not be loaded. Same loudness
        #: rule as tools: a silently-degraded step reads as "covered" when it
        #: was not.
        self.unresolved_functions: list[str] = []
        self.unresolved_subgraphs: list[str] = []
        #: Team mounts whose child cannot enforce the outcome on their card,
        #: as `(node id, slug)`.
        #:
        #: `TeamNode`'s `Expected outcome` never reaches the compiler —
        #: `_subgraph` reads `workflow` and `overrides` and nothing else — so a
        #: user writes a constraint, reasonably believes it binds the run, and
        #: gets no signal that it does not. A document with no grader at all
        #: can be mounted as a Team and will still display that outcome
        #: (production-ready ticket 03).
        #:
        #: Reported rather than refused: a Team without a loop is a legal graph
        #: that answers questions. What it cannot do is keep the promise
        #: printed on its card, which is a thing to say, not a thing to refuse.
        self.unenforced_outcomes: list[tuple[str, str]] = []
        #: Node types this build has no factory for, as `type` and node id.
        #:
        #: The loud half of a rule that was only half kept. `errors.py` records
        #: the policy — an unknown node type is *reported*, not raised, so a
        #: document containing one still answers what it can — and
        #: `_passthrough` implemented the degrade while reporting nothing. Its
        #: docstring claimed "the gap is visible as an unchanged value", which
        #: is exactly what hides it: the skipped node forwards its input, so
        #: the run answers the user's own question back and looks like it
        #: worked. Found through the typo `agent.react` for `agent.llm`.
        #:
        #: Recorded here rather than in `factory_for`, which is a pure lookup
        #: that `test_data_key_contract.py` enumerates over every catalogue
        #: type — a side effect there would report node types nobody wired.
        self.unknown_node_types: list[tuple[str, str]] = []
        #: Per-mount override problems (unknown child node id, wrong shape) —
        #: surfaced through `runtime_warnings` beside unresolved tools.
        self.override_warnings: list[str] = []
        #: Capabilities that failed to *load* — a tool module that would not
        #: import, an abstract class discovery could not instantiate, a plugin
        #: distribution that half-installed (ticket 07 / RC-04).
        #:
        #: Distinct from `unresolved_tools`, which is about a node on the
        #: canvas finding no implementation; this is about an implementation
        #: that never became one. Both share the channel deliberately: from a
        #: developer's seat, "the tool I wrote is not here" is one question,
        #: and answering half of it in a server log they never open is how the
        #: original bug survived. Populated by `WorkflowServices.runtime_for`.
        self.capability_warnings: list[str] = []
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
        #: though both spellings agree wherever `safe_name` is the identity.
        self.node_ids_by_name: dict[str, str] = {}
        #: Mount canvas node id -> the workflow slug it descends into, for
        #: this document and every document mounted under it.
        #:
        #: `node_ids_by_name` alone cannot say *which document* a resolved id
        #: belongs to, and that is not a theoretical gap: the shipped
        #: `concierge` mounts `chinook-assistant`, and both documents have an
        #: `in1`, a `router1` and an `out1`. Without this, a client with the
        #: child open would light its `router1` when the PARENT's router ran —
        #: a second, quieter version of the lie tickets 33/34 are about.
        #:
        #: With it, every level of a run's path can name the document it
        #: happened in, and a client matches on the slug it has open rather
        #: than on an id that two documents may share.
        self.mount_slugs: dict[str, str] = {}
        self._builders: dict[str, Callable[..., Any]] = {
            "input.text": self._input,
            # NOT `_input`. A skill source is a *static text source*, not the
            # run's entry point — see `_static_text`.
            "input.markdown": self._static_text,
            "input.skill": self._static_text,
            "agent.llm": self._agent,
            "route.classifier": self._router,
            "route.grader": self._grader,
            "human.approval": self._human_approval,
            "orchestrate.supervisor": self._orchestrator,
            "orchestrate.worker": self._worker,
            "function.format_report": self._format_report_function,
            "output.formatted": self._output,
        }

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
            self.node_ids_by_name.setdefault(safe_name(node_id), node_id)

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
        """
        builder = self._builders.get(node_type)
        if builder is not None:
            return builder
        # Discovered capabilities resolve by convention, after the
        # explicitly-registered builders so a built-in like
        # `function.format_report` can never be shadowed by accident.
        if node_type == "workflow.subgraph":
            return self._subgraph
        if node_type.startswith("function."):
            return self._discovered_function
        return self._passthrough

    def _resolve_model(self, data: dict[str, Any]) -> Any:
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
        """
        return self._apply_effort(self._base_model(data), _text(data, REASONING_EFFORT_KEY))

    def _base_model(self, data: dict[str, Any]) -> Any:
        """The model itself, before any per-call parameter is applied."""
        selection = _text(data, "model")
        if not selection:
            return self.model
        provider, _, model_id = selection.partition("/")
        if not model_id or provider == "mock":
            return self.model
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
                    selected = self.model
                self._model_cache[key] = selected
            except Exception:
                # An unconfigured provider (no API key) or an unrecognised
                # model id must not take the whole run down — the shared
                # default still produces an answer, just not the node's own
                # choice. Cached too, so one bad selection does not retry
                # (and re-fail) on every node that shares it.
                self._model_cache[key] = self.model
        return self._model_cache[key]

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
        if warning and warning not in self.capability_warnings:
            self.capability_warnings.append(warning)
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
            return {"outputs": {node_id: configured}}

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

            text = state.get("question") or configured
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

        The exact mirror of the memory rule above (`self.store is not None`
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
                self.knowledge_package_dir, knowledge_dir=self.knowledge_dir_override
            )
        ambient = self._ambient_knowledge_memo
        if ambient is None:
            return
        if any(getattr(t, "name", "") == ambient.name for t in lc_tools):
            return
        lc_tools.append(ambient.as_langchain_tool())

    def _bound_tool(self, tool_node_id: str) -> Any | None:
        """Resolves one bound tool node to the implementation it should use.

        The shared registry (`self.tools`) is keyed by *type*, one instance
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
        tool = self.tools.get(tool_type)
        if tool is None:
            if tool_type not in self.unresolved_tools:
                self.unresolved_tools.append(tool_type)
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

        # Resolved by the *type* of each bound node, so wiring a tool on the
        # canvas is exactly what gives the agent that capability.
        lc_tools = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool = self._bound_tool(tool_node_id)
            if tool is not None:
                lc_tools.append(tool.as_langchain_tool())

        # A store's presence turns on the prebuilt memory tools for every
        # agent (ticket 65) — capability by configuration, no per-workflow
        # wiring, matching the minimum-viable-prebuilt rule.
        if self.store is not None:
            from openstategraph.memory import memory_tools

            lc_tools.extend(memory_tools(self.memory))

        # Same rule for knowledge: a non-empty knowledge/ in this workflow's
        # package auto-binds the lookup tool. Deduped by tool name, so an
        # explicitly wired Knowledge atom plus the ambient rule is one tool,
        # never two.
        self._attach_ambient_knowledge(lc_tools)

        data = node.get("data") or {}
        model = self._resolve_model(data)
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
        feedback_sources = [
            src
            for src, dests in plan.conditional.items()
            if node_id in (dests.get("revise"), dests.get("rejected"))
        ]
        built: dict[str, Any] = {}

        def agent_for(skill: str) -> Any:
            if skill not in built:
                contributions: dict[str, Any] = dict(self.workflow_middleware)
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
                if data.get("summarize") and model is not None:
                    # LangChain's own prebuilt, never hand-rolled (ticket 66):
                    # summarizes older turns when the context bloats, keeping
                    # the recent tail verbatim.
                    from langchain.agents.middleware import SummarizationMiddleware

                    contributions["summarization"] = SummarizationMiddleware(model=model)
                tier_cls = agent_family.agent_node_for_tier(_text(data, "tier"))
                built[skill] = tier_cls(
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
                            self.skills_context,
                            # The branches this agent's own classifier can
                            # reach (ticket 11) — generated context, so an
                            # agent's suggestions are grounded in the graph
                            # rather than in what its prompt author guessed
                            # the graph contained.
                            branch_context(node_id, plan, self._nodes),
                            advisor_context(node_id, self.advisor_catalog),
                        )
                        if part
                    ),
                    middleware=contributions,
                ).build()
            return built[skill]

        def run(state: RunState) -> dict[str, Any]:
            prompt = _upstream_text(state, upstream + conditional_upstream) or state.get(
                "question", ""
            )
            skill = _wired_skill(state, skills, self._nodes)
            decisions = state.get("decisions") or {}
            feedback = state.get("feedback", "")
            if not any(decisions.get(src) in ("revise", "rejected") for src in feedback_sources):
                feedback = ""

            agent = agent_for(skill) if model is not None else None
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
                payload.append(
                    HumanMessage(content=f"Your previous answer was rejected: {feedback}")
                )
            elif not payload or payload[-1].type != "human" or payload[-1].content != prompt:
                payload.append(HumanMessage(content=prompt))
            invocation: dict[str, Any] = {"messages": payload}
            rubric_text = _text(data, "rubric").strip()
            if rubric_text:
                invocation["rubric"] = rubric_text
            result = agent.invoke(invocation)
            # `_final_text`, not `messages[-1]`: a loop can legitimately end on
            # a message with no content — a dangling tool call, or a provider
            # blip the retry swallowed — and the last message is then "" while
            # the answer sits one message back. `_worker` and `_ModelShim`
            # already read it this way; this node did not, which is how a
            # correct Chinook answer reached a grader as "the answer is empty"
            # and spent the whole retry budget re-asking an answered question.
            text = _final_text(result.get("messages") or [])
            answer = text if isinstance(text, str) else str(text)
            return {
                "outputs": {node_id: answer},
                "answer": answer,
                "attempts": state.get("attempts", 0) + 1,
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
        base_model = self._resolve_model(data)
        classifying_model = base_model
        if _text(data, "tier") == "deep" and base_model is not None:
            classifying_model = _DeepAgentAsChatModel(base_model, name=f"router_{node_id}")
        upstream = [src for src, dst in plan.edges if dst == node_id]
        skills = plan.skill_bindings.get(node_id, [])

        def router_for(skill: str) -> Router:
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
            classified = (
                _thread_question(state) if turn == state.get("question", "") else turn
            )
            skill = _wired_skill(state, skills, self._nodes)
            router = router_for(skill) if skill else prebuilt
            decision = router.classify(classified)
            return {
                # The conditional edge dispatches on the *stable id* — the
                # `branch:<id>` port the canvas edge actually leaves from —
                # while the model classified by human-readable *name*.
                # `route_key` is the one place that mapping lives.
                "decisions": {node_id: router.route_key(decision.branch)},
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
        base_model = self._resolve_model(data)
        grading_model = base_model
        if _text(data, "tier") == "deep" and base_model is not None:
            grading_model = _DeepAgentAsChatModel(base_model, name=f"grader_{node_id}")
        raw_rubric = data.get("rubric")
        rubric_rows = [
            {"criterion": str(row.get("criterion") or row.get("name") or ""),
             "required": bool(row.get("required", True))}
            for row in raw_rubric
        ] if isinstance(raw_rubric, list) else []
        cap = int(data.get("maxAttempts") or self.max_attempts)
        upstream = [src for src, dst in plan.edges if dst == node_id]
        skills = plan.skill_bindings.get(node_id, [])

        def grader_for(skill: str) -> Grader:
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
            )

        def run(state: RunState) -> dict[str, Any]:
            candidate = _upstream_text(state, upstream) or state.get("answer", "")
            grader = grader_for(_wired_skill(state, skills, self._nodes))
            verdict = grader.grade(candidate, question=state.get("question", ""))

            # Budget check before routing: a grader that keeps rejecting must
            # still let the run finish with an honest answer rather than spin.
            exhausted = state.get("attempts", 0) >= cap
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
                outcome = (
                    f"I could not produce an answer after {cap} "
                    f"{'attempt' if cap == 1 else 'attempts'}. "
                    f"The last review said: {verdict.feedback or 'no reason given'}"
                )

            return {
                "decisions": {node_id: branch},
                "feedback": "" if branch == "pass" else verdict.feedback,
                "outputs": {node_id: outcome},
            }

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
        data = node.get("data") or {}
        message = _text(data, "message") or "Approve this result?"
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            from langgraph.types import interrupt

            candidate = _upstream_text(state, upstream) or state.get("answer", "")
            decision = interrupt({"message": message, "candidate": candidate})

            approved = isinstance(decision, dict) and decision.get("decision") == "approve"
            feedback = ""
            if not approved:
                feedback = (decision or {}).get("feedback", "") if isinstance(decision, dict) else ""
            return {
                "decisions": {node_id: "approved" if approved else "rejected"},
                "feedback": feedback,
                "outputs": {node_id: candidate},
            }

        return run

    def _orchestrator(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Splits its instruction into subtasks and writes the plan to state.

        Does **not** dispatch. Dispatch is the compiler's `_fan_out_router`,
        reading exactly what this writes — the same node-decides /
        edge-dispatches split as the router and the grader.
        """
        from openstategraph.abc.orchestrator import Archetype, archetype_key

        data = node.get("data") or {}
        cap = int(data.get("maxSubtasks") or 8)
        # The model is for archetype labelling (ticket 37's hybrid routing);
        # decomposition itself stays deterministic. With one wired archetype
        # no labelling call is ever made, so the pre-archetype shape costs
        # nothing extra.
        supervisor_model = self._resolve_model(data)
        # The supervisor's rules and its wired skill shape the one model call
        # it makes — assigning each subtask to a worker archetype. The split
        # itself stays deterministic, so a skill here cannot change *how many*
        # subtasks there are, only *who* gets them.
        def orchestrator_for(skill: str) -> Orchestrator:
            return Orchestrator(
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
            )

        orchestrator = orchestrator_for("")
        # The wired worker archetypes, in edge order — the same roster the
        # compiler's dispatch map is built from, keyed by the same
        # `archetype_key`, so a label the planning prompt offered is exactly
        # a key the fan-out router can resolve.
        archetypes = []
        for worker_id in plan.fan_out.get(node_id, []):
            worker_node = self._nodes.get(worker_id) or {}
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
                    tool = self.tools.get(tool_type)
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
        feedback_sources = [
            src
            for src, dests in plan.conditional.items()
            if node_id in (dests.get("revise"), dests.get("rejected"))
        ]
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
            planner = orchestrator_for(skill) if skill else orchestrator
            subtasks = planner.plan(
                instruction, generation=generation, archetypes=archetypes
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
            return {
                "subtasks": {node_id: [t.model_dump() for t in subtasks]},
                "outputs": {node_id: f"Planned {len(subtasks)} subtask(s)."},
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

        lc_tools = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool = self._bound_tool(tool_node_id)
            if tool is not None:
                lc_tools.append(tool.as_langchain_tool())

        # Workers are agents too: the ambient knowledge rule applies (deduped
        # against an explicitly wired atom, same as `_agent`).
        self._attach_ambient_knowledge(lc_tools)

        skills = plan.skill_bindings.get(node_id, [])
        # The worker is an agent too: its card carries the same `model` select
        # as every model-driven node, and `_resolve_model`'s docstring records
        # exactly this class of bug — a visible per-node choice silently
        # ignored for the graph-wide default (audit 2026-08).
        data = node.get("data") or {}
        model = self._resolve_model(data)
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

        def run(state: RunState) -> dict[str, Any]:
            task_id = state.get("task_id", "")
            instruction = state.get("task_instruction", "")

            if model is None:
                return {"worker_results": {task_id: ""}}

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
                context=self.skills_context,
            ).build()
            result = agent.invoke({"messages": [HumanMessage(content=instruction)]})
            out = result.get("messages") or []
            text = _final_text(out)
            return {"worker_results": {task_id: text if isinstance(text, str) else str(text)}}

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
            # A task that died (retries exhausted → error handler wrote to
            # outputs, which carries no task identity) must appear as a
            # named gap, not vanish from the join (ticket 61 residual #2).
            for missing in sorted(current_ids - scoped.keys()):
                scoped[missing] = "_(this task failed before reporting a result)_" 
            body = "\n\n".join(
                # An empty member result renders as an explicit gap — a blank
                # section reads like formatting, and the grader (and the
                # human) must see the miss to act on it (ticket 61).
                f"### {task_id}\n{text or '_(this member produced no result)_'}"
                for task_id, text in sorted(scoped.items())
            )
            report = f"# {title}\n\n{body}" if body else f"# {title}\n\n_No results._"
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
        fn = self.functions.get(node_type)
        if fn is None:
            if node_type not in self.unresolved_functions:
                self.unresolved_functions.append(node_type)
            return self._passthrough(node_id, node, plan)

        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            text = _upstream_text(state, upstream) or state.get("question", "")
            try:
                result = fn(text)
            except Exception as exc:
                return {"outputs": {node_id: f"[{node_id} failed: {type(exc).__name__}: {exc}]"}}
            output = result if isinstance(result, str) else str(result)
            return {"outputs": {node_id: output}, "answer": output}

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
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        data = node.get("data") or {}
        slug = _text(data, "workflow").strip()
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
            raise ValueError(
                f"Workflow {slug!r} includes itself through its subgraphs ({chain}); "
                "a subgraph cycle can never terminate"
            )

        child_graph = None
        if slug and self.document_loader is not None:
            try:
                child_document = self.document_loader(slug)
            except Exception:
                child_document = None
            if child_document is not None:
                # Per-mount overrides (docs/decisions/mount-overrides.md):
                # this mount's own configuration, merged onto a copy of the
                # shared package before the child compiles.
                child_document, mount_warnings = apply_mount_overrides(
                    child_document, data.get("overrides")
                )
                for warning in mount_warnings:
                    self.override_warnings.append(f"{slug or node_id}: {warning}")
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
                    self.unenforced_outcomes.append((node_id, slug))
                child_assets = PackageAssets(
                    tools=self.tools,
                    functions=self.functions,
                    skills_context=self.skills_context,
                    workflow_middleware=self.workflow_middleware,
                    knowledge_dir=self.knowledge_package_dir,
                )
                if self.package_loader is not None:
                    try:
                        child_assets = self.package_loader(slug)
                    except Exception:
                        pass  # the parent assets remain the honest fallback
                child_runtime = NodeRuntime(
                    services=RuntimeServices(
                        model=self.model,
                        tools={**self.tools, **child_assets.tools},
                        functions={**self.functions, **child_assets.functions},
                        document_loader=self.document_loader,
                        package_loader=self.package_loader,
                        store=self.store,
                        skills_context=child_assets.skills_context,
                        workflow_middleware=child_assets.workflow_middleware or {},
                        # The child's OWN knowledge, never the parent's —
                        # the same isolation as skills (ticket 67's lesson).
                        knowledge_package_dir=child_assets.knowledge_dir,
                        max_attempts=self.max_attempts,
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
                    store=self.store,
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
                # different question: the child's name->id map is what lets a
                # frame from inside this mount say which card of the CHILD's
                # canvas it is about. Without it the only ids on the wire
                # belong to documents the viewer may not have open (tickets
                # 33/34). `setdefault` keeps this document's own answer
                # authoritative where two documents share an id — `concierge`
                # and `chinook-assistant` both have `in1` and `router1`.
                #
                # Taken after `build()`, not after `factory()`: a mount inside
                # the child is resolved by that build, so a grandchild's ids
                # only exist on `child_runtime` once it has run.
                for name, canvas_id in child_runtime.node_ids_by_name.items():
                    self.node_ids_by_name.setdefault(name, canvas_id)
                # Which document each level of a run's path happened in,
                # keyed by the **mount path** — the chain of mount node ids
                # from this document down — not by the bare node id.
                #
                # Node ids are unique within a document and nowhere else. Two
                # sibling subtrees that each mount something at a node called
                # `inner` are two different mounts of two different packages,
                # and a flat map collapsed them first-wins: a frame from one
                # was attributed to the other's slug. That is the exact lie
                # `pathSlugs` exists to remove, reappearing one level down.
                self.mount_slugs[node_id] = slug
                for mount_path, mounted_slug in child_runtime.mount_slugs.items():
                    self.mount_slugs[f"{node_id}/{mount_path}"] = mounted_slug

        if child_graph is None:
            label = slug or "(no workflow selected)"
            if label not in self.unresolved_subgraphs:
                self.unresolved_subgraphs.append(label)
            captured = None
        else:
            captured = child_graph

        def run(state: RunState) -> dict[str, Any]:
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
            child_config = {"configurable": {"workflow_slug": slug}} if slug else None
            final = captured.invoke(
                {
                    "question": question,
                    # The conversation crosses the boundary (found live: the
                    # Architect routed through the concierge re-asked its
                    # interview question every turn — the child was invoked
                    # with fresh state, so the parent thread's history never
                    # reached it). Graph state stays isolated; the DIALOGUE
                    # is precisely what a routed conversational child needs.
                    "messages": list(state.get("messages") or []),
                    "attempts": 0,
                    "decisions": {},
                    "outputs": {},
                },
                child_config,
            )
            answer = final.get("answer", "")
            # The child's loop cost is part of the parent's story: without
            # this, a Team that revised twice reports attempts=0 (ticket 60).
            update: dict[str, Any] = {"outputs": {node_id: answer}, "answer": answer}
            child_attempts = final.get("attempts")
            if isinstance(child_attempts, int) and child_attempts > 0:
                update["attempts"] = child_attempts
            return update

        return run

    def _output(self, node_id: str, _node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Collects whatever reached it as the run's answer."""
        upstream = [src for src, dst in plan.edges if dst == node_id]
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]

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
                answer = (
                    "The workflow finished without producing an answer. "
                    "Check the run trace to see which step returned nothing."
                )

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
        already_reported = node_type in self.unresolved_functions
        if node_type and not already_reported:
            entry = (node_type, node_id)
            if entry not in self.unknown_node_types:
                self.unknown_node_types.append(entry)
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            return {"outputs": {node_id: _upstream_text(state, upstream)}}

        return run


__all__ = ["NodeRuntime", "PackageAssets", "RunState", "RuntimeServices", "ToolRegistry", "chinook_tool_registry", "merge_decisions"]
