"""Run context reaches a prompt as a generated section — `organisms-first-class/72`.

Step 6 of the seven in `docs/decisions/runtime-context.md`. 71 gave the three
*text* families `{{key}}` rendering and deliberately withheld it from the
prompted ones, because their context arrives here — as the **Context** section
of a system prompt, generated, locked, above the developer's rules, with the
output contract still last.

**The opt-in is the substance, not a nicety.** A run-context field is exactly
where an API handle, a tenant id or a caller's address ends up, and a tool has
to be able to read one without a model ever seeing it. So a field is rendered
only when the document says `"prompt": true`, and the default is **off**:
shipping this default-on would publish every declared value into a context
window the first time somebody used the feature, and a value sent to a provider
cannot be un-sent.

**What would still be green if the wrong thing were built?** A test of
`run_context_prompt_section()` in isolation, or of a composer's return value —
both pass against a section no node ever sends. So every claim below is made
against **the system message a real compiled graph's model actually received**,
recorded by `RespondingModel.calls`. The leak inverse is asserted on the whole
message rather than on the section, because a value that escaped into any other
part of the prompt has still escaped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.run_context import (
    ContextField,
    context_declaration_problems,
    prompt_context_fields,
    run_context_prompt_section,
)
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from test_orchestrator_graph import RespondingModel, edge, node

#: Obvious placeholders, never a plausible handle. This ticket is about the
#: channel a real credential would travel down, and a fixture that reads like
#: one is a fixture somebody eventually pastes somewhere.
TENANT = "tenant-placeholder"
HANDLE = "SECRET-HANDLE-PLACEHOLDER-ZZZ"

SHOWN = {
    "key": "tenant",
    "type": "string",
    "label": "Tenant",
    "description": "Which customer this run is for.",
    "prompt": True,
}
#: Declared, supplied, and **not** opted in — the whole point of the ticket.
WITHHELD = {"key": "apiHandle", "type": "string", "label": "API handle"}


def _declaration(*fields: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(f) for f in fields]


def _document(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
              context: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": 1,
        "name": "context-reaches-a-prompt",
        "nodes": nodes,
        "edges": edges,
    }
    if context is not None:
        document["settings"] = {"context": context}
    return document


def _run(document: dict[str, Any], model: Any, question: str = "a question",
         **invoke: Any) -> dict[str, Any]:
    runtime = NodeRuntime(model=model)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke({"messages": [], "question": question}, **invoke)


# --------------------------------------------------------------------------- #
# The four prompted families, each driven as a real compiled graph.
# --------------------------------------------------------------------------- #


def _router_document(context: list[dict[str, Any]] | None) -> dict[str, Any]:
    return _document(
        [
            node("in1", "input.text", prompt=""),
            node("r1", "route.classifier", branches=[{"id": "b1", "name": "only"}],
                 rules="- Always answer `only`."),
            node("out1", "output.formatted"),
        ],
        [
            edge("in1", "text", "r1", "text"),
            edge("r1", "branch:b1", "out1", "result"),
        ],
        context,
    )


def _grader_document(context: list[dict[str, Any]] | None) -> dict[str, Any]:
    return _document(
        [
            node("in1", "input.text", prompt="a candidate answer long enough to grade"),
            node("g1", "route.grader", criteria="- Be strict."),
            node("out1", "output.formatted"),
        ],
        [
            edge("in1", "text", "g1", "candidate"),
            edge("g1", "pass", "out1", "result"),
        ],
        context,
    )


def _agent_document(context: list[dict[str, Any]] | None) -> dict[str, Any]:
    return _document(
        [
            node("in1", "input.text", prompt="hello"),
            node("a1", "agent.llm", systemPrompt="- Be brief."),
            node("out1", "output.formatted"),
        ],
        [
            edge("in1", "text", "a1", "prompt"),
            edge("a1", "result", "out1", "result"),
        ],
        context,
    )


def _supervisor_document(context: list[dict[str, Any]] | None) -> dict[str, Any]:
    worker = node("w1", "orchestrate.worker")
    worker["title"] = "Only Worker"
    return _document(
        [
            node("in1", "input.text", prompt="first thing; second thing"),
            node("s1", "orchestrate.supervisor", maxSubtasks=2,
                 rules="- Split into independent subtasks."),
            worker,
            node("rep1", "function.format_report", reportTitle="Report"),
            node("out1", "output.formatted"),
        ],
        [
            edge("in1", "text", "s1", "instruction"),
            edge("s1", "workers", "w1", "dispatch"),
            edge("w1", "result", "rep1", "candidate"),
            edge("rep1", "report", "out1", "result"),
        ],
        context,
    )


FAMILIES = {
    "route.classifier": (_router_document, "only"),
    "route.grader": (_grader_document, "PASS"),
    "agent.llm": (_agent_document, "an answer"),
    "orchestrate.supervisor": (_supervisor_document, "a subtask"),
}


def _sent(builder: Any, reply: str, declaration: list[dict[str, Any]] | None,
          **invoke: Any) -> str:
    """Every system message this family's model actually received, joined."""
    model = RespondingModel([], default=reply)
    _run(builder(declaration), model, **invoke)
    assert model.calls, "the model was never called — the test proves nothing"
    return "\n".join(model.calls)


class TestAnOptedInFieldReachesTheModel:
    """The demonstration, once per prompted family."""

    def test_every_prompted_family_is_told_the_value(self) -> None:
        for name, (builder, reply) in FAMILIES.items():
            sent = _sent(
                builder, reply, _declaration(SHOWN, WITHHELD),
                context={"tenant": TENANT, "apiHandle": HANDLE},
            )
            assert TENANT in sent, name

    def test_the_section_names_the_field_and_declares_itself_authoritative(self) -> None:
        sent = _sent(
            _router_document, "only", _declaration(SHOWN),
            context={"tenant": TENANT},
        )
        assert f"- Tenant (`tenant`): {TENANT} — Which customer this run is for." in sent
        assert "This block is generated from what the caller actually supplied" in sent

    def test_it_rides_in_the_locked_context_section_and_not_in_the_rules(self) -> None:
        """Where it sits is the ticket, so it is asserted structurally too."""
        sent = _sent(
            _router_document, "only", _declaration(SHOWN),
            context={"tenant": TENANT},
        )
        before, _, after = sent.partition("</context>")
        assert TENANT in before
        assert TENANT not in after

    def test_the_output_contract_still_renders_last(self) -> None:
        sent = _sent(
            _router_document, "only", _declaration(SHOWN),
            context={"tenant": TENANT},
        )
        assert sent.rindex("<output_format>") > sent.rindex("<context>")
        assert sent.rindex("<output_format>") > sent.rindex("<rules>")

    def test_a_worker_gets_it_too(self) -> None:
        """`_worker` is a second factory, and a sentence composed into one and
        not the other is the defect `advisor_context` already cost this
        repository once. A supervisor run reaches the model more than once —
        the plan, then each dispatched worker — so this asserts on *every*
        call rather than on the first."""
        model = RespondingModel([], default="a subtask")
        _run(
            _supervisor_document(_declaration(SHOWN)),
            model,
            context={"tenant": TENANT},
        )
        assert len(model.calls) > 1, "the worker never reached the model"
        assert all(TENANT in call for call in model.calls)


class TestAWithheldFieldReachesNoModelAtAll:
    """The inverse this ticket exists for, asserted on the whole message."""

    def test_no_prompted_family_is_ever_shown_it(self) -> None:
        for name, (builder, reply) in FAMILIES.items():
            sent = _sent(
                builder, reply, _declaration(SHOWN, WITHHELD),
                context={"tenant": TENANT, "apiHandle": HANDLE},
            )
            assert HANDLE not in sent, name
            assert "apiHandle" not in sent, name
            assert "API handle" not in sent, name

    def test_a_declaration_where_nothing_opted_in_sends_nothing(self) -> None:
        sent = _sent(
            _router_document, "only", _declaration(dict(WITHHELD)),
            context={"apiHandle": HANDLE},
        )
        assert HANDLE not in sent
        assert "Run context" not in sent

    def test_opt_in_is_off_by_default_in_the_descriptor_itself(self) -> None:
        assert ContextField(key="k", type="string").prompt is False

    def test_the_section_never_names_a_field_it_withheld(self) -> None:
        """Naming a withheld key would tell a model there is something it has
        not been given, and invite it to ask for what nothing can supply."""
        section = run_context_prompt_section(
            prompt_context_fields(
                {"settings": {"context": _declaration(SHOWN, WITHHELD)}}
            ),
            {"tenant": TENANT, "apiHandle": HANDLE},
        )
        assert "apiHandle" not in section
        assert HANDLE not in section


class TestOneCompiledGraphDoesNotLeakBetweenRuns:
    """The agent factory caches per skill, and that cache outlives a run."""

    def test_a_second_caller_never_sees_the_first_callers_value(self) -> None:
        document = _agent_document(_declaration(SHOWN))
        model = RespondingModel([], default="an answer")
        runtime = NodeRuntime(model=model)
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        graph.invoke({"messages": [], "question": "q"}, context={"tenant": "first-placeholder"})
        first_calls = len(model.calls)
        graph.invoke({"messages": [], "question": "q"}, context={"tenant": "second-placeholder"})
        second = "\n".join(model.calls[first_calls:])
        assert "second-placeholder" in second
        assert "first-placeholder" not in second


class TestADocumentThatDeclaresNothingComposesExactlyWhatItAlwaysDid:
    """Byte-identical, and asserted as such rather than described."""

    def test_no_declaration_and_a_declaration_nobody_opted_into_agree(self) -> None:
        for name, (builder, reply) in FAMILIES.items():
            bare = _sent(builder, reply, None)
            declared = _sent(
                builder, reply, _declaration(WITHHELD), context={"apiHandle": HANDLE}
            )
            assert bare == declared, name

    def test_no_declaration_carries_no_context_section_of_ours(self) -> None:
        assert "Run context —" not in _sent(_router_document, "only", None)

    def test_an_opted_in_field_with_no_value_this_run_writes_nothing(self) -> None:
        """Declared, opted in, no default, nothing supplied: not rendered empty."""
        optional = {**SHOWN, "required": False}
        bare = _sent(_router_document, "only", None)
        assert _sent(_router_document, "only", _declaration(optional)) == bare


class TestTheDeclarationValidatesTheNewProperty:
    def test_a_non_boolean_prompt_is_refused_by_name(self) -> None:
        problems = context_declaration_problems(
            {"settings": {"context": [{"key": "tenant", "type": "string", "prompt": "yes"}]}}
        )
        assert any("non-boolean 'prompt'" in p for p in problems)

    def test_prompt_is_a_known_property_and_not_an_unknown_one(self) -> None:
        assert context_declaration_problems(
            {"settings": {"context": [dict(SHOWN)]}}
        ) == []

    def test_a_malformed_declaration_renders_nothing_rather_than_raising(self) -> None:
        assert prompt_context_fields({"settings": {"context": "not a list"}}) == ()


class TestTheTypeScriptMirrorCarriesTheOptIn:
    """`core/` cannot import Python, so the descriptor exists twice."""

    def test_the_interface_declares_prompt_as_an_optional_boolean(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "src" / "core" / "model" / "contracts" / "workflow.ts"
        ).read_text(encoding="utf-8")
        assert "readonly prompt?: boolean;" in source
