"""A dead run showed a provider string and nothing else.

`every-workflow-green` 14. Reproduced in twenty lines with no model, no
compiler and no workflow — one `StateGraph`, one node that raises, one
`error_handler`:

    invoke                            -> handled
    stream updates  subgraphs=False   -> handled
    stream updates  subgraphs=True    -> RAISED
    stream messages subgraphs=False   -> RAISED
    stream messages subgraphs=True    -> RAISED

So a node `error_handler` is bypassed whenever the caller asks for token
streaming or subgraph frames — which is exactly what the editor asks for. That
is LangGraph's behaviour, not this compiler's, and it cannot be fixed here.

What *can* be fixed here is the report. The exception carries the failing task
in `__notes__` — LangGraph appends `During task with name 'n1' and id '…'` —
so the streaming door can name the node the way `/api/runs` already does,
instead of handing a reader a provider string and a reference id.
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import failing_task_name


def _with_notes(*notes: str) -> Exception:
    exc = RuntimeError("provider said no")
    for note in notes:
        exc.add_note(note)
    return exc


class TestTheFailingNodeIsRecoverable:
    def test_it_reads_the_task_name_langgraph_appends(self) -> None:
        exc = _with_notes("During task with name 'router1' and id 'abc-123'")
        assert failing_task_name(exc) == "router1"

    def test_the_outermost_task_wins(self) -> None:
        """LangGraph appends inner first, outer last — the canvas node is the
        outer one, and it is the only name a reader can act on."""
        exc = _with_notes(
            "During task with name 'model' and id 'x'",
            "During task with name 'agent-sql' and id 'y'",
        )
        assert failing_task_name(exc) == "agent-sql"

    def test_an_exception_with_no_notes_yields_nothing(self) -> None:
        assert failing_task_name(RuntimeError("boom")) is None

    def test_an_unrelated_note_is_ignored(self) -> None:
        assert failing_task_name(_with_notes("some other annotation")) is None

    def test_it_does_not_raise_on_anything_odd(self) -> None:
        assert failing_task_name(None) is None
        assert failing_task_name("not an exception") is None
