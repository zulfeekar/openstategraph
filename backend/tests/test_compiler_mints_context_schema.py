"""The declaration becomes a class, and the class never leaves the build.

`organisms-first-class/69`, step 3 of the seven in
`docs/decisions/runtime-context.md`. Ticket 67 made a document able to *say*
what its runs carry; this is the first thing that listens. Nothing supplies a
value yet (70) and nothing reads one (71), so what is asserted here is what a
compiled graph now *carries*: a `context_schema` whose shape is the document's,
and — for a document that declares nothing — no argument at all.

The question these tests are written against is *what would still be green if I
built the wrong thing?* A test that `make_dataclass` was called would pass
against a class the graph never received, so every assertion below goes through
a really compiled graph: the schema is read off the compiled object, and the
value is read by a node that actually ran.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Annotated, Any, TypedDict

import pytest
from langgraph.graph.message import add_messages
from langgraph.runtime import get_runtime

from openstategraph.compile.run_context import CONTEXT_SCHEMA_NAME, mint_context_schema
from openstategraph.compile.workflow_compiler import WorkflowCompiler


class State(TypedDict):
    messages: Annotated[list, add_messages]
    decisions: dict
    seen: dict


TENANT = "tenant-placeholder"


def _document(context: Any = None) -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": 1,
        "name": "test",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 1, "y": 0}},
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


DECLARATION = [
    {"key": "caseId", "type": "string", "label": "Case id", "default": "C-0"},
    {"key": "tenant", "type": "string", "label": "Tenant", "required": True},
    {"key": "maxRefunds", "type": "number", "label": "Refund ceiling", "default": 3},
]


def _reporting_factory() -> Any:
    """Every node records what `Runtime.context` looked like when it ran.

    Through `get_runtime()` rather than a second parameter, because
    `recording_attempts` wraps a node factory's callable in `(*args, **kwargs)`
    and LangGraph's injection reads the signature it is given.
    """

    def factory(node_id: str, _node: dict, _plan: Any) -> Any:
        def run(_state: dict) -> dict:
            try:
                context = get_runtime().context
            except Exception:  # pragma: no cover - a runtime is always present here
                context = "no-runtime"
            return {"seen": {node_id: repr(context)}}

        return run

    return factory


def _what_a_node_saw(result: dict[str, Any]) -> str:
    """`seen` is a plain last-value dict, so the last node to run owns it."""
    return " ".join(result["seen"].values())


def _build(document: dict[str, Any]) -> Any:
    return WorkflowCompiler().build(document, State, _reporting_factory())


class TestADeclarationReachesTheGraph:
    def test_a_compiled_graph_carries_the_declared_shape(self) -> None:
        graph = _build(_document(DECLARATION))

        schema = graph.context_schema
        assert dataclasses.is_dataclass(schema)
        assert [f.name for f in dataclasses.fields(schema)] == [
            "caseId",
            "tenant",
            "maxRefunds",
        ]

    def test_order_is_the_documents_order_not_the_defaults_order(self) -> None:
        """The optional field is declared *first* on purpose.

        Without keyword-only fields this document does not build at all —
        `make_dataclass` raises `non-default argument follows default
        argument`, turning the author's chosen order into a build failure.
        """
        reversed_declaration = [DECLARATION[1], DECLARATION[0], DECLARATION[2]]
        graph = _build(_document(reversed_declaration))

        assert [f.name for f in dataclasses.fields(graph.context_schema)] == [
            "tenant",
            "caseId",
            "maxRefunds",
        ]

    def test_a_supplied_value_reaches_a_node_that_ran(self) -> None:
        graph = _build(_document(DECLARATION))

        result = graph.invoke({"messages": [], "decisions": {}, "seen": {}}, context={"tenant": TENANT})

        assert TENANT in _what_a_node_saw(result)

    def test_a_declared_default_is_what_an_omitting_caller_gets(self) -> None:
        graph = _build(_document(DECLARATION))

        result = graph.invoke({"messages": [], "decisions": {}, "seen": {}}, context={"tenant": TENANT})

        saw = _what_a_node_saw(result)
        assert "'C-0'" in saw
        assert "maxRefunds=3" in saw

    def test_a_required_field_with_no_default_is_refused(self) -> None:
        graph = _build(_document(DECLARATION))

        with pytest.raises(TypeError) as raised:
            graph.invoke({"messages": [], "decisions": {}, "seen": {}}, context={"caseId": "C-9"})

        assert "missing 1 required keyword-only argument: 'tenant'" in str(raised.value)

    def test_an_undeclared_key_is_refused_and_this_is_what_it_says(self) -> None:
        """Verbatim, because the *name* in it is the only part we control.

        `RunContext` is the lexicon word from the design document. It is still
        a Python `TypeError` naming an `__init__` the author never wrote, which
        is exactly why ticket 70 puts our own validator in front of it — this
        assertion is the pin that says so out loud rather than a paragraph.
        """
        graph = _build(_document(DECLARATION))

        with pytest.raises(TypeError) as raised:
            graph.invoke(
                {"messages": [], "decisions": {}, "seen": {}},
                context={"tenant": TENANT, "zzz": 1},
            )

        assert (
            str(raised.value)
            == "RunContext.__init__() got an unexpected keyword argument 'zzz'"
        )
        assert CONTEXT_SCHEMA_NAME == "RunContext"


class TestADocumentThatDeclaresNothingPaysNothing:
    def test_no_declaration_means_no_schema(self) -> None:
        assert _build(_document()).context_schema is None

    def test_an_empty_list_is_the_same_claim_as_absence(self) -> None:
        assert _build(_document([])).context_schema is None

    def test_no_declaration_passes_no_argument_at_all(self, monkeypatch) -> None:
        """`None` and *absent* are not the same thing to a library we do not own.

        A graph built from a document with no declaration must be built by the
        same call it was built by before this ticket, so what is asserted is
        the call, not its result.
        """
        from openstategraph.compile import workflow_compiler as module

        seen: list[dict[str, Any]] = []
        real = module.StateGraph

        class Recording(real):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                seen.append(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(module, "StateGraph", Recording)

        _build(_document())
        assert "context_schema" not in seen[-1]

        _build(_document(DECLARATION))
        assert "context_schema" in seen[-1]

    def test_a_malformed_declaration_mints_nothing_and_still_warns(self) -> None:
        document = _document([{"key": "threadId", "type": "string"}])

        assert _build(document).context_schema is None
        assert any("reserved run identity key" in w for w in WorkflowCompiler().plan(document).warnings)

    def test_a_key_that_cannot_be_a_field_name_is_a_warning_not_a_crash(self) -> None:
        document = _document([{"key": "case-id", "type": "string"}])

        assert _build(document).context_schema is None
        assert any("cannot be minted" in w for w in WorkflowCompiler().plan(document).warnings)


class TestTheClassIsNeverReadBack:
    def test_building_does_not_write_a_type_into_the_document(self) -> None:
        document = _document(DECLARATION)
        before = copy.deepcopy(document)

        _build(document)

        assert document == before

    def test_the_plan_holds_no_python_type(self) -> None:
        """The compile seam is one-directional: the plan is what the compiler
        hands onward, and a class in it would be a runtime object heading back
        towards the model."""
        plan = WorkflowCompiler().plan(_document(DECLARATION))

        for value in vars(plan).values():
            assert not isinstance(value, type), value

    def test_two_builds_of_one_document_mint_two_classes(self) -> None:
        """Nothing is cached, memoised or hung off the document — the class is
        discarded with the build that made it."""
        first = mint_context_schema(_document(DECLARATION))
        second = mint_context_schema(_document(DECLARATION))

        assert first is not second
