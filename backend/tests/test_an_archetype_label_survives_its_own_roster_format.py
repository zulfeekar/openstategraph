"""Every subtask went to the default worker, and the other worker never ran.

`every-workflow-green` 17. `archetype-orchestrator-report` wires a Researcher
and a Writer. Asked to plan an onboarding session it produced three subtasks,
two of them plainly writing work — and the trace showed three `worker-research`
rows and no `worker-write` row at all.

The labelling call returned:

    researcher: compile_best_practices
    writer: draft_onboarding_agenda

`archetype_slug` was applied to the whole line, matched nothing, and each
subtask collapsed to the default. The roster the prompt shows is formatted
`- {key}: {name} — {description}`, so the model answered in the shape it was
taught. The parse required a bare key.

Two failures: the fan-out silently degraded to one archetype, and the warning
that says so went to a logger instead of to the developer channel — the run
reported none.
"""

from __future__ import annotations

from openstategraph.abc.orchestrator import Archetype, Subtask


class _Reply:
    def __init__(self, text: str) -> None:
        self.content = text


class _Model:
    def __init__(self, text: str) -> None:
        self.text = text

    def invoke(self, _messages: object) -> _Reply:
        return _Reply(self.text)


def _orchestrator(reply: str):
    from openstategraph.abc.orchestrator import BaseOrchestrator

    class _O(BaseOrchestrator):
        def split(self, instruction: str, feedback: str = "") -> list[str]:
            return [instruction]

    return _O(model=_Model(reply))


ARCHETYPES = [
    Archetype(key="researcher", name="Researcher", description="Gathers facts"),
    Archetype(key="writer", name="Writer", description="Writes prose"),
]
TASKS = [
    Subtask(id="task-1", instruction="Find best practices"),
    Subtask(id="task-2", instruction="Draft the agenda"),
]


class TestTheLabelIsReadOutOfWhatTheModelSaid:
    def test_a_bare_key_still_works(self) -> None:
        assert _orchestrator("researcher\nwriter").label(TASKS, ARCHETYPES) == [
            "researcher",
            "writer",
        ]

    def test_the_roster_shape_is_understood(self) -> None:
        """`key: name` — exactly what the roster in the prompt looks like."""
        reply = "researcher: compile_best_practices\nwriter: draft_onboarding_agenda"
        assert _orchestrator(reply).label(TASKS, ARCHETYPES) == ["researcher", "writer"]

    def test_a_numbered_reply_is_understood(self) -> None:
        assert _orchestrator("1. researcher\n2. writer").label(TASKS, ARCHETYPES) == [
            "researcher",
            "writer",
        ]

    def test_a_display_name_still_resolves(self) -> None:
        assert _orchestrator("Researcher\nWriter").label(TASKS, ARCHETYPES) == [
            "researcher",
            "writer",
        ]

    def test_an_invented_label_still_falls_to_the_default(self) -> None:
        """Tolerance must not become trust — ticket 37's rule stands."""
        assert _orchestrator("astronaut\nwriter").label(TASKS, ARCHETYPES) == ["", "writer"]


class TestTheCollapseIsReported:
    def test_a_mismatch_is_written_to_notes(self) -> None:
        notes: list[str] = []
        _orchestrator("astronaut\nastronaut").label(TASKS, ARCHETYPES, notes=notes)
        assert notes
        assert any("astronaut" in note for note in notes)

    def test_a_clean_labelling_says_nothing(self) -> None:
        notes: list[str] = []
        _orchestrator("researcher\nwriter").label(TASKS, ARCHETYPES, notes=notes)
        assert notes == []
