"""The run's edges: what enters, what leaves, and what a node nobody knows does.

Four families with one reason to change between them — **the boundary of a
run**. `_input` is the entry and owns the turn reset; `_static_text` is the
node that is text and deliberately owns none of it; `_output` is where "the
run's answer" is *defined*, which is why the empty-answer floor, the
substitution disclosure and the conversation record all land there and nowhere
else; `_passthrough` is the exit a node type this build cannot resolve takes,
and the reason it is loud.

`_static_text` and `_input` are here together on purpose rather than by
alphabet: this file's own second paragraph is an account of what it cost when
they were one builder, and keeping them adjacent is what keeps the difference
readable.

`compile/nodes/__init__.py` carries the argument for the package, the binding
mechanism, and why the first parameter is still called `self`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.abc.tool_notes import notes_for_reader, take_notes
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.context import _text
from openstategraph.compile.reporting import _values_never_sent
from openstategraph.compile.run_context import render_run_context
from openstategraph.compile.state import (
    NO_ANSWER_PRODUCED,
    RESET,
    RunState,
    _upstream_text,
)
from openstategraph.compile.static_source import resolve_static_source
from openstategraph.compile.workflow_compiler import (
    GUARDRAIL_TYPE,
    CompiledPlan,
    failure_marker,
)
from openstategraph.developer_channel import transcript_text

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _static_text(self: "NodeRuntime", node_id: str, node: dict[str, Any], _plan: CompiledPlan) -> Any:
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
    # One seam, never the fields. `factory()` resolved this already, file
    # against stored copy, and recorded whatever they disagreed about
    # (`launch-readiness` 94). The fallback is for a runtime handed a node
    # without a document — a direct unit call — and goes through the same
    # function, so there is still exactly one precedence in the codebase.
    source = self.static_sources.get(node_id) or resolve_static_source(
        node_id, node.get("data") or {}, self.services.skills_package_dir
    )
    configured = source.text

    def run(_state: RunState) -> dict[str, Any]:
        # The author's own text, so the author's own `{{key}}` slots are
        # filled from the run's context (organisms-first-class/71). A
        # workflow declaring nothing gets its text back byte-identical.
        return {"outputs": {node_id: render_run_context(configured)}}

    return run


def _input(self: "NodeRuntime", node_id: str, node: dict[str, Any], _plan: CompiledPlan) -> Any:
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
            # Which exits finished is a fact about *this* turn
            # (`launch-readiness/174`). A checkpointed thread that carried
            # turn one's exits forward would have turn two's single desk
            # joined onto a stale second one — the very silence this
            # channel was added to end, inverted.
            "published": {RESET: ""},
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


def _output(self: "NodeRuntime", node_id: str, _node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Collects whatever reached it as the run's answer."""
    upstream = [src for src, dst in plan.edges if dst == node_id]
    # What this exit is called and where it sits, read from the document
    # once at build time so the run carries no lookup (`launch-readiness/174`).
    # `self._types` is built in document order, which is the order a reader
    # sees the desks drawn in and the order `published_answer` joins them.
    exit_row = {
        "title": str(_node.get("title") or ""),
        "order": list(self._types).index(node_id) if node_id in self._types else 0,
    }
    conditional_upstream = [
        src for src, dests in plan.conditional.items() if node_id in dests.values()
    ]
    # Guardrails ticket 02: the outbound guard is a node you place, and
    # what makes its absence loud is here. Only reported when the document
    # *has* a policy — see `Finding.UNGUARDED_EXIT` for why the absent
    # case is deliberately silent.
    if GUARDRAIL_TYPE in self._types.values() and not self._guarded_upstream(node_id, plan):
        self.diagnostics.record(Finding.UNGUARDED_EXIT, node_id)
    # `launch-readiness` 151: the same question one axis over — not "did a
    # policy get bypassed" but "can a model-supplied quantity reach this
    # Output with nothing between". Here for `UNGUARDED_EXIT`'s reason:
    # an Output is the one node that knows what "reaching the reader"
    # means, and both walks are backwards from it.
    self._report_undeclared_fallback(node_id, plan)

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

        # `launch-readiness/127`. A word the user typed that the data does
        # not hold gets replaced by one it does, and until now nothing
        # said so: three live runs of "list the ports in the persian gulf"
        # returned 628, 68 and an invented set, and at the moment each was
        # produced a reader could not tell them apart.
        #
        # Rendered **here** rather than asked of the model, because a
        # model instructed to disclose discloses most of the time, and
        # "most of the time" is the whole defect. The resolver records the
        # fact (`abc/tool_notes.record_notes`, called by `BaseTool.run`
        # for every tool there is); this node — the one place "the run's
        # answer" is defined — renders it. Only where the user's word and
        # the canonical value actually differ, and always carrying
        # `how_matched`, so a substitution the model inferred for itself
        # can never arrive labelled as one the data declared.
        # `launch-readiness/155`. The sentence above says *"the answer
        # above is for X"*, and a run that answered nothing still got it:
        # live, an agent that asked the user which sense of "Persian Gulf"
        # they meant — and called no tool at all — published that claim
        # about a result that does not exist. Whether the run reached its
        # data is a fact about its own record, read here where the record
        # is in hand, and never a question put to the model: `127`'s whole
        # argument is that the disclosure is not the model's to forget.
        recorded = take_notes()
        disclosure = notes_for_reader(
            recorded, unsent_values=_values_never_sent(state, recorded)
        )
        if disclosure:
            answer = f"{answer}\n\n{disclosure}"

        # `answer`, not `text`: this node's own output IS the run's answer,
        # and the card on the canvas is fed from `outputs[node]` while the
        # chat is fed from `answer`. Publishing the raw upstream text here
        # made the two disagree in exactly the cases the fallback and the
        # floor exist for — an answer that arrived by another path (a
        # mount's, most often) or no answer at all showed a blank Answer
        # card beside a chat bubble that had one. Reported by a tester on
        # `?w=concierge`: "the end node answer remaining empty while the
        # answer is already produced."
        # `published` says *this exit finished*, which is the one thing
        # `outputs` cannot say and `answer` cannot be asked. See
        # `RunState.published`: a document may legitimately have two exits
        # that both complete, and until this row existed the run kept one
        # answer and no door could tell that from a run with one exit.
        update: dict[str, Any] = {
            "answer": answer,
            "outputs": {node_id: answer},
            "published": {node_id: exit_row},
        }
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


def _passthrough(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
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
