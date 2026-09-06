"""``workflow.json`` → a LangGraph ``StateGraph``.

This is the compile seam, and it is **one-directional** (ticket 23): the document
flows in, a runnable graph comes out, and nothing reads runtime objects back into
the editor's model.

The single most important thing this file knows: **not every edge is a graph
edge.** A canvas edge means different things depending on the port it lands on.

| Target port type | Meaning | Becomes |
| --- | --- | --- |
| `tool` | this tool is available to that agent | a **binding**, no graph edge |
| `skill` | this text shapes the agent's prompt | a **binding**, no graph edge |
| `text`, `result` | control flow | `add_edge` |
| `feedback` | a grader's rejection returning upstream | part of a **conditional** edge |

Getting that wrong is not a subtle bug: treating a tool link as control flow would
put the tool node *in the execution order*, so it would run once on its own before
the agent ever called it — and the agent would then also call it, silently doubling
the work. Treating a feedback link as an ordinary edge would create an all-static
cycle, which can never terminate.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Hashable, Mapping

if TYPE_CHECKING:
    # Types only. Named rather than `Any` because this is the seam where the
    # two meanings of "store" meet: `BaseStore` is long-term memory, and the
    # filesystem `WorkflowStore` — the other thing that word means one module
    # over — passes every runtime check this parameter used to have
    # (install-experience ticket 12).
    from langgraph.store.base import BaseStore

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from openstategraph.abc.orchestrator import archetype_key, default_worker_node
from openstategraph.errors import GENERIC_FAILURE_MESSAGE, OpenStateGraphError  # noqa: F401
from openstategraph.compile.run_context import (
    context_declaration,
    context_declaration_problems,
    mint_context_schema,
    unmintable_context_keys,
)
from openstategraph.compile.subagents import subagent_declaration_problems
from openstategraph.compile.fields import _text, branch_ids_by_spelling
from openstategraph.compile.node_catalogue import CATALOGUE, PortSpec
from openstategraph.compile.node_doors import with_both_doors
from openstategraph.compile.side_effects import DEFAULT_MAX_ATTEMPTS
from openstategraph.compile.state import STEP_BUDGET_FLOOR
from openstategraph.step_budget import read_budget_stop
from openstategraph.compile.state import NO_MODEL_MARKER  # noqa: F401  (re-exported)

#: `TimeoutPolicy` was added in `langgraph>=1.2`.
try:
    from langgraph.types import TimeoutPolicy
except ImportError:
    TimeoutPolicy = None  # type: ignore[misc,assignment]

#: `CachePolicy` and a cache backend were added in `langgraph>=1.2`. Both
#: halves are needed or neither is: `cache_policy` names a policy and
#: `compile(cache=...)` supplies the store it reads, so a policy without a
#: cache is a field that does nothing (`organisms-first-class/34`).
try:
    from langgraph.cache.memory import InMemoryCache
    from langgraph.types import CachePolicy
except ImportError:
    CachePolicy = None  # type: ignore[misc,assignment]
    InMemoryCache = None  # type: ignore[misc,assignment]

#: `NodeError` was added in `langgraph>=1.2`; gracefully degrade if absent.
try:
    from langgraph.errors import NodeError
except ImportError:
    NodeError = None  # type: ignore[misc,assignment]

#: Port types that carry **control flow**. Everything else is a binding.
CONTROL_PORT_TYPES = frozenset({"text", "result"})

#: Port types that bind a capability to a node rather than sequencing it.
BINDING_PORT_TYPES = frozenset({"tool", "skill"})

ROUTER_TYPE = "route.classifier"
GRADER_TYPE = "route.grader"
ORCHESTRATOR_TYPE = "orchestrate.supervisor"
WORKER_TYPE = "orchestrate.worker"
#: Ticket "human-in-the-loop": pauses via `interrupt()` and dispatches on a
#: human decision, the same node-decides/edge-dispatches split as the router
#: and the grader — see the conditional-edge handling below.
HUMAN_APPROVAL_TYPE = "human.approval"
#: Guardrails ticket 01: applies a PII/content policy to whatever passes
#: through it and dispatches on the outcome — `allowed` continues, `blocked`
#: takes a wire of its own to an Output carrying the refusal. Same
#: node-decides/edge-dispatches split, and the labels are the literal port ids
#: for the same reason the approval's are: `blocked` does not loop back the
#: way a grader's `revise` does, it takes a different deliberately-wired path.
GUARDRAIL_TYPE = "guard.policy"
#: `launch-readiness` 65: a grader's mechanical sibling — same `pass`/`revise`
#: shape (below), calls a package function instead of a model. Deliberately
#: routed like `GRADER_TYPE`, not like `GUARDRAIL_TYPE`: a guard's `revise`
#: loops back upstream the way a grader's does, it does not take a forward
#: wire the way a blocked guardrail does.
GUARD_CHECK_TYPE = "guard.check"
#: `osg-agent-experience` 42: a classifier's mechanical sibling — the same
#: one-conditional-edge-per-branch shape, decided by a package function instead
#: of by a model, with every way out typed `result` so an output may take one.
#: Routed exactly like `ROUTER_TYPE` below and deliberately not like
#: `GUARD_CHECK_TYPE`: this is a fork whose branches go forward, not a loop
#: whose `revise` returns upstream.
ROUTE_CHECK_TYPE = "route.check"

#: `route.check`'s static way out for a name it could not resolve — a **port**,
#: unlike `route.classifier`'s `fallback` *field*. Named here, beside the type,
#: because the compiler's `unrouted_route` reads it (`osg-agent-experience/80`)
#: and `compile/nodes/route_check.py` cannot own a constant this module needs:
#: that module imports this one. Its docstring keeps the argument for the
#: shape.
ROUTE_CHECK_FALLBACK_BRANCH = "fallback"

#: The label a single-choice router's conditional edge takes to `END` when the
#: verdict named a branch nobody wired and no fallback was declared
#: (`osg-agent-experience/80`). A label rather than `END` itself because
#: `add_conditional_edges` is given a path map and the path function's contract
#: has always been to return a *label*.
#:
#: It is **drawn**, which is why it reads as English rather than as a sentinel:
#: every branch of the path map becomes an arrow in `draw_mermaid`, so a
#: document in this state shows a dotted edge from the fork to `__end__` on the
#: preview and beside the run. That is the honest picture — that branch does
#: end the run — and `__unrouted__` would have put a compiler's private word on
#: a customer's diagram. The space is also what makes a collision unreachable:
#: a branch label here is a `branch:`-stripped port id or the static
#: `fallback`, and no port id carries one.
STOP_LABEL = "unwired branch"

#: The port type that marks a fan-out declaration rather than control flow or a
#: capability binding. An edge landing on a `worker`-typed port means "this is
#: the node Send() dispatches to," not "this runs next."
WORKER_PORT_TYPE = "worker"


def _default_error_handler(state: dict[str, Any], error: NodeError) -> dict[str, Any]:
    """Runs once a node's retries are exhausted. Recovers, never crashes.

    The `error: NodeError` annotation is **load-bearing**, not documentation:
    current langgraph injects the failure context only into a parameter that
    is both *named* `error` and *annotated* `NodeError` (class or the literal
    string — this module's `from __future__ import annotations` makes it the
    string, which the matcher accepts). An untyped `error` parameter is not
    injected at all, and the handler then dies on arity — found when a
    langgraph upgrade silently broke every fault-tolerance test.

    Deliberately returns a plain state update rather than a `Command`: with
    no `goto`, LangGraph continues along the node's own already-declared
    edges exactly as if it had returned this value normally — no routing
    knowledge is needed here, which matters because this handler is generic
    across every node type a workflow might contain.

    Writing the failure into `outputs[node]` (the same channel every node
    factory already writes its result to — see `node_runtime.py`) means a
    failed node still produces *something* a downstream node or the final
    report can read, instead of the whole run aborting because one Chinook
    tool call or one dispatched worker had a bad day. This is the graph-
    assembly-level version of `_grader`'s own rule: a candidate that failed
    is still evidence, not a reason to discard the run.
    """
    return _error_handler_for({})(state, error)


def _error_handler_for(
    canvas_ids: dict[str, str],
) -> Callable[[dict[str, Any], NodeError], dict[str, Any]]:
    """`_default_error_handler`, told which canvas node each graph name is.

    LangGraph names the failing node with whatever `add_node` received —
    `safe_name(id)`, which rewrites every non-alphanumeric character. Every
    *reader* of `outputs` uses the canvas id instead: `_upstream_text`, the
    `update` frame's output lookup, the trace, the final report. Filing the
    failure under the mangled name therefore wrote it where nothing looks, and
    a node that failed after retries read downstream as a node that produced
    nothing — so a grader called it an empty answer and spent its whole retry
    budget re-asking a question the provider had simply refused to answer.

    Invisible to the existing fault tests because every id in them (`n1`)
    survives `safe_name` unchanged; the same collision hid the mounted-output
    defect on the streaming side.

    The map is passed in rather than looked up because this handler is
    installed once per compiled graph and the compiler is the only thing that
    knows the correspondence. An unmapped name falls back to itself, so a stub
    graph built without one behaves exactly as before.
    """

    def handle(_state: dict[str, Any], error: NodeError) -> dict[str, Any]:
        exc = getattr(error, "error", error)
        raw = getattr(error, "node", "unknown")
        node = canvas_ids.get(raw, raw)
        return {"outputs": {node: failure_marker(node, describe_failure(exc))}}

    return handle


def as_our_error(exc: Any) -> "OpenStateGraphError | None":
    """This failure as one of ours, translating a vendor's if we recognise it.

    The one place a foreign exception crosses into our hierarchy. Everything
    downstream then asks the *error* how it reads, rather than each surface
    re-deciding what someone else's `AuthenticationError` means — which is the
    type switch this replaced.

    `None` for a failure we do not recognise. Not a guess: an unrecognised
    exception keeps its own type and message, which is the honest thing to
    show a developer and the same rule `missing_key_diagnosis` follows for an
    unknown provider prefix.
    """
    from openstategraph.chat_model import credential_error_from, unreachable_endpoint_error_from
    from openstategraph.errors import OpenStateGraphError

    if isinstance(exc, OpenStateGraphError):
        return exc
    # Credential first, and the order is not arbitrary: a refusal is judged by
    # status and an unreachable endpoint by address, so the two cannot both
    # claim one exception — but if a vendor ever answered 401 from a host we
    # also recognise, "your key was rejected" is the more specific reading.
    return credential_error_from(exc) or unreachable_endpoint_error_from(exc)


#: LangGraph annotates a propagating exception with the task it died in.
_TASK_NOTE = re.compile(r"During task with name '([^']+)'")


def failing_task_name(exc: Any) -> str | None:
    """Which node an escaped exception died in, or None.

    Needed because a node's `error_handler` is **bypassed** whenever the caller
    streams with `subgraphs=True` or `stream_mode="messages"` — reproduced in
    twenty lines with no model and no compiler, and therefore LangGraph's
    behaviour rather than this project's (`every-workflow-green` 14). The
    editor asks for both, so the one door a developer watches is the one door
    with no net, and it was left showing a provider string and a reference id
    while `/api/runs` said *Node "router1" failed and produced no result*.

    The name is recoverable: LangGraph appends `During task with name 'x' and
    id '…'` as an exception note. **The last such note wins** — they are added
    innermost first, and the outermost is the canvas node, which is the only
    name a reader can act on. An inner `'model'` task is true and useless.

    Returns None rather than guessing. A failure nobody can attribute is still
    better reported as a failure than as a wrong node.
    """
    notes = getattr(exc, "__notes__", None)
    if not isinstance(notes, (list, tuple)):
        return None
    found = [m.group(1) for note in notes if (m := _TASK_NOTE.search(str(note)))]
    return found[-1] if found else None


@dataclass(frozen=True)
class RunHealth:
    """How a run went, in the two categories that are treated differently.

    `failures` are a step that broke while running. They already have a
    customer-facing floor (`RUN_FAILED_ANSWER`) and they are the only kind that
    may reach `cli.run_exit_code` — a run that produced nothing because a node
    died is a failed run.

    `silent` are reports *about how the answer was reached*: a node that ran and
    produced nothing (`every-workflow-green` 01), and a grader that ran out of
    attempts and published a candidate it had rejected (09). Neither is a claim
    that the run failed, and neither may change an exit code.
    """

    failures: list[str]
    silent: list[str]
    #: Whether a grader ran out of attempts and published a candidate it had
    #: rejected — the fact half of `forced_pass_warnings`, split out because
    #: the fact belongs on both audience channels while the *reason* (it can
    #: quote internals) stays developer-only. See `launch-readiness` 25: a
    #: customer-audience run had no field capable of carrying this at all.
    published_rejected: bool = False


def run_health(
    outputs: Any,
    nested_outputs: Any = None,
    forced: Any = None,
    unrouted: Any = None,
    retries: Any = None,
    tool_use: Any = None,
    budget_stops: Any = None,
    published: Any = None,
    answer: Any = None,
) -> RunHealth:
    """The one place a run's health is assembled, for **both** doors.

    `/api/runs` and `/api/runs/stream` each built this themselves and drifted
    twice — a silent node inside a mount reported by one and not the other
    (`every-workflow-green` 16), and a grader that gave up likewise (14). Both
    were found by using the product, because there was nothing for a test to
    hold: the logic existed twice, and a test comparing two implementations
    only ever proves they agree on the day it was written.

    One function cannot disagree with itself. That is the whole argument for
    this existing, and it is why the doors must not reassemble any part of it
    locally — including "just this one extra source", which is exactly how the
    first divergence began.

    Tolerant about its inputs because the two doors read them off different
    shapes: streaming folds them out of frames, `/api/runs` reads finished
    state, and either can hand over `None`.
    """
    flat = outputs if isinstance(outputs, dict) else {}
    nested = nested_outputs if isinstance(nested_outputs, dict) else {}
    exhausted = forced if isinstance(forced, dict) else {}
    lost = unrouted if isinstance(unrouted, dict) else {}
    retried = retries if isinstance(retries, dict) else {}
    # Named `tool_use` because that is its state key — the convention
    # `run_health_from_state` derives the library door from. A source added
    # under any other name goes missing from that door on the day it lands.
    used = tool_use if isinstance(tool_use, dict) else {}
    starved = budget_stops if isinstance(budget_stops, dict) else {}
    exits = published if isinstance(published, dict) else {}
    said = answer if isinstance(answer, str) else ""
    return RunHealth(
        failures=node_failure_warnings(flat) + node_failure_warnings(nested),
        silent=(
            silent_node_warnings(flat, used)
            + silent_node_warnings(nested, used)
            + code_fence_only_warnings(flat)
            + code_fence_only_warnings(nested)
            + forced_pass_warnings(exhausted)
            + step_budget_warnings(starved)
            + unrouted_decision_warnings(lost)
            + retry_warnings(retried)
            + several_exits_warnings(exits, flat)
            + invisible_character_warnings(said, exits, flat)
        ),
        published_rejected=bool(exhausted),
    )


#: The state keys a finished run's health is assembled from — derived from
#: `run_health` itself so the two can never disagree. See
#: `run_health_from_state`.
_HEALTH_SOURCES: tuple[str, ...] = tuple(inspect.signature(run_health).parameters)


def run_health_from_state(state: Any) -> RunHealth:
    """`run_health`, for a door that holds the finished state.

    Every source of run health is a parameter of `run_health` named for the
    state key it is read from, and this reads them **off the signature** rather
    than listing them. That is the whole point: the sources went missing from
    the library door one at a time, once per source added here
    (`workflow-gallery` 49), because each door re-listed them. A door that does
    not list cannot fall behind.

    So the naming convention is load-bearing — a new source must arrive as a
    `run_health` parameter whose name is its state key, and
    `test_the_library_door_reads_the_whole_health_report.py` fails if any door
    stops reading one.

    Tolerant about its input for the same reason `run_health` is: `/api/runs`
    reads finished state, `load_workflow` reads what `invoke()` returned, and
    either can be handed something that is not a mapping at all.
    """
    source = state if hasattr(state, "get") else {}
    return run_health(**{name: source.get(name) for name in _HEALTH_SOURCES})


#: What the shape route of the build door claims, in one sentence, published
#: once (`every-workflow-green` 51).
#:
#: The predicate below implements it and `src/view/ask/doorHeadline.ts` — the
#: card that says it to a developer — quotes it, with
#: `tests/test_the_build_door_opens_on_a_turn_that_called_six_tools.py`
#: failing when the two drift. Before this the docstring on the card was the
#: only statement of the rule, in a different language from the code, with
#: nothing between them; the ticket that found the door open on a turn which
#: had called six tools could not tell from either side whether the rule was
#: per turn or per node.
#:
#: **"anywhere in the turn" is the load-bearing clause.** It is what makes a
#: node the router never reached — an `agent-web` holding the web tools on a
#: run that went to the data branch — not a gap: a node that never ran cannot
#: have declined.
DOOR_SHAPE_RULE = "tools were bound and none were called, anywhere in the turn"


def used_no_tools(tool_use: Any) -> bool:
    """Whether this run had tools available and called none of them.

    The shape route's whole claim, and it is `DOOR_SHAPE_RULE`: *tools were
    bound and none were called, anywhere in the turn*.

    Both halves are load-bearing. A run with **nothing bound** is not a run
    that lacked a capability — a writer agent has no tools by design, and
    "nothing here does this" is not a statement about it. A run with tools it
    never touched is the shape a blocked agent leaves behind.

    Any single use anywhere defeats it: a document whose SQL agent answered and
    whose summariser did not is not a document missing a capability. That is
    the scope word doing its work, and it is per **turn** — this returns
    `False` on the first row carrying a `ran` entry, so no node opens the door
    on its own account.

    What it cannot do is check its own input. `every-workflow-green` 51 is the
    case where this answered correctly about a `tool_use` that had lost a lap:
    the streaming door folded the map with `dict.update` where the channel
    declares `MERGE_ROWS`, and a grader's second lap erased the first lap's
    record of a tool that genuinely ran.

    Tolerant about its input for the same reason `run_health` is — the two
    doors read state off different shapes and either can hand over `None`.
    """
    rows = tool_use if isinstance(tool_use, dict) else {}
    bound = 0
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        bound += len(row.get("bound") or [])
        if row.get("ran"):
            return False
    return bound > 0


#: A SQL statement, as opposed to the English word "select". Both halves are
#: needed and neither is sufficient: `FROM` alone is a preposition, and `SELECT`
#: alone is an imperative verb people write to each other constantly.
#:
#: The span between them may carry `ar.Name` — dotted identifiers are ordinary
#: SQL — but it may not carry a sentence break. That is what separates
#: "SELECT ar.Name, SUM(...) FROM InvoiceLine" from "Select any 3 of the 12
#: playlists; 4 of them are far from complete", which contains both words and
#: is not a query.
_SQL_STATEMENT = re.compile(
    r"\bselect\b[^;:!?]{0,400}?\bfrom\s+[A-Za-z_][\w.]*",
    re.IGNORECASE | re.DOTALL,
)

#: A *figure* — a decimal or a currency amount. Deliberately not "any digit":
#: an id, a row count and a `NVARCHAR(120)` are digits, and a workflow document
#: quoted back as prose is full of them. What this check is about is an answer
#: presenting **results**.
_FIGURE = re.compile(r"(?:[$\u20ac\u00a3]\s*\d[\d,]*(?:\.\d+)?)|(?:\d[\d,]*\.\d+)")


def looks_like_sql_query(text: Any) -> bool:
    """Whether this string contains a SQL statement, not merely the words."""
    return bool(_SQL_STATEMENT.search(str(text or "")))


#: What a run says when the capability its answer depended on never
#: materialised (`launch-readiness` 103).
#:
#: Customer-facing, so it names no node and no tool: which capability failed is
#: a developer fact and `Finding.CAPABILITY_FAILED` already carries it, from
#: `_bind_tools`, on the channel a lost capability has always travelled. What a
#: customer needs is the one thing the refusal could not tell them honestly —
#: that this is not an answer to their question.
CAPABILITY_UNAVAILABLE_ANSWER = (
    "This workflow could not run: a capability it needs was not available, so "
    "the question was never actually answered."
)


def unbound_capability_claim(tool_use: Any, nodes: Any = ()) -> str | None:
    """"This node was drawn capabilities and not one of them exists" — or None.

    `launch-readiness` 103. An agent whose MCP card bound nothing — the server
    was down and tools bind at compile time — answered *"I cannot properly
    answer because this workflow does not have the MCP tools"*, and the
    grader passed it, because a refusal is trivially grounded and
    `BaseGrader`'s refusal clause says an honest decline is a correct answer.
    It is, when the workflow is whole. This is the fact that says it is not.

    Read off the run's own record, with no model call and no string matching
    against *"I cannot"*: nothing upstream is asked to self-report a refusal it
    has every incentive to misreport, and `Correction`-shaped prompt rules have
    been declined on this project six times.

    Three conjuncts, and the narrowness is the safety:

    1. **A drawn capability resolved to nothing.** `unbound` is written by
       `_bind_tools`, which is the only place that knows both the tool nodes
       the canvas wired and what each one actually produced. An agent with
       nothing wired has no key here at all — a writer agent has no tools by
       design, exactly as `used_no_tools` says, and must never be accused.
    2. **That node bound nothing else either.** One capability of two failing
       costs one capability; the agent still holds a working tool and can still
       work. That is the contract `_bind_tools` already advertises.
    3. **No node anywhere bound anything.** Same shape as `unrun_query_claim`'s
       "any query anywhere clears the run": a document whose other agent is
       fully equipped is not a broken run.
    """
    rows = tool_use if isinstance(tool_use, dict) else {}
    if any(isinstance(row, dict) and row.get("bound") for row in rows.values()):
        return None

    named = [str(n) for n in (nodes or []) if str(n) in rows]
    for node_id in named or list(rows):
        row = rows.get(node_id)
        if not isinstance(row, dict):
            continue
        unbound = [str(n) for n in (row.get("unbound") or [])]
        if not unbound:
            continue
        return (
            f'"{node_id}" was wired '
            f"{len(unbound)} {'capability' if len(unbound) == 1 else 'capabilities'} "
            f"({', '.join(unbound)}) and not one of them was available, so "
            "nothing it says is grounded in anything. Retrying cannot make a "
            "capability appear — repair the capability, or draw a different one."
        )
    return None


def unrun_query_claim(candidate: str, tool_use: Any, nodes: Any = ()) -> str | None:
    """"This answer shows a query nothing ever sent" — or None.

    `production-ready` 95. `chinook-assistant`'s analyst answered *"top artists
    by revenue"* with a ten-row table and a `SELECT` beside it, having listed
    the tables, read two schemas, and never called `chinook_execute_sql`. Eight
    live runs, eight skipped queries. The figures were right to the cent, which
    is what parametric recall of a famous public fixture produces — and the
    model grader's *"the provided figures appear invented"* was accurate rather
    than a guess. This is that same rejection reached as a **fact**, off the
    run's own `tool_use`, with no model call.

    The class generalises past this package — any agent that cites evidence it
    never gathered is the same defect — and the narrowness is the safety. Four
    conjuncts, every one of them load-bearing:

    1. **The candidate contains a SQL statement**, by `_SQL_STATEMENT` above.
    2. **It presents figures** — two or more decimals or currency amounts. An
       honest decline that shows the query you *would* need has none, and
       rejecting a decline is a failure this repository has already paid for
       once (see `BaseGrader.PROMPT`'s refusal clause).
    3. **A node investigated and stopped short** — it ran at least one tool and
       left at least one bound tool untouched. A node that ran *nothing* is a
       capability report and belongs to `used_no_tools`/`capability_door`; that
       is the same `ran`-versus-`bound` split `production-ready` 96 drew, and
       it is why a scripted agent that calls no tools is never accused here.
    4. **No node in the run sent a query to anything.** This is the conjunct
       that needs no tool-name heuristic: `tool_use[node]["queried"]` names the
       tools a `SELECT` was actually handed to, whatever they are called. Any
       query anywhere clears the whole run — a document whose second agent did
       the reading is not one citing evidence it never gathered.

    Tolerant in reading, strict in trusting: the shapes are read leniently, and
    the rejection is only ever made about a run whose own record says the query
    never left the building.
    """
    rows = tool_use if isinstance(tool_use, dict) else {}
    if any(
        isinstance(row, dict) and row.get("queried") for row in rows.values()
    ):
        return None

    text = str(candidate or "")
    if not looks_like_sql_query(text):
        return None
    if len(_FIGURE.findall(text)) < 2:
        return None

    named = [str(n) for n in (nodes or []) if str(n) in rows]
    considered = named or list(rows)
    for node_id in considered:
        row = rows.get(node_id)
        if not isinstance(row, dict):
            continue
        ran = [str(n) for n in (row.get("ran") or [])]
        unused = [str(n) for n in (row.get("bound") or []) if str(n) not in ran]
        if ran and unused:
            return (
                f'The answer presents figures from a SQL query, but "{node_id}" '
                f"ran {', '.join(ran)} and never called {', '.join(unused)}. "
                "Run the query and quote its rows, or say the data is unavailable."
            )
    return None


def values_no_statement_carried(state: Any, values: Any) -> frozenset[str]:
    """Which of `values` appear in **no statement this run executed** — `155`.

    The third reader of the run's own record, and the one that answers a claim
    rather than a suspicion. `127`'s disclosure says *"the answer above is for
    Middle East Gulf (MEG) on `load_shipping_region_v2`"* — a claim that a
    result was obtained on that axis, for that value. The note carries no such
    knowledge: `resolve.vocabulary` mints it when it **resolves the word**,
    before the model runs. Nothing between there and `_output` asked whether
    the run went on to use it, and live on 2026-08-28 a run that answered
    nothing carried the sentence anyway.

    What settles it is not the prose. The live non-answer names the canonical
    value itself (*"location → MEG"*), so a search of the answer would have
    passed exactly the run this exists for; and asking the model whether it
    used the resolution is the thing `127` was filed to stop relying on.

    The evidence for *"the answer is for this value"* is a statement that
    carried it **and came back with data**, and `counted_rows` holds both
    halves already: `exchanges_in`, every statement this run executed on both
    rails — the agent's own `tool_use[node]["queries"]` and the message rail a
    node-run query leaves behind — and `cells_of`, whose settled rule is that
    *"a payload that declares itself unsuccessful contributes nothing at
    all"*.

    That second half was learned live, three runs in, and no fixture would have
    taught it. Every refusal measured on 2026-08-29 had **sent** a statement
    carrying the value and been answered `{"ok": false}` by the warehouse — an
    invalid column, twice — and then published *"the answer above is for
    Middle East Gulf (MEG)"* over *"I was unable to determine…"*. A statement
    nobody answered is not a result.

    A value **found** is dropped from the result, so the default is `127`'s
    sentence and this only ever subtracts a claim. Matching is a case-folded
    containment, which errs the same way: a value that matches loosely is
    treated as used, and the reader gets exactly the paragraph they got before.

    **And it says nothing at all about a run with no statement rail.** A record
    showing neither an executed statement nor a bound capability is one this
    cannot speak about — a writer that resolved a term and wrote about it has
    no statements to be missing from — so nothing is subtracted and `127`'s
    sentence stands. That gate is what keeps this off correct work (`133`); it
    is not a guess about what such a run did.

    Two resolutions of one word are the case that makes this per-value rather
    than per-run. *"Persian Gulf"* is genuinely live on two axes in the same
    warehouse — a shipping region and a chokepoint geofence — and a run that
    queried one of them was, before this, disclosed as being *"for"* both.
    """
    from openstategraph.counted_rows import exchanges_in, statement_was_answered

    wanted = [str(v) for v in (values or ()) if str(v).strip()]
    if not wanted:
        return frozenset()
    record = state if isinstance(state, Mapping) else {}
    executed = exchanges_in(record)
    if not executed:
        rows = record.get("tool_use") or {}
        rows = rows if isinstance(rows, dict) else {}
        if not any(isinstance(row, dict) and row.get("bound") for row in rows.values()):
            return frozenset()
    answered = " \n".join(
        sql for sql, result in executed if statement_was_answered(result)
    ).casefold()
    return frozenset(v for v in wanted if v.casefold() not in answered)


def capability_door(answer: str, suggestion: Any, tool_use: Any) -> str | None:
    """What a developer is offered to *build*, or None — one verdict, both doors.

    `every-workflow-green` 35. `advisor_context` requires the block whenever an
    agent is blocked, and the same question on the same workflow emitted it on
    one run and not the next. Escalating the wording had already been tried
    twice; each round changed the rate and none removed the failure, which is
    the signature of the wrong lever.

    So there are two routes to the door and the model owns only one of them:

    1. **What it said.** A decline carries a `reason`, and that sentence is the
       only description anyone has of what the user actually wanted. It wins
       whenever it exists — the shape can never be as good as it.
    2. **How the run went.** Failing that, a run that had tools and used none
       is offered the door anyway. It needs no cooperation, no second model
       call, and no parsing of prose.

    Route 2 cannot know a refusal from a knowledge answer, and that limit is
    deliberately pushed into the *card* rather than papered over here: an empty
    string means "the shape says so, nobody said what", and `AskPanel` renders
    words that claim only that. A gap the model described stays a claim about
    the gap; a gap the shape inferred stays a claim about the run.

    A placeable suggestion closes both routes. A gap something in the catalogue
    covers is an Add & re-run card, not an interview (ticket 34).

    Lives here, beside `run_health`, and for the identical reason: `/api/runs`
    and `/api/runs/stream` each asked this question locally and the pair has
    already drifted twice (14, 16). One function cannot disagree with itself.
    """
    from openstategraph.developer_channel import capability_gap

    if suggestion is not None:
        return None
    described = capability_gap(answer or "")
    if described is not None:
        return described
    return "" if used_no_tools(tool_use) else None


#: Our own refusal, written by the agent runtime when a model calls a name it
#: was never given: "web_fetch is not a valid tool, try one of [...]".
#:
#: `\S+` rather than an identifier class, because the whole point of this
#: sentence is that the name is one **the model made up**, and a made-up name
#: is not obliged to look like an identifier. `production-ready` 98: a live run
#: asked for `execute_sql?`, the `?` fell outside `[A-Za-z0-9_.-]`, the
#: refusal the runtime had just written about itself did not match, and
#: `tool_report` filed the invented name under `ran` — where three readers take
#: it to mean the node did the work. The narrowness that matters is the
#: sentence, not the character class: prose merely mentioning a tool still
#: matches nothing.
_REJECTED_TOOL = re.compile(r"(\S+) is not a valid tool")


def rejected_tool_names(text: Any) -> list[str]:
    """Tool names the runtime refused, in the order they were asked for.

    This is the signal that was sitting in plain text while two rounds of
    prompt wording tried to persuade a model to announce the same thing
    (`every-workflow-green` 33). The agent asked for `web_fetch`, we shipped
    `tool.web-fetch`, and nothing offered it.

    Deliberately narrow. A tool that **ran and returned an error** is wired,
    and re-suggesting it is the defect
    `the-agent-asks-for-what-it-cannot-get` 01 exists to stop — so only this
    one sentence, which the runtime itself writes, counts as a rejection.
    Prose that merely mentions a tool name is not one.
    """
    if not isinstance(text, str) or not text:
        return []
    seen: list[str] = []
    for name in _REJECTED_TOOL.findall(text):
        if name not in seen:
            seen.append(name)
    return seen


def _invocation_error_pattern() -> "re.Pattern[str] | None":
    """A matcher for LangGraph's own bad-arguments sentence, built from LangGraph's
    own format string rather than from a copy of one.

    `CLAUDE.md`: *"a detector keyed on error prose will rot"*. This one is keyed
    on `TOOL_INVOCATION_ERROR_TEMPLATE` — the single constant the library
    formats when `ToolNode` raises `ToolInvocationError`, which it does at
    exactly one moment: **after** the arguments fail their `args_schema` and
    **before** `tool.invoke` is ever called. Reword the template upstream and
    this pattern is reworded with it; the only way it can rot is the library
    dropping the constant, and then we return `None` and claim nothing.

    Note the sibling it must never match: `TOOL_EXECUTION_ERROR_TEMPLATE` says
    *executing* where this one says *invoking*, and that is the library drawing
    the same line this function needs — a body that ran and threw, versus a
    body that never ran.
    """
    try:
        from langgraph.prebuilt.tool_node import TOOL_INVOCATION_ERROR_TEMPLATE
    except Exception:  # pragma: no cover - the library moved the constant
        return None
    parts = re.split(r"\{(tool_name|tool_kwargs|error)\}", TOOL_INVOCATION_ERROR_TEMPLATE)
    groups = {
        "tool_name": "(?P<tool_name>.+?)",
        "tool_kwargs": "(?:.*?)",
        "error": "(?:.*)",
    }
    pattern = "".join(
        groups[part] if index % 2 else re.escape(part) for index, part in enumerate(parts)
    )
    return re.compile(pattern, re.DOTALL)


_INVOCATION_ERROR = _invocation_error_pattern()


def arguments_were_rejected(text: Any, tool_name: Any) -> bool:
    """Whether this tool result says the **arguments** were refused, so the
    tool's body never ran.

    `production-ready` 100. `queried` is 95's evidence that a query left the
    building, and it is read off the *call* arguments — which exist whether or
    not anything accepted them. A model that calls a real, bound
    `chinook_execute_sql` with `sql=` instead of `query=` gets a `ToolMessage`
    under the tool's own name, so the call looked, to `tool_report`, exactly
    like a query that had been sent. It had not been: Pydantic rejected it and
    the database was never opened. Any `queried` anywhere clears
    `unrun_query_claim` for the whole run, so the fabricated answer that
    followed went unchallenged.

    Deliberately narrow, in the direction 98 named. The failure this guards is
    a **miss**, not a false accusation, so every ambiguity resolves towards
    still counting the query:

    - `fullmatch`, so the sentence has to *be* the message. An answer quoting
      it — this product prints machinery as prose constantly — is not one.
    - The sentence names its own subject, and the subject has to be the tool
      that answered. That is the check 98 had to add to the refusal sentence
      for the same reason.
    - A tool that ran a query and *then* failed still counts. "Errored" and
      "never executed" are different things, and confusing them re-breaks
      `the-agent-asks-for-what-it-cannot-get` 01, where an error is data.
    """
    if _INVOCATION_ERROR is None or not isinstance(text, str) or not text:
        return False
    match = _INVOCATION_ERROR.fullmatch(text)
    return bool(match and match.group("tool_name") == str(tool_name or ""))


def suggestible_node_type(tool_name: str, registry: Any) -> str | None:
    """The node type a rejected name could be placed as, or None.

    None is a real answer and the important one: a name no shipped tool carries
    — `slack_post` — must offer nothing rather than the nearest entry, which is
    exactly the wrong turn ticket 29 removed.

    Gated by the same `SUGGESTIBLE_TOOL_PREFIXES` the advisor's catalogue uses,
    so a tool that may not be placed by a card is not placed by this path
    either. One rule, two readers.
    """
    from openstategraph.api.registries import SUGGESTIBLE_TOOL_PREFIXES

    if not tool_name or not isinstance(registry, dict):
        return None
    for node_type, tool in registry.items():
        if not str(node_type).startswith(SUGGESTIBLE_TOOL_PREFIXES):
            continue
        if str(getattr(tool, "name", "")) == tool_name:
            return str(node_type)
    return None


def suggestion_from_rejection(unmet: Any, registry: Any = None) -> dict[str, Any] | None:
    """A capability offer built from what the run recorded, not from the model.

    The card has always come from a fence the model chose to write. That works
    when it cooperates and fails silently when it does not — and it did not, in
    the case this exists for: the agent called `web_fetch`, the runtime refused
    it **by name**, `tool.web-fetch` was in the catalogue, and the user was
    shown nothing (`every-workflow-green` 33).

    A **fallback, never an override**. A model that emitted a suggestion knows
    more about its own situation than a name lookup does — it can propose a
    tool it never got as far as calling — so ticket 15's card keeps winning and
    this only fills the silence.

    Declines by returning None rather than reaching for the nearest entry: a
    name no shipped tool carries offers nothing, which is the wrong turn ticket
    29 removed and must not come back through a different door.
    """
    if not isinstance(unmet, dict) or not unmet:
        return None
    if registry is None:
        # The shipped set, which is the whole of what may be *placed by a card*
        # anyway — `SUGGESTIBLE_TOOL_PREFIXES` excludes a package's own
        # `tools/`, since those already exist in the package that declares
        # them. So resolving without a slug loses nothing this path could
        # offer, and saves threading a registry through two API doors.
        from openstategraph.api.registries import build_tool_registry

        registry = build_tool_registry(None, None)
    for node_id, names in unmet.items():
        if not isinstance(names, (list, tuple)):
            continue
        for name in names:
            node_type = suggestible_node_type(str(name), registry)
            if not node_type:
                continue
            return {
                "nodeType": node_type,
                "attachTo": str(node_id),
                "port": "tools",
                "label": node_type.removeprefix("tool.").replace("-", " ").title(),
                "reason": (
                    f"This step asked for `{name}`, which it does not have. "
                    f"`{node_type}` provides it."
                ),
            }
    return None


def describe_failure(exc: Any) -> str:
    """One line for a **developer**, from an exception.

    Our own errors are already the copy — `MissingProviderKey` exists to carry
    a sentence naming the variable and the fix, so prefixing it with its own
    class name adds a Python identifier to a message written for someone who
    may not be reading Python (ticket 04).

    A foreign exception we cannot place keeps its type, because there the type
    is most of the information: `ConnectError` and `AuthenticationError` say
    genuinely different things about what to do next, and neither says so in
    its message.
    """
    from openstategraph.providers import redact_known_secrets

    ours = as_our_error(exc)
    if ours is not None:
        return ours.developer_message()
    # A vendor's own exception sometimes quotes the key back. Everything this
    # project prints should be safe to paste into an issue, and that cannot
    # depend on each vendor choosing to redact for us.
    return redact_known_secrets(f"{type(exc).__name__}: {exc}")


def describe_failure_for_customer(exc: Any) -> str:
    """The same failure, for someone who cannot act on it.

    Polymorphic rather than a branch here: the error decides, and the base
    class's default is the generic sentence, so a new error type cannot leak a
    variable name to a customer by forgetting to override anything. An
    unrecognised exception gets that same default — never its own text, which
    is how "RuntimeError: the checkpointer is gone" was reaching customers.
    """
    from openstategraph.errors import GENERIC_FAILURE_MESSAGE

    ours = as_our_error(exc)
    return ours.customer_message() if ours is not None else GENERIC_FAILURE_MESSAGE


#: How a failed node's output is written, and the only place it is spelled.
#:
#: Reader and writer are kept together on purpose. The last time they were
#: apart — the failure filed under `safe_name(id)` while every reader looked up
#: the canvas id — a node that failed read downstream as a node that produced
#: nothing, and a grader spent its whole retry budget re-asking a question the
#: provider had refused to answer. See `_error_handler_for` above.
_FAILURE = "[{node} failed after retries: {message}]"
_FAILURE_PATTERN = re.compile(r"^\[(?P<node>.+?) failed after retries: (?P<message>.*)\]$", re.S)


def failure_marker(node: str, message: str) -> str:
    """The text a failed node publishes as its output."""
    return _FAILURE.format(node=node, message=message)


#: What a failed step says to someone who cannot fix it.
#:
#: No variable, no provider, no file — that is developer guidance, and the
#: audience boundary exists to keep it off a customer surface. Says what
#: happened and who can act, and invents nothing about why.
CUSTOMER_STEP_FAILED = "This step did not complete."

#: The answer a run gives when a step failed before one was produced.
#:
#: `node_runtime`'s never-blank floor already covers a run that *reaches* the
#: output node with nothing. It cannot cover this: when an upstream node
#: fails, the output node never runs at all — verified, `outputs` contains no
#: entry for it — so the floor beneath every route to that node is not a floor
#: beneath every run (providers-and-credentials ticket 04).
RUN_FAILED_ANSWER = GENERIC_FAILURE_MESSAGE


def parse_failure_marker(text: str) -> str | None:
    """The reason inside a failure marker, or `None` if this is not one.

    The pattern had three readers inside this module and none outside it, so
    `RunResult.failed_nodes` — the door where a caller most needs to tell a
    sentinel from content — would have had to match the shape a fourth time.
    A marker's shape is knowledge, and knowledge is duplicated once too often
    the moment it is spelled out twice.
    """
    match = _FAILURE_PATTERN.match(text)
    return None if match is None else str(match["message"])


def redact_failure_markers(outputs: Mapping[str, Any]) -> dict[str, Any]:
    """`outputs` with every failure marker replaced, for a customer.

    The marker is written for whoever can set an environment variable, and
    `outputs` is rendered per node on every surface — so without this it
    reached a customer reading "set OLLAMA_API_KEY in .env", which is the
    boundary `tests/test_audience_boundary.py` exists to hold.
    """
    return {
        node: (
            CUSTOMER_STEP_FAILED if parse_failure_marker(str(value or "")) is not None else value
        )
        for node, value in outputs.items()
    }


def node_failure_warnings(outputs: Mapping[str, Any]) -> list[str]:
    """Failed nodes, as developer-channel warnings.

    `outputs` is where a failure lands so that downstream nodes still have
    *something* to read — but every surface renders that map as each node's
    **output**, so on its own a credential failure arrived looking like an
    answer, and the run reported 200 with a blank `answer` and an empty
    developer channel (providers-and-credentials ticket 04).

    Reported here rather than raised: the run genuinely did complete, other
    nodes genuinely did produce results, and this is the same "a step lost a
    capability" shape that `api.registries.runtime_warnings` already carries.
    """
    warnings: list[str] = []
    for node, value in outputs.items():
        reason = parse_failure_marker(str(value or ""))
        if reason is not None:
            # A full stop, not a dash: the message that follows carries its own
            # em-dash ("… no credential — set X"), and two in one sentence read
            # as one run-on rather than as a cause and its fix.
            warnings.append(f'Node "{node}" failed and produced no result. {reason}')
    return warnings


def silent_node_warnings(
    outputs: Mapping[str, Any], tool_use: Any = None
) -> list[str]:
    """Nodes that ran and produced nothing.

    Seen on three workflows while walking them (`every-workflow-green` 01):
    `two-stage-double-loop/draft1`, `archetype-orchestrator-report/
    worker-research#task-1`, `chinook-assistant/agent-sql`. Every time the run
    reported success and every surface showed a confident answer.

    It survives because `answer` uses the `LATEST_NONEMPTY` reducer, so a node
    producing nothing leaves the previous value standing and everything
    downstream reads a **stale** answer as fresh. That reducer is right — it is
    what lets a grader's forced pass have something to hand on — and is not the
    bug. The silence is.

    **Separate from `node_failure_warnings`, deliberately.** That function's
    output feeds `cli.run_exit_code`, where a warning plus an empty answer means
    a failed run. But this project's stated rule is that *"a workflow may
    legitimately answer with nothing at all"*
    (`test_a_failed_run_is_not_a_silent_success`), so folding this in flipped
    that exit code. A silent node is a **report about how the answer was
    reached**, not a claim that the run failed, and the two must not share a
    channel that a script gates on.

    **`tool_use` splits the silence into the two reports it always was**
    (`production-ready` 96). A node that never got started and a node that
    called three tools, read their results, and then had its model end the turn
    without writing anything are opposite situations with opposite fixes, and
    until this they were the same sentence. The second was measured off the raw
    Ollama wire — `content=''`, `thinking=None`, `tool_calls=None`,
    `done_reason='stop'` — so nothing is being lost in extraction and there is
    no channel to widen towards; the model genuinely stopped, and the only
    defect left is a report that cannot say so.

    Read from `tool_use[node]["ran"]`, which `tool_report` writes on every run
    including the empty one. **`ran`, never `bound`**: an agent with tools it
    never touched is a *capability* report with its own door (`used_no_tools`),
    and borrowing this sentence for it would say a loop got somewhere it never
    reached.

    Optional, and tolerant about its shape, for the reason `run_health` is: the
    doors read state off different shapes and any of them can hand over `None`.
    A caller that passes nothing gets exactly the sentences it got before.
    """
    used = tool_use if isinstance(tool_use, Mapping) else {}
    warnings: list[str] = []
    for node, value in outputs.items():
        text = str(value or "").strip()
        if text == NO_MODEL_MARKER:
            # The two are different questions with different fixes — "the
            # model answered with nothing" is a run to re-try, "no model was
            # configured" is a setting to change — and they arrived at every
            # surface as the same sentence (`workflow-gallery` 18).
            warnings.append(
                f'Node "{node}" had no model configured, so it never called one '
                "and produced nothing. Set a model on the node or a default for "
                "the workflow."
            )
        elif not text:
            # A dispatched member of a fan-out, whose key `_worker` writes as
            # `<node>#<task>` — the only producer of a `#` in `outputs`
            # (`workflow-gallery` 52). Two things follow, and both were wrong
            # before. The tool lookup has to use the *node* half, because
            # `tool_report` keys by node id and every dispatched instance
            # shares one, so 96's split missed on every member and a worker
            # could never say its loop had worked. And the sentence has to
            # stop claiming a stale answer is being read: a member's silence
            # leaves a gap in one section of the report, it does not leave the
            # previous `answer` standing, so sending a reader upstream sends
            # them to the wrong place.
            member = node.split("#", 1)[1] if "#" in node else ""
            owner = node.split("#", 1)[0]
            record = used.get(owner)
            ran = record.get("ran") if isinstance(record, Mapping) else None
            names = [str(name) for name in ran] if isinstance(ran, (list, tuple)) else []
            if member:
                # A worker reaches here only after calling a model — its
                # no-model branch writes `NO_MODEL_MARKER` and is handled
                # above — so "its model ended the turn" is measured, not
                # inferred. What the model did on that turn was settled off
                # the raw wire in `production-ready` 96: it genuinely stopped.
                sentence = (
                    f'Member "{member}" of node "{owner}" ran and its model ended the '
                    "turn without writing anything, so that section of the report is "
                    "empty."
                )
                if names:
                    # Attributed to the node and to the run, never to this
                    # member: `tool_use` is per node, and a sibling subtask's
                    # call would otherwise be reported as this one's.
                    sentence += f' The node called {", ".join(names)} during this run.'
                warnings.append(sentence)
            elif names:
                warnings.append(
                    f'Node "{node}" ran {", ".join(names)} and then ended its turn '
                    "without writing an answer. The run continued with the previous "
                    "answer, so what you are reading came from an earlier step."
                )
            else:
                warnings.append(
                    f'Node "{node}" produced no output. The run continued with the previous '
                    "answer, so what you are reading came from an earlier step."
                )
    return warnings


#: A fenced code block — three backticks, an optional language tag, and
#: everything up to the closing three backticks. Not a single inline
#: backtick span, which is ordinary prose ("run `sql_query` yourself") and
#: not the shape this exists to catch.
_FENCED_CODE_BLOCK = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


def code_fence_only_warnings(outputs: Mapping[str, Any]) -> list[str]:
    """Nodes whose whole answer is fenced code, with no prose anywhere else.

    Seen live (`launch-readiness/35`): `sql-qa`'s agent, six live runs of the
    same question, printed the answer and its SQL five times and **only the
    SQL** once — no artist, no figure. Exit code 0, `"attempts": 1`,
    `warnings: []`; the node's own `rules` already asked for a sentence
    before the fence and the model skipped it anyway.

    `silent_node_warnings` does not see this: its whole test is
    `not text.strip()`, and a fenced ```sql block is *plenty* of non-empty
    text. This is the other half of the same silence — a node that answered
    with evidence and no verdict — and it needs its own check because "text
    is present" is exactly what let it slip past every existing report.

    **Never a claim the run failed.** A workflow whose entire job is to hand
    back a snippet ("write me a SELECT for this") legitimately answers with
    only a fenced block, and this function cannot tell that case from
    `sql-qa`'s by the text alone — so, like `silent_node_warnings`, it only
    ever adds a report to `RunHealth.silent`, never to `.failures`, and never
    changes an exit code.

    Deliberately narrow, the same way `looks_like_sql_query` is: only a
    genuine triple-backtick fence counts, and only when stripping every fence
    out of the text leaves nothing behind. A sentence before or after a fence
    — the ordinary, five-out-of-six shape — is left alone. Empty output is
    `silent_node_warnings`'s shape, not this one, so it is skipped here
    rather than reported twice under two different sentences.
    """
    warnings: list[str] = []
    for node, value in outputs.items():
        text = str(value or "").strip()
        if not text or "```" not in text:
            continue
        remainder = _FENCED_CODE_BLOCK.sub("", text).strip()
        if not remainder:
            warnings.append(
                f'Node "{node}" answered with only a fenced code block — no '
                "prose anywhere else. The code is evidence for an answer, not "
                "the answer itself; a reader who cannot read it received "
                "nothing."
            )
    return warnings


def forced_pass_warnings(forced: Mapping[str, Any]) -> list[str]:
    """Graders that ran out of budget and passed a candidate they rejected.

    Seen live (`every-workflow-green` 09): `chinook-assistant` answered its own
    documented question with a raw table schema. The grader rejected it three
    times, the attempts budget ran out, and the third rejection was force-passed
    and published. Nothing said so — "the grader approved this" and "the grader
    gave up" looked identical.

    **The pass is correct and is not changed.** `_grader` argues it: a loop that
    cannot finish is worse than a mediocre answer, and a candidate the grader
    merely disliked is still what the workflow produced. Only the silence is
    the defect.

    **"The review at", not "Grader"** (`launch-readiness/167`). A `guard.check`
    hits the identical ceiling and now writes this identical key, and it is not
    a grader — it calls a package function and never a model. One sentence that
    names one of the two families would be false about the other every time it
    fired, which is the defect this whole map is about. `route.grader` and
    `guard.check` both *review* a candidate, so that is the word.

    Not carried on `decisions`, because the compiler routes on that exact label
    and a new value there would change control flow. Hence its own state key,
    and this function beside `silent_node_warnings` — same channel, same
    reason, and deliberately **not** part of `node_failure_warnings`, which
    feeds `cli.run_exit_code`. A force-pass is a report, not a failed run.
    """
    return [
        f'The review at "{node}" ran out of attempts and published an answer it had '
        f"rejected. Its last reason: {str(reason).strip() or 'none given'}"
        for node, reason in forced.items()
    ]


def step_budget_warnings(budget_stops: Mapping[str, Any]) -> list[str]:
    """Loops that stopped because the workflow ran out of **supersteps**.

    `organisms-first-class` 56. Before this, a cycle whose grader never
    relented simply raised `GraphRecursionError`: the answer the workflow had
    already produced was thrown away, the HTTP door answered `502`, and the
    CLI printed LangGraph's own advice to raise the number — which is the
    opposite of what this product's own step-budget copy says.

    **The pass is correct and is not the news.** It is the identical
    publication `forced_pass_warnings` argues for: a loop that cannot finish
    is worse than a mediocre answer, and the candidate is still what the
    workflow produced. Only the silence would be the defect.

    A separate sentence from the force-pass because a reader's next move is
    different. `maxAttempts` is a number on one grader's card; the step budget
    is a number on the *workflow*, and it is the drawing's shape — how many
    nodes a lap crosses — that decides what it buys. Raising it is deliberately
    **not** the advice: `resolve_step_budget` already says a bigger number only
    lets a loop that cannot settle run longer.

    Vocabulary is fixed by `CLAUDE.md`: **step budget** and **supersteps**,
    never "iterations" or "max turns" — one lap with fan-out costs several
    supersteps, so a count of laps would be a different, wrong number.

    On the **silent** channel and not `node_failure_warnings`, which feeds
    `cli.run_exit_code`: the run completed, took its own wired `pass` edge and
    published. This is a report about how the answer was reached.
    """
    lines: list[str] = []
    overruled: list[dict[str, Any]] = []
    for node, value in budget_stops.items():
        remaining, records = read_budget_stop(value)
        lines.append(
            f'The review at "{node}" stopped revising because the workflow\'s step budget '
            f"was nearly spent ({remaining} supersteps left), and published the "
            "answer it had. A cycle costs one superstep per node on it, so this "
            "loop could not run to its own attempts cap."
        )
        for record in records:
            if record not in overruled:
                overruled.append(record)
    # And, once per package rather than once per stop, the field that could not
    # be honoured (`organisms-first-class` 62). Deliberately not one sentence
    # per grader and not one per mount: the same package mounted three times
    # saved the number once, so saying it three times would be noise about a
    # single decision. Only reached when the ceiling actually bit — a package
    # that asked for less, or asked for more and finished comfortably, records
    # nothing here and is told nothing.
    lines.extend(
        f'The mounted workflow "{record.get("workflow")}" saved a step budget of '
        f'{record.get("requested")} supersteps, and a mount may only ask for less '
        f'than the run\'s — this run allowed {record.get("allowed")}. That smaller '
        "ceiling is what the loop above was measured against."
        for record in overruled
    )
    return lines


def invisible_character_warnings(
    answer: Any, published: Mapping[str, Any], outputs: Any
) -> list[str]:
    """What publication removed from the answer — `osg-agent-experience/87`.

    A model emitted a run of zero-width spaces inside a pair of parentheses and
    the reader saw empty brackets. `compile.state.published_answer` now removes
    them, and a rewrite nobody is told about is its own defect: a developer
    reading the answer is reading text the machinery changed.

    `silent` rather than `failures`, and developer-only, for the reasons the
    two functions either side of this one give — it is a report about how the
    answer was reached rather than a claim the run failed, and it is not the
    customer's vocabulary. It says a count and nothing else: naming the code
    points would put them back into a surface somebody reads.

    Only when something was actually removed. Every clean run is the ordinary
    run, and a channel that speaks on the happy path is one people learn to
    skip.
    """
    from openstategraph.compile.state import invisible_characters_removed

    rows = published if isinstance(published, Mapping) else {}
    removed = invisible_characters_removed(
        {"answer": answer, "published": dict(rows), "outputs": outputs}
    )
    if removed < 1:
        return []
    plural = "" if removed == 1 else "s"
    return [
        f"The answer carried {removed} invisible formatting character{plural} "
        "(zero-width or byte-order marks, which a reader cannot see but a copy "
        "or a grep carries); they were removed before it was published."
    ]


def several_exits_warnings(published: Mapping[str, Any], outputs: Any) -> list[str]:
    """Runs in which more than one Output node finished — `launch-readiness/174`.

    `matchMode: "all"` is the platform's own parallel-router feature and its
    field hint invites the drawing: a desk on each branch, an Output on each
    desk. Both desks then run, both Outputs finish, and `answer` is
    `LATEST_NONEMPTY`, so one of the two answers used to be kept and no door
    said the other had been produced. Nine live runs across two documents.

    **The answer is no longer the silence's other half**: `published_answer`
    joins the exits, so nothing is withheld from the reader any more. What
    stays worth saying is that the answer arrived in parts and *which* nodes
    made them — a fact about the drawing, which is what this channel carries.

    Hence `silent` rather than `failures`, and hence the developer channel
    rather than both audiences. `published_rejected` is on both because a
    customer handed a rejected answer has a fact they cannot otherwise learn;
    a customer handed both halves has lost nothing, and node ids are not their
    vocabulary (`launch-readiness/25`).

    The author's own title leads where there is one, because that is the word
    on the card. The node id follows it either way — this sentence is read by
    someone about to go and look at the drawing.
    """
    rows = published if isinstance(published, Mapping) else {}
    from openstategraph.compile.state import published_exits

    finished = published_exits({"published": dict(rows), "outputs": outputs})
    if len(finished) < 2:
        return []

    def named(node_id: str) -> str:
        row = rows.get(node_id)
        title = str(row.get("title") or "").strip() if isinstance(row, Mapping) else ""
        return f'"{title}" ({node_id})' if title else f'"{node_id}"'

    return [
        "This run finished at more than one Output and every answer is "
        f"published, joined in the order they are drawn: {', '.join(named(n) for n, _ in finished)}."
    ]


def unrouted_decision_warnings(unrouted: Mapping[str, Any]) -> list[str]:
    """Decisions that were made, understood, and had nowhere to go.

    A grader whose `revise` port is unwired still decides `revise`. The
    conditional edge is built from the destinations that were *drawn*, so
    `_router_for` finds no `revise` among them and falls back to the first
    declared one — `pass`. The answer the grader rejected then reaches the
    output with `decisions {"grader1": "revise"}` sitting beside it and
    nothing saying the verdict went nowhere (`workflow-gallery` 31).

    **The fallback is correct and is not changed.** Its own argument holds
    for a *missing* decision: "a stall here would be a hang, not an error".
    (`support-triage` used to rely on it deliberately to reach its human gate;
    `workflow-gallery` 78 wired its `revise` edge, so it no longer does — the
    fallback itself is unchanged and still exists for the genuinely-missing
    case.) Only the silence is the defect, and only for the case the fallback
    was never arguing about — a decision that exists and names a branch
    nobody wired.

    Its own state key rather than a `decisions` value, for the reason
    `forced_pass_warnings` records: the compiler dispatches on that exact
    label, so a third one there would change control flow. And beside
    `silent_node_warnings` rather than inside `node_failure_warnings`, which
    feeds `cli.run_exit_code` — the run genuinely completed and genuinely
    produced the answer it published. This is a report about how that answer
    was reached.
    """
    return [_unrouted_sentence(str(node), label) for node, label in unrouted.items()]


def unrouted_record(branch: str, *, stopped: bool) -> dict[str, Any]:
    """What a **routing** node writes into `unrouted` (`osg-agent-experience/80`).

    A grader writes the bare label and still does: its sentence has one ending
    — the answer shipped anyway — because a grader's unwired `revise` cannot
    change where the run goes. A router's can, and now does: it either takes
    the declared fallback or stops the run at the node. A reader needs to know
    which, and the bare label cannot say.

    Two shapes in one state key rather than a second key beside it, for the
    reason `forced` and `unrouted` both record: another channel is the move
    this project keeps deciding not to make, and every door already carries
    this one.
    """
    return {"branch": branch, "stopped": stopped}


def _unrouted_sentence(node: str, label: Any) -> str:
    """One row of the report, in the vocabulary of whoever lost the verdict."""
    if isinstance(label, Mapping):
        branch = str(label.get("branch") or "").strip() or "a branch"
        ending = (
            "so the run stopped there — wire that branch, or name a fallback"
            if label.get("stopped")
            else "so the run took the declared fallback instead"
        )
        return (
            f'Routing node "{node}" decided "{branch}" and no edge leaves that branch, {ending}.'
        )
    return (
        f'Grader "{node}" asked for a {str(label).strip() or "different branch"} and no '
        f"such edge was wired, so the answer shipped as-is."
    )


#: The state key a recovered retry is recorded under. Named here rather than
#: spelled at each site because it is one word in four places: the schema, the
#: wrapper below, `run_health`'s parameter list, and the resume seed.
RETRIES_KEY = "retries"


def recording_attempts(node_id: str, fn: Any) -> Any:
    """`fn`, wrapped so a **recovered** retry leaves a record in state.

    Here, at graph assembly, and deliberately not in any node factory. Retry is
    a graph-assembly parameter and not a node concern (`CLAUDE.md`), so the one
    place that knows a node has a `retry_policy` is the one place that reports
    the policy firing — otherwise every node family reimplements it and one of
    them forgets, which is how `_agent` got a fix that `_worker` did not
    (`skills/ticket-loop`, ticket 33).

    The attempt number comes from LangGraph itself.  `run_with_retry` patches
    `node_attempt` into the runtime's `ExecutionInfo` before every attempt
    (`pregel/_retry.py`), 1-indexed, so a node reading it on the attempt that
    finally returned knows how many it took. Nothing is inferred and nothing is
    counted here — a counter of our own would be a second source of a number
    the library already publishes.

    Silent by construction in three cases, each on purpose:

    - **First attempt succeeded** — no row, because presence is the signal.
    - **Every attempt failed** — the callable never returns, so this never
      runs. `node_failure_warnings` carries that case already, on the failure
      half where it belongs.
    - **The node returned something that is not a state dict** (`None`, or a
      `Command`). Recording would mean rewriting a control-flow instruction to
      carry a report, and a report is never worth changing what a node said.

    Tolerant about the runtime for the same reason `run_health` is tolerant
    about its inputs: `build` is driven by scripted stubs and by
    `langgraph<1.2` in tests, and a missing `ExecutionInfo` must cost a report,
    never a run.
    """

    def attempt_number() -> int:
        try:
            from langgraph.runtime import get_runtime

            info = getattr(get_runtime(), "execution_info", None)
            attempt = getattr(info, "node_attempt", 1)
        except Exception:
            return 1
        return attempt if isinstance(attempt, int) else 1

    def record(result: Any) -> Any:
        attempt = attempt_number()
        if attempt <= 1 or not isinstance(result, dict):
            return result
        merged = dict(result)
        existing = merged.get(RETRIES_KEY)
        rows = dict(existing) if isinstance(existing, dict) else {}
        rows[node_id] = attempt
        merged[RETRIES_KEY] = rows
        return merged

    if inspect.iscoroutinefunction(fn):

        async def recorded_async(*args: Any, **kwargs: Any) -> Any:
            return record(await fn(*args, **kwargs))

        return recorded_async

    def recorded(*args: Any, **kwargs: Any) -> Any:
        return record(fn(*args, **kwargs))

    return recorded


def retry_warnings(retries: Mapping[str, Any]) -> list[str]:
    """Nodes that failed, were retried, and then succeeded.

    The compiler gives every node `RetryPolicy(max_attempts=3)` as a
    graph-assembly parameter, so a transient provider failure is silently
    re-run. The **exhausted** case has always been reported —
    `node_failure_warnings` carries it, and the run's answer is missing so
    somebody notices. The **recovered** case had nothing at all: a second (or
    third) full model run, paid for, with the right answer at the end of it and
    no surface saying it took more than one go (`memory-and-replay` 41).

    It was not entirely invisible, which is how it was found: LangGraph
    appends `|1`, `|2` to `checkpoint_ns` when one task invokes a subgraph
    again, and a retried agent re-invokes its own compiled graph. Ticket 40
    read that segment; this is the report it should always have had.

    **On the silent half, and that is a decision rather than a default.** The
    run completed and published the answer it was asked for; `cli.run_exit_code`
    reads `.failures`, and a script that gated on a recovered transient would
    fail builds for a provider hiccup that the policy exists to absorb
    (`workflow-gallery` 49 split `RunResult` for exactly this). A retry is a
    report about *how* the answer was reached.

    Presence is the signal — the same shape as `forced` and `unrouted`. A node
    that got it right first time writes no row, so this list is empty on an
    ordinary run and no reader has to filter `attempt 1`.
    """
    return [
        f'Node "{node}" failed and was retried; attempt {attempt} produced the result.'
        for node, attempt in retries.items()
    ]


def _node_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """`add_node` kwargs for one node's own retry/timeout override, if set.

    `set_node_defaults` (in `build`, below) already gives every node the
    same graph-wide retry policy — this is the *per-node* override the
    canvas's `maxRetries`/`timeoutSeconds`/`cacheTtlSeconds` fields expose (declared once in
    `ModelRegistry.defineNode` on the TS side, inherited by every executable
    node type). Per LangGraph's own docs: "Per-node values still take
    precedence" over `set_node_defaults`, so passing these as `add_node`
    kwargs is the correct override mechanism, not a parallel one.

    `cacheTtlSeconds` has no graph-wide default and deliberately never
    will: caching is **opt-in per node**, because a node's answer is only
    reusable when the developer says its inputs determine its output, and
    most nodes here drive a model. `build` supplies `compile(cache=...)`
    only when some node opted in, so a document that sets nothing is
    assembled exactly as it was before this field existed.

    All three fields are blank strings by default (`FieldValue` has no `None`
    default for a `text` field of this shape) — blank means "no override,
    use the graph default", not "zero" or "unbounded". A non-numeric or
    non-positive value is treated the same as blank: the frontend's own
    `validate` already rejects those before a document can be saved with
    one, so reaching this function with garbage means the value predates
    validation being added, not a case to crash on.
    """
    overrides: dict[str, Any] = {}

    cache_ttl = str(data.get("cacheTtlSeconds") or "").strip()
    if cache_ttl and CachePolicy is not None:
        try:
            ttl = int(cache_ttl)
            if ttl > 0:
                overrides["cache_policy"] = CachePolicy(ttl=ttl)
        except ValueError:
            pass

    max_retries = str(data.get("maxRetries") or "").strip()
    if max_retries:
        try:
            n = int(max_retries)
            if n > 0:
                overrides["retry_policy"] = RetryPolicy(
                    max_attempts=n, initial_interval=1.0, backoff_factor=2.0
                )
        except ValueError:
            pass

    timeout_seconds = str(data.get("timeoutSeconds") or "").strip()
    if timeout_seconds and TimeoutPolicy is not None:
        try:
            seconds = float(timeout_seconds)
            if seconds > 0:
                overrides["timeout"] = TimeoutPolicy(run_timeout=seconds)
        except ValueError:
            pass

    return overrides


def safe_name(node_id: str) -> str:
    """A graph-legal name for a workflow node id.

    LangGraph **reserves `:`** in node names, and our ids look like
    `node:agent.llm-1`, so they cannot be used verbatim — `add_node` raises. Found
    by compiling a document actually exported from the canvas; every hand-written
    fixture had used simple ids and sailed past it.

    Derived from the id rather than the label, because LangGraph treats a node
    name as identity: renaming a node would otherwise break an interrupted
    thread (ticket 04).
    """
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in node_id)


#: Port types per node type — **generated**, never hand-written.
#:
#: The name is unchanged so no consumer had to move, but the contents now come
#: from `compile/port_specs.json`, which `src/nodes/portSpecs.ts` emits from the
#: authoritative TypeScript catalogue (register RC-01; see `node_catalogue.py`
#: for the direction argument). The table stays **injectable** via the
#: compiler's `port_resolver`, which is what let this swap happen without
#: touching a line of compilation logic.
DEFAULT_PORT_SPECS: dict[str, dict[str, PortSpec]] = CATALOGUE.port_specs


def default_port_resolver(node_type: str, port_id: str) -> PortSpec:
    """Best-effort port lookup.

    Some ports are generated from a node's own configuration rather than
    declared — a router's outputs are one `branch:<slug>` per configured branch
    — so those are matched by prefix. The prefixes come from the same generated
    artifact as the static ports: the generator discovers them by probing the
    node's real `ports()` function, so this can never disagree with the editor
    about what a branch port id looks like.
    """
    for group in CATALOGUE.dynamic_ports.get(node_type, ()):
        if port_id.startswith(group.prefix):
            return PortSpec(
                type=group.type,
                direction=group.direction,
                max_connections=group.max_connections,
                accepts=group.accepts,
            )
    spec = DEFAULT_PORT_SPECS.get(node_type, {}).get(port_id)
    if spec is not None:
        return spec
    # Unknown port on a known-or-unknown type: assume control flow. Wrong in the
    # safe direction — an extra sequencing edge is visible in the Mermaid preview,
    # whereas a missed one silently drops a step.
    return PortSpec("text", "in" if port_id != "result" else "out")


@dataclass
class CompiledPlan:
    """What the compiler decided, before a `StateGraph` is built.

    Separated from the graph so it can be asserted directly in a test and
    inspected in the editor. It is also what `openstategraph validate` prints.

    This docstring also promised it was *"reused by the code generator"*. There
    is no code generator and there never has been — `docs/export-and-portability.md`
    records the decision that a `.py` export is not planned. The sentence was
    describing a design that would have made generator and interpreter agree by
    construction; nothing was built to disagree.
    """

    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    #: source node -> {branch label: destination node}
    conditional: dict[str, dict[str, str]] = field(default_factory=dict)
    #: agent node -> tool node names bound to it (not sequenced)
    tool_bindings: dict[str, list[str]] = field(default_factory=dict)
    #: agent node -> skill node names feeding its prompt
    skill_bindings: dict[str, list[str]] = field(default_factory=dict)
    #: Nodes that compile into a binding rather than a step, so are not graph nodes.
    bound_only: list[str] = field(default_factory=list)
    #: orchestrator node id -> the worker archetype nodes it dispatches
    #: `Send` to, in canvas edge order (ticket 37).
    #:
    #: A list per orchestrator, one entry per wired archetype — but still a
    #: *static* declaration: each entry is one node that absorbs however many
    #: dynamic task instances get labelled for it at runtime. LangGraph has no
    #: concept of a node that exists N times, only tasks dispatched N times
    #: against one node. Edge order matters: the first wired archetype is the
    #: default dispatch target when no card claims `default`.
    fan_out: dict[str, list[str]] = field(default_factory=dict)
    entry: list[str] = field(default_factory=list)
    exits: list[str] = field(default_factory=list)
    #: node id -> where a verdict naming no *wired* branch goes, for the
    #: **single-choice** routing families only (`osg-agent-experience/80`).
    #: The value is a label in `conditional[node]` — the declared fallback —
    #: or `""` meaning "stop at this node".
    #:
    #: A node with no entry here keeps the historic first-destination
    #: fall-through, and that is deliberate rather than an oversight: a
    #: grader whose `revise` is unwired is a *recorder*, and
    #: `Finding.UNWIRED_REVISE` is on the record as "a report, not a
    #: refusal" — stopping its run would throw away the answer it just
    #: approved. A router is the other case. Its whole substance is *one
    #: verdict, one destination*, so falling through to whichever branch
    #: happened to be declared first publishes an answer the verdict did
    #: not ask for.
    unrouted_route: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: Reports that stay off `warnings` on purpose — `launch-readiness/24`'s
    #: unknown-`data`-key half, and any dynamically-discovered node type this
    #: build has no static field schema for at all. `warnings` is the channel
    #: `package_testing.assert_document_shape` and `ValidateWorkflowTool`'s
    #: PROBLEMS FOUND both require empty (`Finding.UNWIRED_REVISE`'s
    #: precedent, `workflow-gallery/31`); an advisory here can never move
    #: VALID to INVALID, on purpose — refusing a document over a key that
    #: might belong to a newer field or a plugin is the failure mode the
    #: owner's decision on 24 was written to prevent.
    advisories: list[str] = field(default_factory=list)


def always_taken_cycles(plan: "CompiledPlan") -> list[tuple[str, ...]]:
    """Every loop in `plan` that no decision can leave, as node paths.

    `CLAUDE.md`'s rule — *"a cycle must contain at least one conditional edge
    — an all-static cycle can never terminate"* — made checkable
    (`launch-readiness` 177). It was stated as settled fact and enforced
    nowhere in the backend: `validate` printed `VALID` beside `Routes: none`
    for a document whose only possible outcome is to spend the whole step
    budget and raise `GraphRecursionError`, which at the default budget of 50
    is roughly fifty model calls before the user is told anything.

    **What counts as an escape is read from the plan itself**, never from a
    second list of node types that would drift out of step with the one
    `plan()` builds: an edge that reaches `plan.conditional` or `plan.fan_out`
    came from a node that *decides*, and every other edge is taken on every
    lap. So the walk below is over `plan.edges` alone, and a router, a
    grader's `revise`, a guard's, an approval's branches, a guardrail's and an
    orchestrator's `Send` are all excluded by construction, together with
    whatever family declares a branch port next.

    **A `Send` is a decision, and this function used to say it was not.**
    The premise it was written on — *"`orchestrate.supervisor` chooses how
    many tasks to dispatch, never whether to stop dispatching"* — is
    contradicted by the compiler six hundred lines down: a fan-out compiles to
    `add_conditional_edges`, and `_fan_out_router` returns `[]` for an
    orchestrator that planned no subtasks. An empty list dispatches nothing,
    so the edge is not taken and the lap ends. The one edge kind this walk
    went out of its way to include was the one edge kind that decides, and the
    cost was a **false rejection**: a supervisor replan loop — `sup ⇒ w ->
    sup`, the evaluator-optimizer pattern with a planner in the middle — was
    reported here and therefore failed validation, which the paragraph below
    names as the worse of the two outcomes (`the-cost-of-one-more` 07).

    So `plan.fan_out` is not walked. **Nothing is lost by that**, and the two
    halves of "lost" are separate questions:

    - *A cycle that runs through a fan-out edge.* It has an escape by
      construction — the orchestrator plans zero subtasks — so it was never a
      cycle no decision can leave. Whether a given orchestrator ever will plan
      zero is a fact about a model that has not run, and "we cannot know" is
      the argument for the conservative answer, which is silence.
    - *A cycle merely **reachable** through one.* Unaffected, because this
      walk does not start from `plan.entry` and never asked about
      reachability: the outer loop is `for start in sorted(successors)`, so an
      all-static loop parked below a fan-out is still found. Pinned in
      `tests/test_a_fan_out_is_not_an_edge_that_is_always_taken.py`, because
      that is a property of the loop above rather than of this sentence.

    **One channel, still all-or-nothing, and that stays right.** Every edge in
    a cycle reported here is now unconditional in the compiled graph, so this
    function is certain about what it reports and needs no softer register to
    say so. There is no cap on the count either: one warning per back edge,
    each naming a different closing edge, because a truncated list hides a
    defect the author would then ship.

    **Conservative in the direction that costs nothing.** A cycle carrying a
    router whose every branch leads back into it is equally doomed and is not
    reported here: judging *where* a branch goes is judging a decision the
    model has not made yet, and this function only reports what is true
    before any model runs. A missed loop is a run that overruns, which is
    where every one of them was before this existed; a wrongly-reported one
    would fail a working document, which is worse than the defect.
    """
    successors: dict[str, set[str]] = {}
    for source, destination in plan.edges:
        successors.setdefault(source, set()).add(destination)

    #: 0 unvisited, 1 on the current path, 2 finished. An explicit colour
    #: rather than recursion depth, because a back edge is exactly "a
    #: successor still on the path" and nothing else here needs to know it.
    #:
    #: The walk is iterative for the reason the budget walk below is:
    #: a document arriving through a door that is not the editor was not laid
    #: out by hand, and a `RecursionError` raised out of `plan()` would be
    #: reported as *"Compile failed"* — the compiler blaming itself for a
    #: large drawing.
    #: Where each node on the current path sits in it, so a back edge can be
    #: cut from the path in one lookup. `path.index(successor)` answered the
    #: same question by scanning, O(E·V) over a document's back edges; the
    #: depth is already known when the node is pushed and costs a dict entry
    #: to keep (`the-cost-of-one-more` 07).
    depth: dict[str, int] = {}
    colour: dict[str, int] = {}
    path: list[str] = []
    found: list[tuple[str, ...]] = []

    def _push(node_id: str) -> tuple[str, list[str]]:
        colour[node_id] = 1
        depth[node_id] = len(path)
        path.append(node_id)
        #: Reverse-sorted, so `pop()` from the tail yields ascending order.
        #: `pop(0)` walked a list strictly left to right at O(d) a step —
        #: O(Σdeg²) over the document — for an ordering `reversed` gives free.
        return node_id, sorted(successors.get(node_id, ()), reverse=True)

    for start in sorted(successors):
        if colour.get(start, 0) != 0:
            continue
        stack: list[tuple[str, list[str]]] = [_push(start)]
        while stack:
            node_id, pending = stack[-1]
            if not pending:
                stack.pop()
                path.pop()
                del depth[node_id]
                colour[node_id] = 2
                continue
            successor = pending.pop()
            if colour.get(successor, 0) == 1:
                found.append(tuple(path[depth[successor] :]) + (successor,))
            elif colour.get(successor, 0) == 0:
                stack.append(_push(successor))
    return found


def data_key_findings(
    nodes: Mapping[str, dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """`(hard, advisory)` findings for every node's `data` against its own
    field schema — `launch-readiness/24`.

    **Hard**: a `required` field absent from `data`. There is no working
    version of that node without it, so accepting the document produces only
    the silent wrong answer this ticket exists to close — the owner's
    decision, 2026-08-24.

    **Advisory**: today, exactly one sentence — a `tool.*`/`function.*` type
    with no static field schema to check at all, named below.

    It used to carry a second: a key `data` holds that no field on that node
    type declares, reported as advice because "it might be a newer field or a
    plugin's, so the document stays valid". `osg-agent-experience/32` moved
    that class onto the verdict (`document_checks.unknown_fields`), and the
    sentence is gone from here rather than kept beside it — the editor's
    validate door printed both at once, so one list said *stays valid* directly
    above `valid: false`, and the new sentence names the node's actual fields
    while the old one did not. Two spellings of one finding is the duplication
    this file's own contract exists to prevent.

    **A `tool.*`/`function.*` type absent from the generated catalogue is
    skipped, not guessed at.** Those two prefixes are exactly the ones
    `<slug>/tools.QueryTool` and a package's own `functions/` mint from
    Python with no static field schema for this to check against, and
    pretending one exists would be a false-positive avalanche on the
    workflow-scoped types CLAUDE.md says are legitimate. The skip still
    speaks: it is folded into the advisory list below, named, so nothing
    about *that* node's keys goes unchecked *silently*.

    **Any other type absent from the catalogue is skipped with no advisory
    at all** — deliberately. That is either an unknown node type, which
    `ValidateWorkflowTool` already reports on its own loud channel, or a type
    a plugin registered through `openstategraph.node_families`
    (`known_node_types()`), which is legitimately known to the runtime and
    outside this ticket's scope; saying "its data keys were not checked" a
    second time about a type the validator has already vouched for is noise
    dressed as caution, not the honesty the tool.*/function.* case needs.
    """
    from openstategraph.compile.node_catalogue import CATALOGUE

    hard: list[str] = []
    advisory: list[str] = []
    for node_id, node in nodes.items():
        node_type = str(node.get("type") or "")
        if node_type not in CATALOGUE.node_types:
            if node_type.startswith(("tool.", "function.")):
                advisory.append(
                    f'Node "{node_id}" has type "{node_type}", which this build has no '
                    "generated field schema for (a workflow-scoped or plugin-discovered "
                    "type) — its data keys were not checked."
                )
            continue
        raw_data = node.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}
        for key in sorted(CATALOGUE.required_field_keys.get(node_type, frozenset())):
            if key not in data:
                hard.append(
                    f'Node "{node_id}" ({node_type}) is missing "{key}", which its own '
                    "field schema marks required — there is no working version of this "
                    "node without it."
                )
    return hard, advisory


def _plan_destinations(plan: CompiledPlan) -> dict[str, list[str]]:
    """Every node a node can hand to, whatever kind of edge does the handing.

    Static edges, conditional branch destinations and `Send` fan-out targets
    all cost the same thing — one superstep on the way past — so the walk
    does not care which is which.
    """
    onward: dict[str, list[str]] = {}
    for source, target in plan.edges:
        onward.setdefault(source, []).append(target)
    for source, branches in plan.conditional.items():
        for target in branches.values():
            onward.setdefault(source, []).append(target)
    for source, targets in plan.fan_out.items():
        for target in targets:
            onward.setdefault(source, []).append(target)
    return onward


def _walk_successors(
    onward: Mapping[str, list[str]], start: str
) -> dict[str, list[str]]:
    """Everything reachable from `start`, asking each node for its successors
    **once** — which is the whole of `the-cost-of-one-more` 01.

    The walk this replaced carried a per-path `seen` set, so it re-expanded
    every node once per distinct path prefix that reached it. That is an
    enumeration of simple paths, and on a drawable width-3 tail it cost 55
    seconds at 69 nodes. Nothing downstream of here asks `onward` a second
    time; the local map is what the rest of the derivation reads.
    """
    successors: dict[str, list[str]] = {}
    stack = [start]
    while stack:
        node = stack.pop()
        if node in successors:
            continue
        onward_of_node = list(onward.get(node, ()))
        successors[node] = onward_of_node
        stack.extend(nxt for nxt in onward_of_node if nxt not in successors)
    return successors


def _nodes_that_reach(successors: Mapping[str, list[str]], target: str) -> set[str]:
    """The half of `successors` from which `target` is still reachable.

    A route *back* is a path that has to arrive somewhere. Restricting the
    vertex set first is what lets the same condensation answer both walks:
    inside this set every node reaches `target`, so the component holding
    `target` has no successors and the walk stops there without a special
    case.
    """
    if target not in successors:
        return set()
    backward: dict[str, list[str]] = {}
    for node, nexts in successors.items():
        for nxt in nexts:
            backward.setdefault(nxt, []).append(node)
    reaching = {target}
    stack = [target]
    while stack:
        node = stack.pop()
        for previous in backward.get(node, ()):
            if previous not in reaching:
                reaching.add(previous)
                stack.append(previous)
    return reaching


def _components(
    successors: Mapping[str, list[str]], vertices: set[str]
) -> list[list[str]]:
    """Strongly connected components of `vertices`, successors emitted first.

    Tarjan, iterative for the same reason `always_taken_cycles` is: a document
    that did not come from the editor can be deeper than the interpreter's
    stack, and a `RecursionError` out of `plan()` reads as the compiler
    blaming itself. Tarjan's emission order *is* a reverse topological order
    of the condensation, so the dynamic programme below needs no second sort.
    """
    index: dict[str, int] = {}
    lowest: dict[str, int] = {}
    on_stack: set[str] = set()
    pending: list[str] = []
    emitted: list[list[str]] = []
    counter = 0
    for root in vertices:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, cursor = work.pop()
            if cursor == 0:
                index[node] = lowest[node] = counter
                counter += 1
                pending.append(node)
                on_stack.add(node)
            nexts = [nxt for nxt in successors.get(node, ()) if nxt in vertices]
            descended = False
            while cursor < len(nexts):
                nxt = nexts[cursor]
                cursor += 1
                if nxt not in index:
                    work.append((node, cursor))
                    work.append((nxt, 0))
                    descended = True
                    break
                if nxt in on_stack:
                    lowest[node] = min(lowest[node], index[nxt])
            if descended:
                continue
            if lowest[node] == index[node]:
                component: list[str] = []
                while True:
                    member = pending.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                emitted.append(component)
            if work:
                lowest[work[-1][0]] = min(lowest[work[-1][0]], lowest[node])
    return emitted


def _longest_component_path(
    successors: Mapping[str, list[str]], vertices: set[str], start: str
) -> int:
    """The most nodes any one path from `start` can visit, or an over-estimate.

    **Longest simple path is NP-hard and this does not compute it.** What it
    computes is the longest path through the *condensation*, weighting each
    strongly connected component by how many nodes it holds — O(V+E), with a
    real memo, and an upper bound on the simple-path answer because a path
    crosses the components in topological order and can visit at most every
    node of each.

    Over-estimating is safe in the only direction that matters here. The
    number is a **floor for a default**: too large stops a revision loop one
    lap early, too small restores the `GraphRecursionError` that
    `organisms-first-class` 56 exists to remove. It is also never smaller than
    the walk it replaced, which truncated at a fixed depth and so under-read
    exactly the deep tails this is for.

    Where the graph is acyclic — which is every shipped drawing's `pass` tail
    — every component is a single node and the answer is exact.
    """
    emitted = _components(successors, vertices)
    component_of: dict[str, int] = {}
    for position, component in enumerate(emitted):
        for member in component:
            component_of[member] = position
    longest = [0] * len(emitted)
    for position, component in enumerate(emitted):
        onward_best = 0
        for member in component:
            for nxt in successors.get(member, ()):
                neighbour = component_of.get(nxt)
                if neighbour is not None and neighbour != position:
                    onward_best = max(onward_best, longest[neighbour])
        longest[position] = len(component) + onward_best
    return longest[component_of[start]]


def _longest_chain(onward: Mapping[str, list[str]], node: str) -> int:
    """Supersteps from `node` onward, counting `node` itself.

    Depth, not node count — a fan-out layer runs in **one** superstep however
    wide it is, which is why the longest path is the right measure and a
    census of the reachable set would be the wrong one.
    """
    successors = _walk_successors(onward, node)
    return _longest_component_path(successors, set(successors), node)


def _longest_route_back(
    onward: Mapping[str, list[str]], node: str, target: str
) -> int | None:
    """Supersteps from `node` to `target` inclusive, or `None` if it never
    gets there — which is what an open-ended `revise` branch looks like."""
    successors = _walk_successors(onward, node)
    reaching = _nodes_that_reach(successors, target)
    if node not in reaching:
        return None
    return _longest_component_path(successors, reaching, node)


def step_budget_floor_for(plan: CompiledPlan, node_id: str) -> int:
    """How few supersteps must be left before this grader stops revising.

    `organisms-first-class` 59. `56` compared against a flat constant, and a
    constant cannot know how far `pass` still has to travel: a grader wired to
    a formatter, then a guardrail, then an output has three supersteps of tail
    where `evaluator-optimizer` has one, and the run raised the very exception
    `56` exists to remove. Raising the constant instead was priced and
    refused — it would stop *every* loop earlier, including the one-node tails
    that are the common case, to pay for a shape most drawings do not have.

    **The question is not what the tail costs; it is what one more lap costs
    and then the tail.** A grader looks at the budget once per lap, so a floor
    sized only for the tail approves a lap the budget cannot pay for and the
    run dies part way round, never offered the chance to stop. That is the
    `revise`-side exposure, and it is real: with two nodes spliced into the
    revise path, the same package raised at `recursion_limit=10`.

    So: the longest route from `revise` back to this grader, plus the longest
    chain from `pass` onward. On `evaluator-optimizer` that is 2 + 1 = 3 —
    **the constant `56` measured on that drawing**, which is the argument for
    deriving it at all. The derivation agrees with the measurement on the
    shape the measurement was taken on, and only moves for shapes `56` never
    saw.

    `STEP_BUDGET_FLOOR` remains the floor of the floor. A grader with nothing
    drawn on one of its branches has nothing to derive from, and a number
    below the measured one would restore the crash.

    **Both walks run over the whole plan digraph, and it is cyclic on
    purpose** — the revise loop is the subject, and a `pass` branch may
    legally close a second one. So neither walk asks for the longest simple
    path, which is NP-hard and, in a cycle, not even finite. Each asks for the
    longest path through the graph's **condensation**, weighting a strongly
    connected component by the nodes it holds: O(V+E), and an upper bound on
    the simple-path answer, which is the safe direction for a floor. See
    `_longest_component_path`. Until `the-cost-of-one-more` 01 this paragraph
    read *"the walk is capped rather than solved"*, and the cap it named
    bounded a path's length while the walk enumerated their number — 55
    seconds for one grader on a drawable 69-node document.

    The map is built once here and both walks read it, rather than once per
    walk. It is **not** cached across calls: a grader and a guard each pay one
    O(V+E) pass, which is the same class as the walk it feeds, and a cache
    keyed on a plan would buy a constant factor with a lifetime.
    """
    branches = plan.conditional.get(node_id) or {}
    onward = _plan_destinations(plan)
    lap = (
        _longest_route_back(onward, branches["revise"], node_id)
        if "revise" in branches
        else None
    )
    tail = _longest_chain(onward, branches["pass"]) if "pass" in branches else None
    if lap is None or tail is None:
        return STEP_BUDGET_FLOOR
    return max(STEP_BUDGET_FLOOR, lap + tail)


class WorkflowCompiler:
    """Turns a stored document into a plan, then into a graph.

    Node *names* are the workflow's node ids, deliberately. LangGraph treats node
    names as identity — renaming one hard-breaks an interrupted thread, and
    subgraph checkpoint namespaces are assigned by call order (ticket 04). Ids are
    stable across renames and re-layouts; labels are not.
    """

    def __init__(
        self,
        *,
        port_resolver: Callable[[str, str], PortSpec] = default_port_resolver,
    ) -> None:
        self._port = port_resolver

    @staticmethod
    def _needs_feeding(node: Mapping[str, Any]) -> bool:
        """Whether this node's type declares an in-port it cannot run without.

        Read off the generated catalogue rather than through `self._port`,
        which answers about **one named port** and so cannot say what a type
        declares. An injected resolver therefore does not change this answer,
        and that is the honest limit of it: a test resolver stands in for the
        port table, not for the node catalogue. A type the catalogue does not
        carry — a package tool, a plugin — answers `False`, which is the
        behaviour every node had before this question was asked.
        """
        specs = DEFAULT_PORT_SPECS.get(str(node.get("type") or ""))
        if not specs:
            return False
        return any(spec.direction == "in" and spec.required for spec in specs.values())

    @staticmethod
    def _declared_fallback(
        node_type: str, node: Mapping[str, Any], branches: Mapping[str, str]
    ) -> str:
        """The label a verdict with no wired branch takes, or `""` for "stop".

        Two families, two spellings of one idea, and the difference is not
        cosmetic. `route.check` has no prompt, so its fallback is a **port**
        that always exists and a developer can see on the canvas.
        `route.classifier` has a prompt, so its fallback is a **field naming
        one of its own branches** — the model has to be told which branch
        means "nothing else matched". Either way the answer here is a label in
        the wired destination map or nothing at all.

        A field naming a branch nobody wired is the same as no fallback: there
        is nowhere to go, and inventing a destination is what this ticket is
        about.
        """
        if node_type == ROUTE_CHECK_TYPE:
            return ROUTE_CHECK_FALLBACK_BRANCH if ROUTE_CHECK_FALLBACK_BRANCH in branches else ""
        data = node.get("data") or {}
        named = _text(data if isinstance(data, dict) else {}, "fallback").strip()
        if not named:
            return ""
        resolved = branch_ids_by_spelling((data or {}).get("branches")).get(named.casefold(), named)
        return resolved if resolved in branches else ""

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #

    def plan(self, document: dict[str, Any]) -> CompiledPlan:
        plan = CompiledPlan()
        # What the document says its runs carry, checked before anything is
        # wired (`organisms-first-class/67`). A malformed declaration is a
        # problem on the channel `validate` turns into a non-zero exit; a
        # well-formed one is minted into the graph's `context_schema` in
        # `build` (69), and no declaration at all is silent and free.
        context_problems = context_declaration_problems(document)
        plan.warnings.extend(context_problems)
        # What a deep agent says it may delegate to (`organisms-first-class/84`).
        # Same channel and same reason: a row the runtime cannot deliver — three
        # required strings missing, a repeated name, or a declaration on a tier
        # with no `subagents` parameter at all — is a document defect knowable
        # before anything runs, and saying nothing is the `skills=` failure 81
        # measured.
        plan.warnings.extend(subagent_declaration_problems(document))
        if not context_problems:
            # A key that cannot become a field name cannot be minted, and a
            # build that raised `TypeError` out of `make_dataclass` would blame
            # the compiler for a document defect. Reported here, where every
            # other document defect is reported, and the whole schema is
            # withheld rather than half of it: a context a caller can only
            # partly supply is worse than one it must supply none of.
            awkward = unmintable_context_keys(context_declaration(document))
            if awkward:
                listed = ", ".join(repr(key) for key in awkward)
                plan.warnings.append(
                    f"Run context declares keys that cannot be minted into a run "
                    f"context schema: {listed} — a key must be a plain word (letters, "
                    "digits and underscore, not starting with a digit), because it is "
                    "also a command-line flag and a prompt variable. No context schema "
                    "was minted for this workflow."
                )
        nodes = {n["id"]: n for n in document.get("nodes", [])}

        # Annotations and containers never execute, so they are not graph nodes.
        executable = {
            node_id: node
            for node_id, node in nodes.items()
            if not str(node.get("type", "")).startswith("annotate.")
        }

        hard_data_key_findings, advisory_data_key_findings = data_key_findings(executable)
        plan.warnings.extend(hard_data_key_findings)
        plan.advisories.extend(advisory_data_key_findings)

        has_incoming: set[str] = set()
        has_outgoing: set[str] = set()
        #: Nodes whose only participation is being *bound* to another node.
        bound_only: set[str] = set()
        #: Nodes that take part in control flow, and so are real graph nodes.
        in_control_flow: set[str] = set()

        for edge in document.get("edges", []):
            src, dst = edge.get("source") or {}, edge.get("target") or {}
            # Annotated (and the `is None` arm spelled out) so the type checker
            # can see what the `in executable` test already guaranteed: past
            # this guard both ids are real strings, and every set/dict keyed by
            # them below is keyed by `str`.
            src_id: str | None = src.get("nodeId")
            dst_id: str | None = dst.get("nodeId")
            if src_id is None or dst_id is None or src_id not in executable or dst_id not in executable:
                plan.warnings.append(f"Dropped an edge with an unknown endpoint: {src_id} -> {dst_id}")
                continue

            src_type = str(executable[src_id].get("type", ""))
            dst_type = str(executable[dst_id].get("type", ""))
            dst_port = self._port(dst_type, dst.get("portId", ""))
            src_port = self._port(src_type, src.get("portId", ""))

            # --- fan-out: a dispatch target, not a step and not a binding ---
            #
            # Checked before BINDING_PORT_TYPES because a worker's "dispatch"
            # port is its own type, not a tool/skill capability — conflating
            # them would make the worker bind to the orchestrator as if it were
            # a tool, which is a different (and wrong) relationship.
            if dst_port.type == WORKER_PORT_TYPE:
                targets = plan.fan_out.setdefault(src_id, [])
                if dst_id not in targets:
                    targets.append(dst_id)
                has_outgoing.add(src_id)
                # The worker has no *static* incoming edge — LangGraph dispatches
                # it dynamically via Send — but it is reached, so it must not be
                # treated as an entry and wired from START. Same precedent as the
                # grader's `revise` edge.
                has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- bindings: capability, not sequence ---
            if dst_port.type in BINDING_PORT_TYPES:
                bucket = (
                    plan.tool_bindings if dst_port.type == "tool" else plan.skill_bindings
                )
                bucket.setdefault(dst_id, []).append(src_id)
                # A bound node is **not a graph node at all**. It compiles into
                # the agent's tool list, not into a step.
                #
                # Getting this half-right is worse than getting it wrong: an
                # earlier version only excluded it from `exits`, so it still had
                # no incoming edge, became an `entry`, and got wired from START —
                # meaning the tool ran once on its own at graph start *and* again
                # when the agent called it. Exactly the doubling this whole
                # distinction exists to prevent, and the unit tests missed it
                # because they only asserted `exits`.
                bound_only.add(src_id)
                continue

            # --- the router, and its mechanical sibling: one conditional edge
            # per branch. `route.check` decides by calling a package function
            # rather than a model, which changes who chooses and nothing about
            # the edge (`osg-agent-experience` 42). Its `fallback` is a static
            # port carrying no prefix, so `removeprefix` leaves it as its own
            # label — the same string `_route_check` writes.
            if src_type in (ROUTER_TYPE, ROUTE_CHECK_TYPE):
                branch = src.get("portId", "").removeprefix("branch:")
                plan.conditional.setdefault(src_id, {})[branch] = dst_id
                has_outgoing.add(src_id)
                has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- the grader, and its mechanical sibling: pass continues,
            # revise loops back. Same shape, same edge semantics — a guard is
            # priced as `route.grader` with computation instead of judgement,
            # not as `GUARDRAIL_TYPE` (`launch-readiness` 65).
            if src_type in (GRADER_TYPE, GUARD_CHECK_TYPE):
                label = "revise" if src_port.type == "feedback" else "pass"
                plan.conditional.setdefault(src_id, {})[label] = dst_id
                has_outgoing.add(src_id)
                # A revise edge deliberately does **not** mark its destination as
                # having an incoming edge: the loop target is usually the entry
                # node, and counting it would leave the graph with no entry at
                # all and nothing wired to START.
                if label == "pass":
                    has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- human approval: same node-decides/edge-dispatches split as
            # the grader, just with a human's decision instead of an LLM's.
            # Labels are the literal port ids ("approved"/"rejected"), not
            # translated to "pass"/"revise" — a rejection here does not loop
            # back to a retry the way a grader's revise does, it takes a
            # different, deliberately-wired path (e.g. straight to an
            # explanatory Output), so borrowing the grader's own vocabulary
            # would misdescribe what actually happens on this edge.
            if src_type == HUMAN_APPROVAL_TYPE:
                label = src_port_id if (src_port_id := src.get("portId", "")) else "approved"
                plan.conditional.setdefault(src_id, {})[label] = dst_id
                has_outgoing.add(src_id)
                has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- the guardrail: allowed continues, blocked takes its own wire
            # Labels are the literal port ids, like the approval's: a blocked
            # message goes *forward* to an Output carrying a refusal, so it is
            # neither a grader's `revise` (which returns upstream and is the
            # only thing a cycle may close on) nor an ordinary edge.
            if src_type == GUARDRAIL_TYPE:
                label = src.get("portId", "") or "allowed"
                plan.conditional.setdefault(src_id, {})[label] = dst_id
                has_outgoing.add(src_id)
                has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- ordinary control flow ---
            plan.edges.append((src_id, dst_id))
            has_outgoing.add(src_id)
            has_incoming.add(dst_id)
            in_control_flow.update((src_id, dst_id))

        # A node that is only ever bound is excluded; an isolated node is kept,
        # because a lone node on a fresh canvas should still be runnable.
        plan.nodes = sorted(
            node_id
            for node_id in executable
            if node_id not in bound_only or node_id in in_control_flow
        )
        plan.bound_only = sorted(bound_only - in_control_flow)

        plan.edges.sort()
        # **What can start a run, preferred over what merely has no edge into
        # it** (`osg-agent-experience/80`). A node with no incoming edge used
        # to be wired from START unconditionally, and that is how four mounts
        # hanging off *unwired branches* of a single-choice router ran on
        # every run: nothing pointed at them, so each became an entry, each
        # spent a model call on an empty input, and each published its own
        # Output. The router's verdict never entered into it.
        #
        # Asked of the descriptor rather than of a list of types: a node type
        # declaring a **required** in-port is saying it cannot begin anything
        # on its own. `input.text` and a router declare none and start runs;
        # a mount, an Output and an agent's `prompt` declare one.
        #
        # A *preference*, not a refusal, and the fallback line is the reason:
        # a lone agent on a fresh canvas has a required `prompt` with nothing
        # feeding it and must still run — `_upstream_text` hands it the
        # question. So a document with nothing else to start it keeps exactly
        # the behaviour it had. What changes is only the case where something
        # else *can* start the run, which is the case where a starved node
        # was never meant to be a second beginning.
        candidates = [n for n in plan.nodes if n not in has_incoming]
        startable = [n for n in candidates if not self._needs_feeding(executable[n])]
        plan.entry = sorted(startable or candidates)
        plan.exits = sorted(n for n in plan.nodes if n not in has_outgoing)
        # **And the ones the preference dropped are named.** Not scheduling a
        # starved node is the fix; doing it in silence would be the same defect
        # one layer down — the owner met this shape as four lens mounts that
        # ran unasked, and the only thing worse than a node running unasked is
        # a node the compiler quietly declined to run with nothing said. An
        # advisory rather than a warning, deliberately: the document is not
        # invalid — a half-wired canvas is what a canvas looks like mid-build —
        # so this may never move VALID to INVALID (`launch-readiness/24`'s
        # precedent, recorded on `advisories` itself).
        if startable:
            for node_id in sorted(set(candidates) - set(startable)):
                plan.advisories.append(
                    f'"{node_id}" has no incoming edge and cannot start a run on its own, '
                    f"so it never runs. Wire something into it, or delete it."
                )

        if not plan.entry and plan.nodes:
            plan.warnings.append("No entry node: every node has an incoming edge")

        # Where a single choice goes when the branch it named was never drawn
        # (`osg-agent-experience/80`). Only the two families whose substance is
        # *one verdict, one destination*; see `CompiledPlan.unrouted_route` for
        # why a grader is deliberately not one of them.
        for src_id, branches in plan.conditional.items():
            node_type = str((nodes.get(src_id) or {}).get("type") or "")
            if node_type not in (ROUTER_TYPE, ROUTE_CHECK_TYPE):
                continue
            plan.unrouted_route[src_id] = self._declared_fallback(
                node_type, nodes.get(src_id) or {}, branches
            )

        # A grader/guard whose `revise` is wired but whose `pass` is not: the
        # `pass` verdict is unmapped, so `_router_for` falls through to the
        # only wired destination — `revise` — and every passing judgement
        # loops back instead of leaving. That is not a missing-decision stall
        # (`UNWIRED_REVISE`'s case, which is a legal graph that never
        # revises); it is a decision the node understands but has nowhere to
        # go, and the fallback turns it into a run that cannot terminate.
        # `UNWIRED_REVISE` is deliberately a report, not a refusal, because a
        # grader-as-recorder with no `revise` wired is fine — it just never
        # sends anything back. There is no matching safe reading here: a
        # `pass` with no exit can only loop, so this is checked on
        # `plan.warnings`, the hard channel, at compile time rather than
        # left to raise mid-run (launch-readiness 66).
        for src_id, branches in plan.conditional.items():
            node = nodes.get(src_id)
            if node is None or node.get("type") not in (GRADER_TYPE, GUARD_CHECK_TYPE):
                continue
            if "revise" in branches and "pass" not in branches:
                mapped = ", ".join(f"{k!r} -> {v!r}" for k, v in sorted(branches.items()))
                plan.warnings.append(
                    f"Grader {src_id!r} has an unmapped 'pass' verdict: only "
                    f"{mapped} is wired, so a passing judgement falls through "
                    "to 'revise' and the run never terminates. Wire the "
                    "'pass' port to a destination."
                )

        # A loop no decision can leave. The sibling of the check above and
        # the same argument: a `pass` verdict with nowhere to go can only
        # loop, and so can a cycle with no verdict on it at all. Reported on
        # `plan.warnings` — the hard channel, so `validate` exits non-zero and
        # `load_workflow` carries it — rather than raised, because a refusal
        # would break any document already carrying one and this map forbids
        # that. The editor refuses to *draw* one (`acyclicRule`, and
        # `capacityRule` incidentally), but a hand-written document, a
        # scaffold, an exported package, an MCP `compile_workflow` call and
        # the workflow-architect agent all arrive here without passing either
        # (`launch-readiness` 177).
        for cycle in always_taken_cycles(plan):
            drawn = " -> ".join(repr(node_id) for node_id in cycle)
            plan.warnings.append(
                f"Nodes {drawn} form a loop with no conditional step on it: "
                "every edge on that path is taken on every lap, so the run can "
                "only go round until the step budget is spent and then fail. "
                "Put a grader, a guard or a router on the loop so a verdict can "
                "leave it, or remove the edge that closes it."
            )

        # Two archetypes with one dispatch key cannot both be reachable — the
        # later one silently shadows the earlier in the dispatch map. Warn at
        # plan time, where the collision is a document fact, not a run fact.
        for orchestrator_id, worker_ids in plan.fan_out.items():
            if len(worker_ids) < 2:
                continue
            keys = [archetype_key(nodes[w]) for w in worker_ids if w in nodes]
            duplicates = {k for k in keys if keys.count(k) > 1}
            if duplicates:
                plan.warnings.append(
                    f"Orchestrator {orchestrator_id!r} has workers sharing an "
                    f"archetype key ({', '.join(sorted(duplicates))}); retitle "
                    "the workers so every archetype is dispatchable"
                )
        return plan

    # ------------------------------------------------------------------ #
    # Building
    # ------------------------------------------------------------------ #

    def build(
        self,
        document: dict[str, Any],
        state_schema: type,
        node_factory: Callable[[str, dict[str, Any], CompiledPlan], Any],
        *,
        compile_graph: bool = True,
        checkpointer: Any = None,
        store: 'BaseStore | None' = None,
        mounted: bool = False,
    ) -> Any:
        """Assembles the graph.

        `node_factory` supplies the callable for each node, so the compiler owns
        *topology* and knows nothing about models, prompts or tools. That split is
        what lets the whole structure be tested without an API key.

        `checkpointer` is what makes a `human.approval` node's `interrupt()`
        actually able to pause: LangGraph raises at compile time if a graph
        containing an interrupt has no checkpointer at all. Optional and
        `None` by default — a graph with no human-in-the-loop node has
        nothing to checkpoint, and passing one unconditionally would give
        every run persisted state it never asked for.

        `store` keeps its name and gains a type. The name because it is handed
        straight to LangGraph's own `compile(store=)` on the last line of this
        method, and a second spelling at the last hop would be one more place
        the two vocabularies can disagree; the type because this is where
        `WorkflowServices.store` (the filesystem one) could arrive by a
        one-token edit and pass every check downstream.

        `mounted` says this graph is being built as a **child of a mount**, and
        the only thing it changes is what *declares nothing* compiles to
        (`organisms-first-class/76`). A graph with no `context_schema` is not
        isolated from its caller's run context — it inherits it, and no argument
        to `invoke` can take that away — so a mounted child that declares
        nothing is given an empty schema rather than none. A workflow run
        directly is never mounted and is never sealed: 69's promise that a
        document declaring nothing builds exactly the graph it built before is
        kept where it was made.
        """
        plan = self.plan(document)
        nodes = {n["id"]: n for n in document.get("nodes", [])}
        # What this workflow's runs carry, as a class (`organisms-first-class/69`).
        # A **build artefact**: minted here from JSON field descriptors, handed
        # to LangGraph, and never read back — `workflow.json` holds no Python
        # type and `core/` never sees this object, which is how portability
        # guardrail 4 survives a feature about declaring a Python class. It is
        # a graph-assembly parameter, so it sits here beside `retry_policy` and
        # `set_node_defaults` rather than on any node family.
        #
        # `None` means *pass nothing*, not *pass `None`*: a document that
        # declares no run context must build exactly the graph it built before
        # this ticket, and whether a library treats an explicit `None` as an
        # absent argument is its business rather than a thing to assume.
        context_schema = mint_context_schema(document, sealed=mounted)
        # `state_schema` is a caller-supplied TypedDict class, so the builder's
        # own type parameters cannot be inferred from it; `Any` here is honest —
        # the state shape is a workflow's, not ours.
        builder: StateGraph[Any, Any, Any, Any] = (
            StateGraph(state_schema)
            if context_schema is None
            else StateGraph(state_schema, context_schema=context_schema)
        )

        # Graph-assembly parameters, never a node concern (CLAUDE.md): every
        # node gets the same retry/error-recovery policy from one place,
        # rather than each node factory reimplementing its own backoff loop.
        # `max_attempts=3` with exponential backoff is not a theoretical
        # nicety here — a live run this session hit a real, transient
        # `ollama._types.ResponseError` (a cloud-provider 500) that a bare
        # retry resolved on the next attempt. `default_retry_on` (the
        # library default) already excludes programming errors
        # (`ValueError`, `TypeError`, ...), so this does not mask a bug by
        # retrying it into a timeout.
        # The number lives in `compile/side_effects.py`, which is also what
        # reads it to decide whether a node that acts outside the run can be
        # run twice (`launch-readiness` 121). One spelling, or the finding
        # and the policy drift into two different threes.
        default_retry = RetryPolicy(
            max_attempts=DEFAULT_MAX_ATTEMPTS, initial_interval=1.0, backoff_factor=2.0
        )
        has_graph_defaults = hasattr(builder, "set_node_defaults")
        if has_graph_defaults:
            builder.set_node_defaults(
                retry_policy=default_retry,
                # langgraph's published `StateNode` union does not include the
                # `(state, error: NodeError)` shape it accepts at runtime via
                # its name+annotation matcher — a gap in the library's types,
                # not in ours. `test_node_overrides` proves the handler really
                # fires, so the ignore is narrow and covered.
                error_handler=_error_handler_for(  # type: ignore[arg-type]
                    {safe_name(node_id): node_id for node_id in plan.nodes}
                ),
            )

        wants_cache = False
        for node_id in plan.nodes:
            overrides = _node_overrides(nodes[node_id].get("data") or {})
            wants_cache = wants_cache or "cache_policy" in overrides
            if not has_graph_defaults and "retry_policy" not in overrides:
                # `langgraph<1.2` has no graph-wide defaults, and the earlier
                # fallback comment here claimed `_node_overrides` covered it —
                # it does not: overrides only exist when a card sets
                # `maxRetries`. That left every node retry-less, so one
                # transient Ollama 500 emptied a fan-out worker's result or
                # 502'd the whole run (found live, ticket 61). The default is
                # applied per node instead; an explicit override still wins.
                overrides = {**overrides, "retry_policy": default_retry}
            builder.add_node(
                safe_name(node_id),
                # Wrapped here, beside `retry_policy` itself: the policy and
                # the report of it firing are one concern and must not drift
                # apart into the node factories (`recording_attempts`).
                # And `with_both_doors` outermost, which is the last thing
                # between a node body and LangGraph (`async-first/06`). A
                # migrated family's body is `async def`, and a node built from
                # a coroutine function has an async door and no sync one — so
                # one migrated node would make the whole compiled graph
                # async-only and break the four synchronous doors this backend
                # still has onto it: the blocking `/api/runs`, the MCP server,
                # `CompiledWorkflow.run` (the library path a package's own
                # `tests/` uses), and the CLI. `compile/node_doors.py` carries
                # the measurement, and why this is a collaborator applied at
                # one seam rather than a method on a base class. Identity for
                # a `def` body, so no un-migrated family is touched — and
                # outermost so `recording_attempts`, which already knows both
                # kinds, keeps seeing the raw body.
                with_both_doors(
                    recording_attempts(
                        node_id, node_factory(node_id, nodes[node_id], plan)
                    )
                ),
                **overrides,
            )

        for src, dst in plan.edges:
            builder.add_edge(safe_name(src), safe_name(dst))

        for src, destinations in plan.conditional.items():
            if not destinations:
                continue
            unrouted_route = plan.unrouted_route.get(src)
            # `dict[Hashable, str]`, which is what `add_conditional_edges`
            # declares: a `dict[str, str]` is not a subtype of it (a dict is
            # invariant in its key), and mypy says so.
            path_map: dict[Hashable, str] = {
                label: safe_name(dst) for label, dst in destinations.items()
            }
            if unrouted_route == "":
                # A single-choice router with no declared fallback stops the
                # run at itself rather than publishing some other branch's
                # answer. END has to be in the map for the path function to be
                # allowed to name it, and the label is one no branch id can
                # collide with — `branch:` is stripped off a port id, and a
                # `route.check`'s static ports are `fallback` and nothing else.
                path_map[STOP_LABEL] = END
            builder.add_conditional_edges(
                safe_name(src),
                self._router_for(src, destinations, unrouted_route),
                # The complete declared destination set. Without it every
                # renderer must assume the router reaches any node (ticket 03).
                path_map,
            )

        for orchestrator_id, worker_ids in plan.fan_out.items():
            # key -> graph node name. First writer wins on a collision, which
            # matches the plan-time warning above: the shadowed worker is
            # unreachable and the developer was told.
            archetype_map: dict[str, str] = {}
            for worker_id in worker_ids:
                worker_node = nodes.get(worker_id) or {}
                archetype_map.setdefault(archetype_key(worker_node), safe_name(worker_id))
            # Exactly one default is the validated shape; the rule itself is
            # `default_worker_node`, shared with the orchestrator node so the
            # dispatch and the record of it (ticket 17) cannot disagree.
            chosen = default_worker_node(
                [{**(nodes.get(w) or {}), "id": w} for w in worker_ids]
            )
            default_worker = str((chosen or {}).get("id") or worker_ids[0])
            builder.add_conditional_edges(
                safe_name(orchestrator_id),
                self._fan_out_router(orchestrator_id, archetype_map, safe_name(default_worker)),
                # The complete declared destination set: every wired archetype.
                # Still static — N dynamic tasks per archetype node (ticket 27).
                [safe_name(w) for w in worker_ids],
            )

        for node_id in plan.entry:
            builder.add_edge(START, safe_name(node_id))
        for node_id in plan.exits:
            builder.add_edge(safe_name(node_id), END)

        if not compile_graph:
            return builder
        # And the saver reaches the graph async-capable, on **every** door
        # (`async-first/06`). Phase A bridged it at the two streaming handlers
        # and said why — at that point only `graph.astream()` could call a
        # checkpointer's async four, so "the process-wide saver stays exactly
        # what every synchronous caller already holds". Phase D expires that
        # reasoning: a migrated node body is `async def` and invokes its own
        # compiled agent through `ainvoke`, and a nested graph inherits the
        # parent's checkpointer through the ambient config — so the async four
        # are now reached from the *synchronous* door too, which was the one
        # door the bridge deliberately did not cover. Live, that surfaced as
        # `NotImplementedError: The SqliteSaver does not support async
        # methods`, swallowed by the graph-wide error handler into an empty
        # answer: two states, one output, again.
        #
        # Safe to apply here rather than at the doors because the wrapper is
        # invisible to a synchronous caller by construction — `memory.py`'s
        # `_AsyncCapableSaver` delegates the sync four one by one, and
        # `__getattr__` passes `setup`, `conn` and the rest through. Idempotent,
        # so the two handlers that still wrap explicitly cost nothing.
        checkpointer = _async_capable_saver(checkpointer)
        if wants_cache and InMemoryCache is not None:
            # Only when asked. `cache=` on every graph would attach an
            # unbounded in-process dict to workflows that never opted in.
            return builder.compile(checkpointer=checkpointer, store=store, cache=InMemoryCache())
        return builder.compile(checkpointer=checkpointer, store=store)

    @staticmethod
    def _fan_out_router(
        orchestrator_id: str,
        archetype_map: dict[str, str],
        default_worker: str,
    ) -> Callable[[Any], list[Any]]:
        """Reads the orchestrator's plan and dispatches one `Send` per subtask.

        Hybrid routing (ticket 37): each subtask carries the archetype key the
        orchestrator labelled it with, and the key resolves to that archetype's
        node through `archetype_map`. A key that resolves to nothing — the
        model invented a label, or labelling failed and left `""` — dispatches
        to `default_worker` rather than raising: a misroute degrades to the
        single-archetype behaviour this graph had before archetypes existed.

        This is the one place `Send` is constructed, deliberately outside the
        orchestrator node itself. The node writes *what to do*
        (`state["subtasks"][id]`); this reads it and decides *how many times to
        do it* — the same node-decides / edge-dispatches split already used for
        the router and the grader, so all three "which branch" mechanisms share
        one shape.

        **The payload is the worker's entire visible state — nothing more.**
        Verified directly against the installed langgraph: a `Send` payload does
        **not** merge with the parent graph state, it *replaces* what the
        dispatched node sees. So every worker instance receives exactly
        `task_id` and `task_instruction` and nothing else — no question, no
        schema hint, no upstream output — unless the orchestrator explicitly
        packs it into the subtask. This is stricter isolation than a
        tool-subagent, which at least receives the whole task description in
        its ToolMessage; here the isolation is structural, not a convention.
        """

        def route(state: Any) -> list[Any]:
            subtasks = (state.get("subtasks") or {}).get(orchestrator_id) or []
            return [
                Send(
                    archetype_map.get(task.get("archetype") or "", default_worker),
                    {"task_id": task["id"], "task_instruction": task["instruction"]},
                )
                for task in subtasks
            ]

        return route

    @staticmethod
    def _router_for(
        node_id: str, destinations: dict[str, str], unrouted_route: "str | None" = None
    ) -> Callable[[Any], "str | list[str]"]:
        """The `path` function for one conditional edge.

        Reads the decision a node already wrote to state rather than deciding
        again. A router node writes `branch`; a grader writes `verdict`. Falling
        back to the first declared destination keeps a run alive when a decision
        is missing — a stall here would be a hang, not an error.

        **That argument is about a decision that is missing, and there is a
        second case it never covered** (`workflow-gallery` 31): a decision that
        exists, is understood, and names a branch the author never wired. It
        took the identical silent fallback, so a grader that judged an answer
        inadequate sent it to the output anyway. The fallback stays — a
        genuinely missing decision would otherwise hang the run rather than
        error — but the case is no longer silent. It is reported twice, and
        neither report is here: a `path` function returns a label and cannot
        write state, so the honesty is produced where the decision is, in
        `node_runtime._grader` (`Finding.UNWIRED_REVISE` at compile time, the
        `unrouted` state key during the run). Anything added *here* would have
        to be a channel of its own, which is what this project keeps not doing.

        **May return several destinations** when a classifier ran in
        `matchMode: "all"` and the question belonged to more than one desk
        (`every-workflow-green` 27). LangGraph documents both halves of that:
        a `path` function may return a sequence, and "if a node has multiple
        outgoing edges, all of those destination nodes will be executed in
        parallel as part of the next superstep".

        The set is read from its **own** `routes` channel, never from
        `decisions`. `decisions[node_id]` is a single label that this very
        function dispatches on and that every trace row, warning and test
        reads; ticket 09 is the record of what widening it costs. A document
        with no `routes` entry — which is every workflow shipping today —
        takes the identical path it always did.

        One destination stays a plain string rather than a one-item list, for
        the same reason: the callers downstream have always been handed a name.

        **`unrouted_route` is where the first-destination default stops**
        (`osg-agent-experience/80`). The paragraphs above argue the default is
        right for a *grader*, and they still do — a grader whose `revise` is
        unwired is a recorder, and its approved answer must ship. They were
        never an argument about a **router**, whose whole substance is one
        verdict and one destination, and on a live run they made one: a
        classifier answered `unclear`, that branch had no edge, and the first
        branch that happened to be declared published an answer nobody asked
        for. So the two families are now told apart at plan time rather than
        sharing a default that only ever suited one of them: `None` keeps the
        historic behaviour, a label sends an unwired verdict to the declared
        fallback, and `""` stops the run at the node. This function is unmoved
        on everything else — it still reads a decision somebody else made.
        """
        default = next(iter(destinations))

        def unrouted() -> str:
            if unrouted_route is None:
                return default
            return unrouted_route or STOP_LABEL

        def route(state: Any) -> "str | list[str]":
            if not hasattr(state, "get"):
                return unrouted()
            decisions: dict[str, str] = state.get("decisions") or {}
            routes: dict[str, Any] = state.get("routes") or {}

            requested = routes.get(node_id)
            if isinstance(requested, (list, tuple)):
                # Unwired branches are dropped rather than raising: a
                # half-wired router is already a plan-time warning, and a crash
                # here would turn a visible gap into a dead run.
                # Labels, not node names: `add_conditional_edges` is given a
                # path map, so this function's contract has always been to
                # return the *label* and let LangGraph resolve it.
                # `isinstance` rather than a cast: `routes` is state, so its
                # contents are whatever a node wrote. Every candidate is
                # already resolved against `destinations` — the strict half
                # of the read-tolerantly rule — and this makes the *type*
                # say so, which is what `no-any-return` was reporting at the
                # `return wired[0]` below (`organisms-first-class` 48).
                wired: list[str] = [
                    key
                    for key in requested
                    if isinstance(key, str) and key in destinations
                ]
                if len(wired) > 1:
                    return wired
                if len(wired) == 1:
                    return wired[0]

            chosen = decisions.get(node_id)
            if chosen in destinations:
                return chosen
            return unrouted()

        return route


__all__ = [
    "BINDING_PORT_TYPES",
    "CONTROL_PORT_TYPES",
    "DEFAULT_PORT_SPECS",
    "CompiledPlan",
    # Re-exported from `node_catalogue` so existing importers keep working; the
    # dataclass moved there because the loader has to build one.
    "PortSpec",
    "WorkflowCompiler",
    "default_port_resolver",
    "safe_name",
]


def _async_capable_saver(checkpointer: Any) -> Any:
    """`checkpointer`, able to answer the async four. Total, and idempotent.

    `True`, `False` and `None` are the mount tri-state
    (`compile/mount_persistence.py`) rather than savers, and pass through
    untouched — a mount that inherits its parent's saver inherits the wrapped
    one. Imported lazily so the compiler does not pull `memory` (and, through
    it, sqlite and the optional postgres extra) into every import of itself.
    """
    if not isinstance(checkpointer, BaseCheckpointSaver):
        return checkpointer
    from openstategraph.memory import async_capable

    return async_capable(checkpointer)
