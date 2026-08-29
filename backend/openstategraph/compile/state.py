"""The shared run-state schema, and the pure functions that read one.

`RunState` is the state schema every compiled workflow's `StateGraph` carries,
together with the turn-boundary `RESET` marker, the named reducers re-exported
for its readers, and the module-level helpers whose only argument is a state.

Nothing here resolves a model, builds a node or touches a document; a reader
that needs a *document* belongs in `compile/context.py`, on the other side of
this seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict, get_type_hints

from langgraph.managed import RemainingSteps


from openstategraph.compile.reducers import RESET as _RESET
from openstategraph.compile.reducers import Reducer, reducer_for


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


#: What a model-driven node publishes when no model was configured for it.
#:
#: `_worker` returned `{"worker_results": {task_id: ""}}` for a `None` model and
#: wrote **no** `outputs` entry, so the step was absent from the run's record
#: entirely — not even the silent channel could see it — and was in any case
#: indistinguishable from a worker whose model answered with nothing
#: (`workflow-gallery` 18).
#:
#: A marker in `outputs` rather than a new state channel, for the reason
#: `_FAILURE` is one: reader and writer stay together, and downstream still
#: reads *something*. On the **silent** half rather than the failure half —
#: `silent_node_warnings` argues that boundary in as many words, and
#: `cli.run_exit_code` reads `.failures`. A step nobody gave a model to is a
#: report about how the answer was reached; the run did not break.
#:
#: It lives here rather than in `workflow_compiler.py`, which defined it until
#: `export-and-eject/16`, because it is a *value written into `RunState`* — the
#: same kind of word as `RESET`, and read by `_silent_member_note` two hundred
#: lines below. `workflow_compiler` re-exports it, so its own readers and the
#: tests that import it from there did not have to move.
NO_MODEL_MARKER = "[no model was configured for this step]"


#: What an output node says when it reached the end with nothing to say.
#:
#: A named constant, not a literal at the one site that writes it, because a
#: *consumer* has to be able to tell this apart from a real answer: `run`
#: exited 0 for a workflow whose mount did not resolve, since "is the answer
#: empty" was being asked of a sentence saying it was (`production-ready` 53).
#:
#: It used to end "Check the run trace to see which step returned nothing" —
#: printed directly below the line that already names the step, pointing at a
#: trace the CLI cannot open. Advice a surface cannot honour is worse than
#: none, so the honest floor is the first sentence alone.
#:
#: Here rather than in `node_runtime.py`, which defined it until
#: `launch-readiness/174`, for `NO_MODEL_MARKER`'s reason: it is a *value
#: written into `RunState`*, and `published_answer` below — the seam that
#: assembles a run's answer out of the state — has to be able to recognise it
#: without importing the runtime. `node_runtime` re-exports it, so its own
#: readers and the tests that import it from there did not have to move.
NO_ANSWER_PRODUCED = "The workflow finished without producing an answer."


#: How few supersteps must be left before a cycle stops asking for another lap
#: (`organisms-first-class` 56).
#:
#: **The floor of the floor**, since `organisms-first-class` 59. `56` compared
#: against this number flat, on the argument that a derived one would be a
#: second thing to keep true. It is a property of the drawing, and 59 measured
#: the cost of not deriving it: a `pass` branch crossing three nodes, and a
#: `revise` path crossing three, both raised the exception 56 exists to
#: remove. `workflow_compiler.step_budget_floor_for` now walks the plan; this
#: is what it falls back to when a grader has nothing drawn to derive from,
#: and the minimum it will ever return. The derivation *reproduces* the number
#: below on the drawing the number was measured on — one more lap (2) plus the
#: tail (1) — which is what made deriving it safe.
#:
#: **Three, and the number was measured rather than copied.** The LangGraph
#: docs' own example uses `<= 2`; that is one short here, and the run still
#: raised. `remaining_steps` is read *inside* the superstep it describes, so
#: `remaining == 1` means the grader itself is the last step the budget will
#: pay for and the output node behind a forced `pass` never gets to run. Laps
#: also arrive on a parity — `evaluator-optimizer` at `recursion_limit=10`
#: shows the grader 7, 5, 3, 1, because one lap costs two supersteps — so a
#: floor must be crossed with a step to spare rather than exactly.
#:
STEP_BUDGET_FLOOR = 3


@dataclass(frozen=True)
class _CustomerVisible:
    """Marker: this channel's contents may cross the customer boundary.

    ## Why the audience of a channel is declared *on the channel*

    `the-boundary-nobody-checked/02`. The audience of a state channel was
    written down twice already — the table in `api/audience.py`, and the
    comments below — and `GET /api/threads/{id}` published every channel to
    everybody because it had neither in code. A third spelling, a key list
    beside that door's `_PRIVATE_PREFIXES`, is exactly how the same defect
    comes back a third time: three lists that agree today and disagree after
    the next channel.

    So the declaration is the annotation, and `customer_visible_channels()`
    below reads it back. Adding a channel and deciding who may read it is one
    edit, in one place, and they cannot drift because there is only one of
    them.

    ## Two decisions inside the marker

    **Unmarked means developer-only**, so the default is a refusal. `RunState`
    is where the machinery accumulates — a tool's arguments and results, a
    grader's reason, a deep agent's files — and a channel added tomorrow by
    somebody thinking about a reducer is refused to a customer without them
    having to think about a boundary at all. This is the direction
    `api/audience.py`'s move 1 already takes for a request.

    **It goes first in the metadata, before the reducer.** LangGraph reads the
    reducer from `__metadata__[-1]` (`langgraph/graph/state.py::_is_field_binop`,
    read off the installed version rather than remembered), so a marker
    appended after a reducer would quietly demote a merged channel to a
    last-value one — an `InvalidUpdateError` shipped by a security fix. Pinned
    in `tests/test_a_stored_run_answers_to_an_audience.py` rather than trusted
    to this paragraph.

    `compile/` cannot import `api/`, so this says *customer-visible* rather
    than naming `api.audience.Audience`. The two meet in `api/audience.py`,
    which is the one module allowed to know both.
    """


#: This channel is part of what a customer's own run already publishes.
CUSTOMER_VISIBLE = _CustomerVisible()


def customer_visible_channels() -> frozenset[str]:
    """The `RunState` channels a customer may read, off the channels themselves.

    The set every door serving a customer filters by. It is deliberately the
    same set a customer's live `done` frame carries — answer, question,
    decisions, routes, outputs, nested outputs and attempts — because a
    customer's *history* being a different shape from their *run* is the
    inconsistency the two audiences exist to remove.
    """
    hints = get_type_hints(RunState, include_extras=True)
    return frozenset(
        name
        for name, annotation in hints.items()
        if any(
            isinstance(item, _CustomerVisible)
            for item in getattr(annotation, "__metadata__", ())
        )
    )


class RunState(TypedDict, total=False):
    """The shared state schema for a compiled workflow."""

    messages: Annotated[list[Any], reducer_for(Reducer.ADD_MESSAGES)]
    question: Annotated[str, CUSTOMER_VISIBLE]
    #: node id -> branch label chosen. Read by the compiler's `path` functions.
    decisions: Annotated[dict[str, Any], CUSTOMER_VISIBLE, reducer_for(Reducer.MERGE)]
    #: agent node id -> tool names the runtime refused, because the model
    #: called something it was never given (`every-workflow-green` 33).
    #:
    #: The deterministic half of the capability offer. `web_fetch is not a
    #: valid tool` is our own sentence, carrying the name, and `tool.web-fetch`
    #: is in the catalogue — so the offer can be a lookup rather than a
    #: sentence a model has to be persuaded to write. MERGE, because several
    #: agents can each reach for something they do not have.
    unmet_tools: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: tool-binding node id -> `{"bound": [...], "ran": [...]}` — the shape of
    #: this run's tool use (`every-workflow-green` 35).
    #:
    #: The other half of the capability offer, and the half that needs no
    #: cooperation at all. `unmet_tools` above reads a name out of our own
    #: refusal, which only exists when the agent *called* something; here it
    #: called nothing, and two rounds of prompt wording failed to make the
    #: model reliably say so. A run that had tools and used none is the case B
    #: shape whether or not it was announced.
    #:
    #: Both lists, not a boolean: "no tools bound" and "tools bound, none used"
    #: are different runs and only the second is offered a door. MERGE_ROWS,
    #: not MERGE: a grader's revise loop re-invokes the same node, and a plain
    #: per-key MERGE let a later lap's row replace an earlier lap's — the
    #: record of a tool that genuinely ran, gone (`production-ready` 106).
    #: `tool_use` records what happened, and what happened does not un-happen,
    #: so a repeat lap's row is merged into the standing one rather than
    #: overwriting it.
    #:
    #: `ran` names tools in our own vocabulary, and a deep agent's delegation
    #: appears there as `delegate:<worker>` rather than as `deepagents`' one
    #: `task` tool (`launch-readiness` 178, `openstategraph/delegations.py`).
    #: MERGE_ROWS matters twice over for that entry: a revision lap must not
    #: overwrite the record of a delegation that already happened.
    tool_use: Annotated[dict[str, Any], reducer_for(Reducer.MERGE_ROWS)]
    #: router node id -> **every** branch label it matched, when that router
    #: runs in `matchMode: "all"` (`every-workflow-green` 27).
    #:
    #: Its own channel rather than a widened `decisions`, which stays a single
    #: label because the compiler's conditional edge dispatches on that exact
    #: key and every trace row, warning and test reads it. Ticket 09 is the
    #: record of learning that a new value there changes control flow.
    #: MERGE, because a document may hold several classifiers.
    routes: Annotated[dict[str, Any], CUSTOMER_VISIBLE, reducer_for(Reducer.MERGE)]
    #: node id -> that node's textual output, so a downstream node can read it.
    outputs: Annotated[dict[str, Any], CUSTOMER_VISIBLE, reducer_for(Reducer.MERGE)]
    answer: Annotated[str, CUSTOMER_VISIBLE, reducer_for(Reducer.LATEST_NONEMPTY)]
    #: output node id -> `{"title", "order"}` for every Output node that
    #: actually finished this run (`launch-readiness/174`).
    #:
    #: **Which exits ran is not a question `answer` can be asked.** A reducer
    #: is handed one update at a time, and LangGraph applies two updates
    #: landing in one superstep exactly as it applies two landing in
    #: successive ones — `f(f(current, u1), u2)` — so `LATEST_NONEMPTY` cannot
    #: tell a *supersession* (a mount writes `answer`, the Output downstream
    #: writes it again) from a *race* (two desks of a `matchMode: "all"`
    #: router finish together). Live, nine times over two documents, the race
    #: kept one desk's answer and no door said the other desk had produced
    #: one. This channel is what makes the two distinguishable after the run,
    #: which is the earliest moment they can be.
    #:
    #: The text is deliberately *not* stored here: `outputs[node_id]` already
    #: holds exactly what this node published, and a second copy is a second
    #: thing to keep true. What is here is what `outputs` cannot say — that
    #: this id is an **exit**, what its author called it, and where it sits in
    #: the document, so a join of several is ordered by the drawing rather
    #: than by whichever task the scheduler happened to finish first.
    #:
    #: MERGE, and every key has exactly one writer — its own node — so the
    #: single-writer argument `revisions` and `forced` rest on holds here too.
    published: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: Same hazard, same fix as `answer`: this document alone has four
    #: `_grader` instances (one per intent), each writing `feedback` on
    #: every step — "" on pass, real text on revise. Found live: two
    #: graders landed in the same superstep and LangGraph raised
    #: `InvalidUpdateError: At key 'feedback': Can receive only one value
    #: per step`, with the raw error then rendered into the chat panel as
    #: if it were the model's own answer.
    feedback: Annotated[str, reducer_for(Reducer.LATEST_NONEMPTY)]
    attempts: Annotated[int, CUSTOMER_VISIBLE, reducer_for(Reducer.MAX)]
    #: grader node id -> how many candidates *that grader* has judged this turn
    #: (`workflow-gallery` 21). The revision budget, and the only counter a
    #: grader's `maxAttempts` is measured against.
    #:
    #: `attempts` above cannot serve, and the ticket is the record of what that
    #: cost. It is one graph-wide integer that every model-driven node
    #: increments once per invocation, so a card reading "2 attempts" bought a
    #: number of laps that depended on the shape of the graph around it: a
    #: cycle holding two agents burned it twice as fast as one holding one, and
    #: a second grader in series inherited the first stage's spend and
    #: force-passed the first candidate it was ever shown. It stays exactly as
    #: it is — it is a true count of model-node invocations and `RunResult`
    #: publishes it — and it is no longer what a budget is checked against.
    #:
    #: **The grader counts, because the grader is the only node that knows a
    #: lap happened.** An agent cannot: it is invoked identically on a first
    #: draft and on a revision, which is precisely why counting at the agent
    #: produced this.
    #:
    #: MERGE, and the key is the grader's own node id, so the single-writer
    #: argument that `forced`, `unrouted` and `verdicts` rest on holds here
    #: too — a node writes only its own row and no two writes of one key can
    #: land in one superstep. Reset at the turn boundary by `_input`, for the
    #: reason `RESET` exists: a checkpointed thread that carried a spent
    #: budget forward would hand turn two a grader with no laps left.
    revisions: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: grader node id -> the reason it rejected the answer it was then forced
    #: to pass (`every-workflow-green` 09). Written only on a force-pass, so
    #: its presence *is* the signal.
    #:
    #: Its own key rather than a `decisions` value, because the compiler routes
    #: on that exact label and a new one there would change control flow. And a
    #: reducer because two graders can exhaust in one run — `feedback` is
    #: `LATEST_NONEMPTY` and would keep only the last.
    forced: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: agent node id -> the deep-agent filesystem tools' `files` dict, as it
    #: stood after that node's last invocation (`launch-readiness/106`).
    #:
    #: `DeepAgentNode`'s compiled agent is invoked fresh — `agent.invoke({...})`
    #: with no config, no checkpointer — every time this node's `run()` runs,
    #: because the compiled sub-agent graph is a plain `Runnable`, not the
    #: thread the outer workflow graph checkpoints. Its own `StateBackend`
    #: keeps files in *that* invocation's state only ("Files persist within a
    #: conversation thread but not across threads" — `deepagents`'s own
    #: docstring), so a write on one call and an `ls` on the next each got a
    #: blank slate: the write always "succeeded" into a dict nobody read
    #: again, and `ls` always found nothing, including on a retry lap of the
    #: very same node in the very same turn. This channel is the carry: `run()`
    #: seeds `invocation["files"]` from here before calling `agent.invoke` and
    #: writes `result.get("files")` back after, so the outer `RunState` — which
    #: *is* checkpointed — is the one store both calls actually share.
    #:
    #: Keyed by node id and MERGE'd rather than a single dict, for the same
    #: reason `revisions`/`forced` are: several deep-agent nodes in one
    #: document must not share a findings store, and a node writes only its
    #: own key.
    agent_files: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: deep-agent node id -> that node's `{task_id: AsyncTask}` map
    #: (`async-first/08`). The same threading as `agent_files` directly above,
    #: for the same reason and by the same code: the agent's own state is
    #: discarded when its node returns, and this is the channel the workflow's
    #: checkpointer persists. Without it a task id would not survive to the turn
    #: that collects the answer, which is the entire point of a child that
    #: outlives the turn.
    #:
    #: The library puts this metadata outside message history deliberately —
    #: *"deep agents compact their message history when the context window fills
    #: up; if task IDs were only in tool messages they would be lost during
    #: compaction"* — and MERGE is what that needs: `check` and `list` can both
    #: write a row in one superstep, which is exactly the named-reducer rule.
    async_tasks: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: grader node id -> the branch label it chose that no edge carries
    #: (`workflow-gallery` 31). Written only when the decision reached nothing,
    #: so its presence *is* the signal — the same shape as `forced` above.
    #:
    #: Not a `decisions` value, for the reason stated there: the compiler
    #: dispatches on that exact label. MERGE, because a document may hold
    #: several graders and more than one can lose a verdict in a run.
    unrouted: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: node id -> the 1-indexed attempt on which that node finally succeeded,
    #: written only when it was more than the first (`memory-and-replay` 41).
    #:
    #: Not written by any node factory. The compiler wraps every node callable
    #: in `recording_attempts` at `add_node`, beside the `retry_policy` that
    #: causes this, because retry is a graph-assembly parameter and not a node
    #: concern — a per-family implementation is one family away from being
    #: forgotten.
    #:
    #: Presence is the signal, the same shape as `forced` and `unrouted`: a
    #: node that got it right first time writes no row. MERGE, because several
    #: nodes can each hit a transient failure in one run and a fan-out can
    #: schedule two of them in the same superstep.
    retries: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: grader node id -> `{"verdict": "pass"|"revise", "reason": str}` — what
    #: the grader actually **thought**, written on every judgement rather than
    #: only on an exceptional one (`workflow-gallery` 32).
    #:
    #: Not readable from `decisions`, and that is the whole reason it exists:
    #: `decisions` holds the *branch* the compiler dispatches on, and at the
    #: attempt cap a grader writes `pass` there for an answer it rejected. A
    #: reviewer told "pass" about an answer nothing passed is worse informed
    #: than one told nothing (gallery ticket 22's hazard, arriving at the one
    #: surface where a person acts on it).
    #:
    #: Not `feedback` either: that is `LATEST_NONEMPTY`, cleared to `""` on a
    #: pass and addressed to the *producer* — `reason` is the sentence written
    #: for a human reading the judgement, which is exactly this reader.
    #:
    #: MERGE, for the reason `forced` and `unrouted` give: a document may hold
    #: several graders and a fan-out can schedule two in one superstep.
    verdicts: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: `"<mount node id>/<child node id>"` -> that node's output, for every
    #: node inside a mounted workflow. Written by `_subgraph`; read by
    #: `/api/runs`, which has no frame stream to rebuild it from the way
    #: `streaming.py` does (`every-workflow-green` 16). MERGE, because a
    #: document may mount several packages and each writes its own keys.
    nested_outputs: Annotated[dict[str, Any], CUSTOMER_VISIBLE, reducer_for(Reducer.MERGE)]
    #: guardrail node id -> what its policy did, as `{entity, strategy,
    #: count}` rows. **Counts and entity types, never values** — the whole
    #: point of the channel is that a developer can see "3 emails redacted
    #: from this answer" without the answer's readers seeing the three emails
    #: (guardrails ticket 03). `abc.guardrail.Redaction` has no field that
    #: could hold one.
    #:
    #: A map with a named reducer from the day it exists, not after the first
    #: `InvalidUpdateError`: an inbound and an outbound guard are two writers
    #: of one key by construction, and a `Send` fan-out can schedule two in
    #: one superstep. That is exactly the hazard `answer` demonstrated live.
    redactions: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
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
    #: grader node id -> the supersteps that were left when it stopped looping
    #: (`organisms-first-class` 56). Presence is the signal, the same shape as
    #: `forced` and `unrouted` above; MERGE for the same reason.
    budget_stops: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]
    #: **Managed, not ours.** LangGraph populates this on every superstep with
    #: the supersteps remaining before `recursion_limit` is reached, and no
    #: node may write it — which is why it carries no reducer and is not
    #: seeded by `ask()` or reset by `_input`.
    #:
    #: It is here so a loop that cannot settle can *degrade* instead of
    #: raising `GraphRecursionError`: the docs call reading it in-graph the
    #: **recommended** approach over catching the error outside, because the
    #: graph then completes normally and the answer it did produce is
    #: published rather than lost. `_grader` is the only reader — the grader's
    #: `revise` is the one branch a cycle may close on.
    remaining_steps: RemainingSteps


def published_routes(state: Mapping[str, Any]) -> dict[str, list[str]]:
    """router node id -> every branch label that router matched, for a reader.

    **The one place `routes` becomes something a door publishes**
    (`launch-readiness/175`). The channel was written by `_router`, read by the
    compiler's own conditional edge, and published by nobody: `RunResult`,
    `RunResponse`, the terminal SSE frame, `run_workflow` and
    `openstategraph run --json` all carried `decisions[router]` alone, which is
    **one** label. So a router that matched one branch and a router that
    matched three were the same row, measured live on `stress-parallel-drop`
    with both desks' answers sitting in `outputs`.

    One function rather than a read at each door, for the reason 174 measured
    rather than assumed: five doors each folding a channel their own way is how
    the same run published the cost desk on `/api/runs/stream` and the risk
    desk on `/api/runs`.

    **`decisions` is read here too, and that is what stops two fields becoming
    two stories.** They are different facts — `decisions[r]` is the single
    label the conditional edge dispatched on, `routes[r]` is every label that
    ran — and the invariant binding them (`decisions[r] in routes[r]`) is
    *produced* here rather than merely asserted somewhere: a router whose row
    somehow omits its own dispatched label gets it appended instead of
    published inconsistently. Only for a node that already has a `routes` row,
    though: `decisions` also holds graders, guards and approvals, and none of
    those has branches to report.

    Read tolerantly, like everything crossing this seam: `routes` is state, so
    its contents are whatever a node wrote. Non-string labels are dropped and
    duplicates collapse, keeping first appearance — the document's declared
    branch order, which is the order the classifier matched in.
    """
    routes = state.get("routes") if hasattr(state, "get") else None
    if not isinstance(routes, Mapping):
        return {}
    decisions = state.get("decisions") or {}
    if not isinstance(decisions, Mapping):
        decisions = {}

    published: dict[str, list[str]] = {}
    for node_id, matched in routes.items():
        if node_id == RESET or not isinstance(matched, (list, tuple)):
            continue
        labels: list[str] = []
        for label in matched:
            text = str(label) if isinstance(label, str) else ""
            if text and text not in labels:
                labels.append(text)
        dispatched = decisions.get(node_id)
        if isinstance(dispatched, str) and dispatched and dispatched not in labels:
            labels.append(dispatched)
        if labels:
            published[str(node_id)] = labels
    return published


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


def _silent_member_note(task_id: str, state: RunState) -> str:
    """What an empty section of a fan-out report says instead of nothing.

    `workflow-gallery` 52. It used to read `_(this member produced no result)_`
    — a true sentence that answers none of the three questions a reader has:
    did this member run, did its loop work, and is there text somewhere that we
    lost? The live symptom is a whole subtask silently unanswered in a report
    that otherwise looks finished.

    Everything here is read off state rather than inferred. `_worker` writes
    `outputs[f"{node}#{task}"]`, so the node behind a member is recoverable,
    and its two empty branches are distinguishable: `NO_MODEL_MARKER` means no
    model was ever called, and anything else empty means one was called and
    returned nothing — which `production-ready` 96 settled off the raw Ollama
    wire (`content=''`, `thinking=None`, `done_reason='stop'`) as the model
    genuinely stopping, not as text lost in extraction.

    **No tool is named here, deliberately.** Every dispatched instance shares
    one node id, so `tool_use` is per node; naming a call inside one member's
    section would attribute a sibling's work to this subtask. The node-level
    sentence in `silent_node_warnings` says "the node called X during this
    run", which is what is actually known.
    """
    outputs = state.get("outputs") or {}
    owner = next(
        (str(key).split("#", 1)[0] for key in outputs if str(key).endswith(f"#{task_id}")),
        "",
    )
    if not owner:
        # Nothing wrote an output under this task id at all, so there is no
        # node to name and nothing measured to say about it.
        return "_(this member produced no result)_"
    if str(outputs.get(f"{owner}#{task_id}") or "") == NO_MODEL_MARKER:
        return (
            f"_(no model was configured for `{owner}`, so nothing ran for this "
            "subtask. Set a model on the node or a default for the workflow.)_"
        )
    return (
        f"_(`{owner}` ran this subtask and its model returned no text, so it is "
        "unanswered.)_"
    )


def _upstream_text(state: RunState, node_ids: list[str]) -> str:
    outputs = state.get("outputs") or {}
    return "\n".join(outputs[n] for n in node_ids if n in outputs)


def published_exits(state: Any) -> list[tuple[str, str]]:
    """`(node id, text)` for every exit that finished this run with something
    to say, in the order the document draws them.

    Ordered by the drawing rather than by arrival, because arrival order is a
    property of the scheduler: two exits of a `matchMode: "all"` router finish
    in one superstep and whichever task got there first would otherwise decide
    what a reader sees first. `order` is the node's index in the document, so
    the reader gets the desks top to bottom.

    Three kinds of row are dropped, and each drop is the difference between a
    join and a mess: an exit that produced nothing, an exit that published the
    `NO_ANSWER_PRODUCED` floor (appending *"the workflow finished without
    producing an answer"* to an answer that exists would be a false sentence
    about a true one), and an exit whose text is one another exit already
    published — two Outputs fed by one node are one answer drawn twice.

    Tolerant about its input for `run_health`'s reason: the doors read state
    off different shapes and any of them can hand over `None`.
    """
    rows = state.get("published") if hasattr(state, "get") else None
    outputs = (state.get("outputs") if hasattr(state, "get") else None) or {}
    if not isinstance(rows, dict) or not isinstance(outputs, dict):
        return []

    def position(row: Any) -> int:
        if isinstance(row, dict):
            try:
                return int(row.get("order"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0
        return 0

    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for node_id, row in sorted(
        ((k, v) for k, v in rows.items() if k != RESET),
        key=lambda item: (position(item[1]), str(item[0])),
    ):
        text = str(outputs.get(node_id) or "")
        if not text.strip() or text.strip() == NO_ANSWER_PRODUCED or text in seen:
            continue
        seen.add(text)
        found.append((str(node_id), text))
    return found


def published_answer(state: Any) -> str:
    """A run's answer as a reader must receive it — `launch-readiness/174`.

    **The one seam every door reads the answer through**, and the reason it is
    a seam rather than a line in each of them is the defect it fixes: five
    doors each wrote `str(final.get("answer") or "")`, and a document whose
    parallel router opened two desks handed *different* halves to different
    doors of the same run — the streaming door published the cost desk and the
    blocking door the risk desk, measured. `test_a_runs_diagram_opens_its_mounts.py`
    is the precedent for the shape and
    `test_every_door_reads_the_whole_answer.py` is the test that fails when a
    sixth door writes its own.

    One exit, which is every document in `examples/` and every document
    anybody has drawn on purpose, returns `answer` untouched — byte for byte,
    including the `NO_ANSWER_PRODUCED` floor and `127`'s substitution notice.
    Two or more, and the answer is the join, which is `_upstream_text`'s join
    exactly: `"\n"`, no labels, in document order. That is not a new
    rendering — it is the rendering the platform already produces when both
    desks are wired into **one** Output, which is the drawing `capacityRule`
    forbids and which has always answered correctly. Making the permitted
    drawing and the forbidden one produce the same string is the whole point:
    until now the reachable shape was the lossy one.

    `every-workflow-green` 27 met this loss one node upstream and answered it
    the same way — by *gathering* the branches into `function.format_report`
    rather than by refusing the drawing. This is that answer at the last node,
    where it needs nothing of the author.
    """
    answer = str((state.get("answer") if hasattr(state, "get") else "") or "")
    exits = published_exits(state)
    if len(exits) < 2:
        return answer
    return "\n".join(text for _node_id, text in exits)


def _upstream_verdict(state: RunState, node_ids: list[str]) -> dict[str, str]:
    """What the grader that produced this node's input thought of it.

    `workflow-gallery` 32. Returns `{"verdict", "reason"}` — plus `check` when
    a deterministic check rejected the candidate without a model call
    (`production-ready` 92) — or an empty dict
    when no grader is immediately upstream — so a caller adds nothing rather
    than adding two empty keys, and a client can read absence as "no machine
    opinion exists" instead of "the machine had nothing to say".

    **Immediate producers only, and no walk further back.** Several graders can
    sit upstream of one gate along a chain, and a judgement of *some earlier
    text* captioning *this* text would be a confident wrong statement rather
    than a missing one. The same `node_ids` list `_upstream_text` uses to build
    the candidate builds the verdict, so the text and its judgement can never
    come from different places.

    First match in that list wins where a node has more than one graded
    producer. That is a genuine choice and not an accident: the alternative —
    concatenating verdicts the way `_upstream_text` concatenates text — would
    give a `verdict` field two values, and the field is what a reviewer acts
    on. A fan-in of several graders into one gate is `workflow-gallery` 48's
    territory and is not drawable today.
    """
    verdicts = state.get("verdicts") or {}
    for node_id in node_ids:
        row = verdicts.get(node_id)
        if isinstance(row, dict) and row.get("verdict"):
            found = {"verdict": str(row["verdict"]), "reason": str(row.get("reason") or "")}
            # Only when one actually fired. An empty `check` is the ordinary
            # case — a model judged it — and a key present-but-empty would
            # make a reviewer's client distinguish "" from absent to learn
            # nothing (`production-ready` 92).
            if row.get("check"):
                found["check"] = str(row["check"])
            return found
    return {}


def _wired_skill(
    state: RunState,
    node_ids: list[str],
    sources: Mapping[str, Any] | None = None,
) -> str:
    """The prompt contribution of whatever is wired to a node's `skill` port.

    Frontmatter is stripped here rather than at the reading node: a skill can
    arrive from a picked `SKILL.md`, from a pasted instruction, or from a file
    an upstream node loaded, and only one of those has ever heard of YAML.

    **State first, then the compiler's resolved sources — and the second half
    was the one that was missing.** A skill source is `bound_only`: it is
    deliberately kept out of `plan.nodes`, because it is configuration hanging
    off a port rather than a step in the graph. It therefore never runs, never
    writes `outputs`, and this function — reading only state — returned `""`
    for every wired skill on every node type, always. The shipped
    `sql-analyst.md` never reached the analyst; the whole layer was decorative
    at runtime.

    Reading configuration is not a fallback bolted on, it is the correct source
    for this kind of node: `_static_text`'s output does not depend on state at
    all, and the `skill` port type is produced only by `input.markdown` and
    `input.skill`, both static. State is still consulted first, so a future
    dynamic producer keeps working without another change here.

    **`sources` is `NodeRuntime.static_sources`, not the document's nodes**
    (`launch-readiness` 94). This function used to read `instruction` →
    `instructions` → `content` off each node's `data` itself, which made it the
    *second* module implementing that precedence — and neither of the two knew
    `filename` existed, so a skill node pointing at a file on disk was shown to
    the model as whatever stale copy happened to be pasted beside it. One
    module decides now, at compile time, and this one reads what it decided.
    """
    from openstategraph.skills import skill_text

    live = _upstream_text(state, node_ids)
    if live.strip():
        return skill_text(live)

    if not sources:
        return ""
    configured = "\n".join(
        text
        for text in (
            getattr(sources.get(node_id), "text", "") for node_id in node_ids
        )
        if text
    )
    return skill_text(configured)
