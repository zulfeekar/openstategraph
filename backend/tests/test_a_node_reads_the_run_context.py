"""A node reads what the caller supplied — `organisms-first-class/71`.

Step 5 of the seven in `docs/decisions/runtime-context.md`, and the first of
the three read doors. 67 made a document able to *say* what its runs carry, 69
turned that into a `context_schema`, 70 put a validator at all three supply
doors. Until this ticket nothing read a value back, so the whole channel was
provably wired and provably useless.

**What would still be green if the wrong thing were built?** A test of
`render_run_context()` in isolation would pass against a renderer no node ever
calls, exactly as 70 found a validator tested away from its doors proves
nothing. So the demonstration below compiles a real document with the real
`WorkflowCompiler` and the real `NodeRuntime`, really runs it, and asserts on
the answer that came out — the value has to survive the mint, the supply and
the read to appear there.

The inverses matter as much as the demonstration, and there are four: a
workflow declaring nothing runs exactly as it did and its nodes touch no
context; a declared key nobody supplied a value for leaves the author's text
alone rather than deleting it; the *caller's question* is never rendered,
because it is not the author's text; and the prompted families are untouched —
their context arrives as a generated section in 72, and two mechanisms writing
one prompt is the duplication rule broken.
"""

from __future__ import annotations

from typing import Any

import pytest

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.run_context import render_run_context, run_context
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.run_identity import RUN_IDENTITY_KEYS, run_identity

#: Obvious placeholders. A feature about tenants is exactly where a real
#: looking identity slips into a repository.
TENANT = "tenant-placeholder"

DECLARATION = [
    {"key": "tenant", "type": "string", "label": "Tenant", "required": True},
    {"key": "caseId", "type": "string", "label": "Case id", "default": "C-0"},
    {"key": "maxRefunds", "type": "number", "label": "Refund ceiling", "default": 3},
    {"key": "dryRun", "type": "boolean", "label": "Dry run", "default": False},
]


def _document(prompt: str, context: Any = None) -> dict[str, Any]:
    """input -> output, the whole graph, with no model anywhere in it."""
    document: dict[str, Any] = {
        "version": 1,
        "name": "run-context-read",
        "nodes": [
            {
                "id": "in1",
                "type": "input.text",
                "position": {"x": 0, "y": 0},
                "data": {"prompt": prompt},
            },
            {
                "id": "out1",
                "type": "output.formatted",
                "position": {"x": 200, "y": 0},
                "data": {},
            },
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }
    if context is not None:
        document["settings"] = {"context": context}
    return document


def _run(document: dict[str, Any], **invoke: Any) -> dict[str, Any]:
    runtime = NodeRuntime(model=None)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke({"messages": [], "question": ""}, **invoke)


def _answer(result: dict[str, Any]) -> str:
    return str(result.get("answer") or result.get("outputs", {}).get("out1") or "")


# --------------------------------------------------------------------------- #
# The demonstration.
# --------------------------------------------------------------------------- #


class TestASuppliedValueReachesANodesOutput:
    def test_the_answer_depends_on_what_the_caller_supplied(self) -> None:
        document = _document("This run is for {{tenant}}.", DECLARATION)

        result = _run(document, context={"tenant": TENANT})

        assert _answer(result) == f"This run is for {TENANT}."

    def test_the_same_workflow_answers_differently_for_a_second_caller(self) -> None:
        """The point of the channel, and not provable from one run.

        A node that hard-coded anything, or that read the *declaration* rather
        than the run, passes the test above and fails this one.
        """
        document = _document("This run is for {{tenant}}.", DECLARATION)

        first = _answer(_run(document, context={"tenant": TENANT}))
        second = _answer(_run(document, context={"tenant": "other-placeholder"}))

        assert first != second
        assert "other-placeholder" in second

    def test_a_declared_default_is_what_an_omitting_caller_reads(self) -> None:
        document = _document("Case {{caseId}}, up to {{maxRefunds}}.", DECLARATION)

        result = _run(document, context={"tenant": TENANT})

        assert _answer(result) == "Case C-0, up to 3."

    def test_a_skill_node_renders_its_own_text_too(self) -> None:
        """`input.markdown` / `input.skill` are `_static_text`, not `_input`.

        Two builders, so a fix wired into one is invisible in the other — the
        exact shape of the miss `skills/ticket-loop` warns about.
        """
        runtime = NodeRuntime(model=None)
        node = {"id": "s1", "type": "input.markdown", "data": {"content": "Serving {{tenant}}."}}
        document = {"version": 1, "name": "skill", "nodes": [node], "edges": []}
        build = runtime.factory(document)
        run = build("s1", node, WorkflowCompiler().plan(document))

        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(RunState, context_schema=_schema())
        graph.add_node("s1", run)
        graph.add_edge(START, "s1")
        graph.add_edge("s1", END)
        result = graph.compile().invoke(
            {"messages": [], "question": ""}, context={"tenant": TENANT}
        )

        assert result["outputs"]["s1"] == f"Serving {TENANT}."


def _schema() -> Any:
    from openstategraph.compile.run_context import mint_context_schema

    return mint_context_schema({"settings": {"context": DECLARATION}})


# --------------------------------------------------------------------------- #
# The inverses.
# --------------------------------------------------------------------------- #


class TestAWorkflowThatDeclaresNothingIsUnchanged:
    def test_a_placeholder_survives_verbatim_when_nothing_is_declared(self) -> None:
        result = _run(_document("This run is for {{tenant}}."))

        assert _answer(result) == "This run is for {{tenant}}."

    def test_ordinary_text_is_byte_identical(self) -> None:
        text = "Summarise the ticket. Use {json} braces, {{ and }} too."
        result = _run(_document(text))

        assert _answer(result) == text

    def test_the_accessor_is_empty_outside_a_run(self) -> None:
        """`get_runtime()` raises with no runnable context; `{}` is the answer."""
        assert run_context() == {}


class TestOnlyTheAuthorsOwnTextIsRendered:
    def test_the_callers_question_is_never_rendered(self) -> None:
        """The question is the caller's own words, and `{{tenant}}` in it is a
        string they typed — not a slot the workflow's author opened. Rendering
        it would let a caller read a value the author never chose to show."""
        document = _document("unused", DECLARATION)
        runtime = NodeRuntime(model=None)
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        result = graph.invoke(
            {"messages": [], "question": "who is {{tenant}}?"},
            context={"tenant": TENANT},
        )

        assert _answer(result) == "who is {{tenant}}?"

    def test_an_undeclared_key_is_left_exactly_as_written(self) -> None:
        document = _document("Hello {{nobody}} and {{tenant}}.", DECLARATION)

        result = _run(document, context={"tenant": TENANT})

        assert _answer(result) == f"Hello {{{{nobody}}}} and {TENANT}."

    def test_a_declared_key_with_no_value_is_left_alone_not_blanked(self) -> None:
        declaration = [
            {"key": "tenant", "type": "string", "label": "Tenant", "required": True},
            {"key": "locale", "type": "string", "label": "Locale"},
        ]
        document = _document("[{{locale}}] for {{tenant}}.", declaration)

        result = _run(document, context={"tenant": TENANT})

        assert _answer(result) == f"[{{{{locale}}}}] for {TENANT}."

    def test_a_key_that_cannot_be_a_field_name_is_prose(self) -> None:
        """`case-id` is a legal JSON key and an illegal field name, so 69 mints
        no schema for the whole declaration. The text must still survive."""
        document = _document("Case {{case-id}}.", [{"key": "case-id", "type": "string", "label": "C"}])

        assert _answer(_run(document)) == "Case {{case-id}}."


class TestThePromptedFamiliesAreNotRenderedHere:
    """72 builds the generated **Context** section, with per-field opt-in.

    A second mechanism writing the same prompt is the duplication rule broken,
    and it would defeat the opt-in that keeps an API handle out of a model. So
    an agent's own instruction is left exactly as the author wrote it — for
    now, deliberately, and this test is what says so out loud.
    """

    def test_an_agents_instruction_is_not_substituted(self) -> None:
        from tests.conftest import RespondingModel

        seen: list[str] = []
        model = RespondingModel([], default="done")
        document = {
            "version": 1,
            "name": "agent-context",
            "settings": {"context": DECLARATION},
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "go"}},
                {
                    "id": "a1",
                    "type": "agent.llm",
                    "position": {"x": 200, "y": 0},
                    "data": {"instruction": "You serve {{tenant}}."},
                },
                {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "a1", "portId": "prompt"}},
                {"source": {"nodeId": "a1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }
        runtime = NodeRuntime(model=model)
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        graph.invoke({"messages": [], "question": "hello"}, context={"tenant": TENANT})

        seen = list(model.calls)
        assert seen, "the scripted model was never called"
        assert TENANT not in " ".join(seen)


class TestTheTwoChannelsStaySeparate:
    """`configurable` is who the run is *for*; `context` is what the workflow
    asked its caller for. Both reach a node, through two accessors, and neither
    leaks into the other."""

    @staticmethod
    def _probe(seen: dict[str, Any]) -> Any:
        def factory(node_id: str, _node: dict, _plan: Any) -> Any:
            def run(_state: RunState) -> dict[str, Any]:
                seen["identity"] = run_identity()
                seen["context"] = run_context()
                return {"outputs": {node_id: ""}}

            return run

        return factory

    def test_a_node_reads_both_and_neither_carries_the_other(self) -> None:
        seen: dict[str, Any] = {}
        document = _document("{{tenant}}", DECLARATION)
        graph = WorkflowCompiler().build(document, RunState, self._probe(seen))

        graph.invoke(
            {"messages": [], "question": ""},
            context={"tenant": TENANT},
            config={"configurable": {"thread_id": "t-1", "user_email": "someone@example.invalid"}},
        )

        assert set(seen["identity"]) == set(RUN_IDENTITY_KEYS)
        assert set(seen["context"]) == {f["key"] for f in DECLARATION}
        assert TENANT not in seen["identity"].values()
        assert seen["context"]["tenant"] == TENANT
        assert "thread_id" not in seen["context"]


# --------------------------------------------------------------------------- #
# How a value is spelled, and where that decision lives.
# --------------------------------------------------------------------------- #


class TestHowAValueIsSpelled:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, "true"),
            (False, "false"),
            (3, "3"),
            (3.0, "3"),
            (3.5, "3.5"),
            ("acme", "acme"),
        ],
    )
    def test_one_value_one_spelling_whichever_door_it_came_by(
        self, value: Any, expected: str
    ) -> None:
        """`--context dryRun=false` and `{"dryRun": false}` are one value, and
        a node's text must not reveal which door the run came in by. Python's
        own `True`/`False` would be a third spelling of a value nobody typed
        that way, and `3.0` is the CLI's `float()` leaking into an answer."""
        assert render_run_context("{{k}}", {"k": value}) == expected

    def test_whitespace_inside_the_braces_is_tolerated(self) -> None:
        assert render_run_context("{{ tenant }}", {"tenant": TENANT}) == TENANT

    def test_every_occurrence_is_filled_not_only_the_first(self) -> None:
        assert render_run_context("{{a}}/{{a}}", {"a": "x"}) == "x/x"
