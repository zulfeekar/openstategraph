"""The build door stops depending on the model choosing to knock.

`every-workflow-green` 35. `advisor_context` says, in as many words, *"whenever
you are blocked for want of a capability you must always emit the block"* — and
the same question on the same workflow produced the block on one run and only a
sentence on the next. A developer who hits the silent run has no way to know a
door exists.

The wording had already been escalated twice, each round changing the rate and
none removing the failure, which is the signature of the wrong lever. So the
door is offered on the **shape of the run** instead: a run that had tools and
called none of them, produced no suggestion, and left no gap behind is the case
B shape whether or not the model said so.

Two things this deliberately is *not*:

- **It is not a claim about what the run meant.** The shape cannot know a
  refusal from a knowledge answer, so the card it opens may only say what the
  shape proves — see `src/view/ask/AskPanel.tsx`, where an empty gap renders
  different words from a described one.
- **It is not a second chance for the model.** When the model *did* describe
  the gap, that description still wins; the shape only fills the silence.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from openstategraph.compile.workflow_compiler import capability_door, used_no_tools

BOUND_AND_UNUSED = {"agent-1": {"bound": ["chinook_query"], "ran": []}}
BOUND_AND_USED = {"agent-1": {"bound": ["chinook_query"], "ran": ["chinook_query"]}}
NO_TOOLS_AT_ALL = {"writer-1": {"bound": [], "ran": []}}

DECLINE = (
    "I can't post to Slack.\n\n"
    '```suggestion\n{"nodeType": "none", "attachTo": "agent-1", "port": "tools", '
    '"label": "", "reason": "no way to send a Slack message"}\n```'
)


class TestTheShapeAlone:
    """No fence, no suggestion — the run's own shape has to carry it."""

    def test_tools_bound_and_none_run_opens_the_door(self) -> None:
        assert capability_door("I can't post to Slack.", None, BOUND_AND_UNUSED) == ""

    def test_a_run_that_used_its_tools_offers_nothing(self) -> None:
        """The negative control, measured live: a real Chinook answer ran two
        tools and drew no card. That is the whole of "answered normally" that
        the shape can see."""
        assert capability_door("Rock earns the most.", None, BOUND_AND_USED) is None

    def test_a_workflow_with_no_tools_at_all_offers_nothing(self) -> None:
        """A writer agent has nothing bound, so "nothing here does this" is not
        a statement about it. Without this clause the card would appear on
        every turn of a tool-less workflow — the happy-path noise CLAUDE.md
        warns about, which is how a channel teaches people to skip it."""
        assert capability_door("Here is your paragraph.", None, NO_TOOLS_AT_ALL) is None

    def test_no_record_at_all_offers_nothing(self) -> None:
        """A run with no tool-bearing node writes no key. Absent is not empty."""
        assert capability_door("Hello.", None, {}) is None
        assert capability_door("Hello.", None, None) is None


class TestWhatTheModelSaidStillWins:
    def test_a_described_gap_is_kept_word_for_word(self) -> None:
        assert capability_door(DECLINE, None, BOUND_AND_UNUSED) == (
            "no way to send a Slack message"
        )

    def test_a_described_gap_survives_a_run_that_used_its_tools(self) -> None:
        """Ticket 34's route is untouched: the shape only fills a silence."""
        assert capability_door(DECLINE, None, BOUND_AND_USED) == (
            "no way to send a Slack message"
        )

    def test_a_placeable_suggestion_is_not_something_to_build(self) -> None:
        """A gap a catalogue entry covers is an Add & re-run card, not an
        interview — and that stays true however empty the run's shape looks."""
        offer = {"nodeType": "tool.web-search", "attachTo": "agent-1"}
        assert capability_door("No live data.", offer, BOUND_AND_UNUSED) is None


class TestTheVerdictItself:
    def test_bound_but_unused_is_the_shape(self) -> None:
        assert used_no_tools(BOUND_AND_UNUSED) is True

    def test_one_node_using_a_tool_answers_for_the_whole_run(self) -> None:
        """Any tool anywhere in the run defeats it. A workflow whose SQL agent
        answered and whose summariser did not is not a workflow that lacks a
        capability."""
        assert used_no_tools({**BOUND_AND_UNUSED, "agent-2": {"bound": ["x"], "ran": ["x"]}}) is False

    def test_rubbish_rows_are_ignored_rather_than_fatal(self) -> None:
        assert used_no_tools({"a": "not a row", "b": None}) is False
        assert used_no_tools("not a map") is False


class TestNeitherDoorAsksTheQuestionItself:
    """The rule `run_health` exists for, applied to the second verdict.

    `/api/runs` and `/api/runs/stream` each assembled the capability gap
    locally — one call to `capability_gap` apiece — which is the shape that
    drifted twice already (`every-workflow-green` 14, 16). One function, called
    from both, cannot disagree with itself.
    """

    DOORS = ("streaming", "routes.runs")

    def _source(self, module: str) -> str:
        import importlib

        target = importlib.import_module(f"openstategraph.api.{module}")
        return Path(inspect.getfile(target)).read_text(encoding="utf-8")

    def test_both_doors_call_the_shared_verdict(self) -> None:
        for module in self.DOORS:
            assert "capability_door(" in self._source(module), module

    def test_neither_door_reads_the_fence_on_its_own(self) -> None:
        for module in self.DOORS:
            assert "capability_gap(" not in self._source(module), module


class TestWhatTheRuntimeRecords:
    """`tool_report` is the seam both tool-binding factories call.

    One function rather than two calls per site, because `every-workflow-green`
    36 is the record of what two calls costs: `advisor_context` was composed
    into `_agent` and not `_worker`, so `morning-brief` asked for a tool we
    ship and no card appeared. A factory that can be refused a tool can also
    decline to use one, and both facts have to leave by the same door.
    """

    def _tool(self, name: str, content: str) -> object:
        from langchain_core.messages import ToolMessage

        return ToolMessage(content=content, name=name, tool_call_id=f"c-{name}")

    def test_a_tool_that_ran_is_recorded(self) -> None:
        from openstategraph.compile.node_runtime import tool_report

        update = tool_report("agent-1", [self._tool("chinook_query", "3 rows")], ["chinook_query"])
        assert update["tool_use"] == {"agent-1": {"bound": ["chinook_query"], "ran": ["chinook_query"]}}

    def test_a_tool_that_ran_and_errored_still_ran(self) -> None:
        """`the-agent-asks-for-what-it-cannot-get` 01: errors are data. A bound
        tool that answered "No recipient configured" is wired, and a run that
        used it is not a run missing a capability."""
        from openstategraph.compile.node_runtime import tool_report

        update = tool_report("a1", [self._tool("email_send", "Error: no recipient")], ["email_send"])
        assert update["tool_use"]["a1"]["ran"] == ["email_send"]

    def test_a_name_the_runtime_refused_did_not_run(self) -> None:
        """The refusal comes back as a `ToolMessage` too, and counting it as a
        use would close the door on precisely the run that needs it."""
        from openstategraph.compile.node_runtime import tool_report

        refusal = self._tool("web_fetch", "Error: web_fetch is not a valid tool, try one of [...]")
        update = tool_report("a1", [refusal], ["chinook_query"])
        assert update["tool_use"]["a1"]["ran"] == []
        assert update["unmet_tools"] == {"a1": ["web_fetch"]}

    def test_a_node_with_no_tools_bound_still_reports(self) -> None:
        """Absent and empty must not look the same to the verdict: a run that
        recorded nothing cannot be told from a workflow with no tools, and one
        of those deserves the door while the other does not."""
        from openstategraph.compile.node_runtime import tool_report

        assert tool_report("w1", [], [])["tool_use"] == {"w1": {"bound": [], "ran": []}}

    def test_nothing_refused_writes_no_unmet_key(self) -> None:
        from openstategraph.compile.node_runtime import tool_report

        assert "unmet_tools" not in tool_report("a1", [], ["t"])


class TestBoundMeansWiredOnTheCanvas:
    """Found in the browser, after the suite was green.

    `skill-driven-rubric` wires no tool nodes at all, and a perfectly good
    "write one sentence" answer drew the build card. The reason is that
    `_bind_tools` is not the end of the list: a configured memory store appends
    `save_memory`/`search_memory` to **every** agent, and a package with a
    `knowledge/` directory appends the lookup tool. So almost every agent has
    something bound, and the clause meant to keep the card off tool-less
    workflows was protecting nothing.

    `bound` therefore means *wired on the canvas*, which is also the only
    reading a developer can act on — the card asks them to build a tool for
    this workflow, and an ambient capability is not one. `ran` stays wide: an
    agent that reached for its memory was not stuck.

    Asserted on the order of the source rather than on a spelling, because the
    defect is entirely one of *when* the snapshot is taken.
    """

    def _factory(self, name: str) -> str:
        import ast as _ast

        from openstategraph.compile import node_runtime as module

        tree = _ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))
        (cls,) = [n for n in _ast.walk(tree) if isinstance(n, _ast.ClassDef) and n.name == "NodeRuntime"]
        (fn,) = [m for m in cls.body if isinstance(m, _ast.FunctionDef) and m.name == name]
        return _ast.unparse(fn)

    def test_the_snapshot_is_taken_before_the_ambient_tools_arrive(self) -> None:
        for name in ("_agent", "_worker"):
            source = self._factory(name)
            snapshot = source.index("wired = ")
            for ambient in ("_attach_ambient_knowledge", "memory_tools"):
                if ambient in source:
                    assert snapshot < source.index(ambient), (name, ambient)

    def test_neither_factory_reports_the_mutated_list(self) -> None:
        """The snapshot, not the list that keeps growing under it.

        Read off the call's **third argument** rather than off `", wired)"`,
        which is what this line matched until `launch-readiness` 103 added a
        fourth (`unbound`). A trailing-paren match asserts the argument's
        position only for as long as it happens to be last, so the fix that
        added an argument reddened a test about something else entirely.
        """
        import ast as _ast

        for name in ("_agent", "_worker"):
            tree = _ast.parse(self._factory(name))
            calls = [
                n
                for n in _ast.walk(tree)
                if isinstance(n, _ast.Call)
                and isinstance(n.func, _ast.Name)
                and n.func.id == "tool_report"
            ]
            assert calls, name
            for call in calls:
                assert _ast.unparse(call.args[0]) == "node_id", name
                assert _ast.unparse(call.args[2]) == "wired", name
