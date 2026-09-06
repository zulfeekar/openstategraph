"""Who learns that a guardrail acted, and what they are told.

Guardrails tickets 02 and 03, which are one question asked from two ends.

**03 — a redaction that happens silently is its own defect.** A developer
debugging *"why did the agent answer that?"* is reading text the machinery
quietly rewrote. But the obvious fix — showing what was redacted — recreates
the leak in the surface people read most often. The shape of the answer was
already in this codebase: the **audience boundary**. The developer channel
carries counts and entity types; the customer sees clean text and nothing
else. That is a field named in `api/audience.py`, not a fourth convention.

**02 — a node you can forget to add is a leak you can forget to prevent.**
Settled as *a node, with its absence made loud* — but only the absence that
is evidence of a mistake. A document with no guardrail at all is warned about
by nothing here, deliberately: most workflows handle no personal data, and a
warning on every document is one nobody reads (`compile/diagnostics.py` says
so in as many words). What is reported is the **inconsistent** case — a
document that has a policy and a path to the user that skips it.
"""

from __future__ import annotations

import json
from typing import Any

from openstategraph.api.audience import Audience, DeveloperChannel
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from test_guardrail_node import EMAIL, guarded_document, node, edge  # noqa: F401


class TestTheDeveloperChannelCarriesCountsNotValues:
    def test_a_customer_frame_has_no_redaction_report_at_all(self) -> None:
        channel = DeveloperChannel(
            redactions=[{"node": "guard-out", "entity": "email", "strategy": "redact", "count": 3}]
        )
        assert channel.payload(Audience.CUSTOMER) == {}

    def test_a_developer_frame_always_carries_the_field(self) -> None:
        # Present even when empty, so a developer client never has to tell
        # "nothing was redacted" apart from "an older backend" — the same
        # argument `warnings` and `suggestion` already carry.
        payload = DeveloperChannel().payload(Audience.DEVELOPER)
        assert payload["developer"]["redactions"] == []

    def test_it_reports_what_happened_and_where(self) -> None:
        channel = DeveloperChannel(
            redactions=[{"node": "guard-out", "entity": "email", "strategy": "redact", "count": 3}]
        )
        report = channel.payload(Audience.DEVELOPER)["developer"]["redactions"]
        assert report == [
            {"node": "guard-out", "entity": "email", "strategy": "redact", "count": 3}
        ]

    def test_a_redaction_report_is_not_a_warning(self) -> None:
        # Folding this into `warnings` was the cheaper option and the wrong
        # one: every guarded run would then report warnings, the editor
        # renders warnings as problems, and a channel that cries wolf on the
        # happy path is a channel people learn to skip.
        channel = DeveloperChannel(
            redactions=[{"node": "g", "entity": "email", "strategy": "redact", "count": 1}]
        )
        assert channel.payload(Audience.DEVELOPER)["developer"]["warnings"] == []


class TestTheStoredTraceIsRedactedToo:
    """Settled, with the cost written down.

    The trade is real: a redacted trace is a worse debugging tool. It is
    still the right answer, because the alternative is not "a better trace" —
    it is a *clean answer beside a payload carrying the same 59 addresses*,
    sent to the same recipient on the same frame. A redaction that covers
    only the prose is not a redaction. What the developer loses is replaced
    by something they did not have before: `redactions` says three emails
    were removed from this node's output, which is the fact they were
    actually looking for.
    """

    def test_the_transcript_the_next_turn_reads_carries_the_redacted_form(self) -> None:
        runtime = NodeRuntime(model=_fake(f"Her address is {EMAIL}."))
        document = guarded_document()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "who is she"})

        transcript = " ".join(str(getattr(m, "content", "")) for m in final.get("messages", []))
        assert EMAIL not in transcript

    def test_no_settled_surface_of_the_run_still_holds_it(self) -> None:
        runtime = NodeRuntime(model=_fake(f"Her address is {EMAIL}."))
        document = guarded_document()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "who is she"})

        # `answer`, `outputs` and `messages` are the three things a `done`
        # frame is built from. All three, or none of them.
        for key in ("answer", "outputs", "messages"):
            assert EMAIL not in json.dumps(final.get(key), default=str), key


class TestAPolicyWithAHoleInItIsReported:
    def test_a_document_with_no_guardrail_is_warned_about_by_nothing(self) -> None:
        document = _unguarded_document()
        runtime = NodeRuntime(model=_fake("ok"))
        WorkflowCompiler().build(document, RunState, runtime.factory(document))

        assert runtime.diagnostics.warnings() == []

    def test_a_guarded_document_with_a_guarded_exit_is_quiet(self) -> None:
        document = guarded_document()
        runtime = NodeRuntime(model=_fake("ok"))
        WorkflowCompiler().build(document, RunState, runtime.factory(document))

        assert not runtime.diagnostics.any(Finding.UNGUARDED_EXIT)

    def test_an_exit_that_skips_the_policy_is_named(self) -> None:
        # The realistic mistake: a second Output added later, wired straight
        # off the agent, so the answer that reaches the user on *that* path
        # never meets the guard on the other one.
        document = guarded_document()
        document["nodes"].append(node("out2", "output.formatted"))
        document["edges"].append(edge("agent1", "result", "out2", "result"))

        runtime = NodeRuntime(model=_fake("ok"))
        WorkflowCompiler().build(document, RunState, runtime.factory(document))

        assert runtime.diagnostics.subjects(Finding.UNGUARDED_EXIT) == [("out2",)]

    def test_the_sentence_names_the_consequence_and_the_fix(self) -> None:
        sentence = Finding.UNGUARDED_EXIT and __import__(
            "openstategraph.compile.diagnostics", fromlist=["CompileDiagnostics"]
        ).CompileDiagnostics.sentence_for(Finding.UNGUARDED_EXIT)
        assert "guardrail" in sentence.lower()
        assert "{0}" in sentence


def _unguarded_document() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "plain",
        "nodes": [
            node("in1", "input.text"),
            node("agent1", "agent.llm"),
            node("out1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "agent1", "prompt"),
            edge("agent1", "result", "out1", "result"),
        ],
    }


def _fake(answer: str) -> Any:
    from itertools import repeat

    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    return GenericFakeChatModel(messages=repeat(answer))
