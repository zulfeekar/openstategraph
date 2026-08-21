"""The saved step budget is the budget the graph is invoked with.

`workflow-gallery` 26. `settings.recursionLimit` existed at four layers —
the editor's model held it, `RuntimeClient` serialised it, `RunRequest`
accepted it (`ge=10, le=1000`), and the graph config consumed it — and at
the fifth, the one that reads it out of a saved document, there was
nothing. Every run in the editor, on `/chat` and from the CLI took 50.

The tests below are deliberately **not** "does `RunRequest` accept the
field". That was already green while the defect was live. Each one asks
what config a graph was actually invoked with.

`recursion_limit` counts **supersteps, not iterations** (CLAUDE.md), which
is why the user-facing word for it is *step budget* and why nothing here
calls it an iteration count.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.step_budget import DEFAULT_STEP_BUDGET, resolve_step_budget

REPO = Path(__file__).resolve().parent.parent.parent

MINIMAL_DOCUMENT: dict[str, Any] = {
    "version": 2,
    "name": "budget-test",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}


def _with_budget(value: Any) -> dict[str, Any]:
    return {**MINIMAL_DOCUMENT, "settings": {"recursionLimit": value}}


class TestResolution:
    """The one function that decides, so there is one thing to get right."""

    def test_absence_still_yields_the_default(self) -> None:
        assert resolve_step_budget(None, MINIMAL_DOCUMENT) == DEFAULT_STEP_BUDGET
        assert DEFAULT_STEP_BUDGET == 50

    def test_a_saved_setting_is_read(self) -> None:
        assert resolve_step_budget(None, _with_budget(200)) == 200

    def test_an_explicit_request_value_wins_over_the_document(self) -> None:
        assert resolve_step_budget(120, _with_budget(200)) == 120

    def test_the_snake_case_spelling_is_read_too(self) -> None:
        """Tolerant in reading: a hand-written document is not the editor."""
        settings = {"recursion_limit": 300}
        assert resolve_step_budget(None, {**MINIMAL_DOCUMENT, "settings": settings}) == 300

    def test_a_value_outside_the_accepted_range_is_clamped_not_obeyed(self) -> None:
        """A document is not validated by Pydantic, and a run that dies at
        validation because of a saved number is worse than one that runs."""
        assert resolve_step_budget(None, _with_budget(5)) == 10
        assert resolve_step_budget(None, _with_budget(100_000)) == 1000

    def test_nonsense_falls_back_rather_than_raising(self) -> None:
        for junk in ("many", None, True, [], {"a": 1}, 3.5):
            assert resolve_step_budget(None, _with_budget(junk)) == DEFAULT_STEP_BUDGET
        assert resolve_step_budget(None, {"settings": "nope"}) == DEFAULT_STEP_BUDGET
        assert resolve_step_budget(None, {}) == DEFAULT_STEP_BUDGET


class _Recorder:
    """Captures the config every invoke/stream is given."""

    def __init__(self) -> None:
        self.configs: list[dict[str, Any]] = []

    def install(self, monkeypatch: Any) -> None:
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        real_build = WorkflowCompiler.build
        recorder = self

        def build(self_: Any, *args: Any, **kwargs: Any) -> Any:
            graph = real_build(self_, *args, **kwargs)
            real_invoke = graph.invoke
            real_stream = graph.stream

            def invoke(state: Any, config: Any = None, **kw: Any) -> Any:
                recorder.configs.append(dict(config or {}))
                return real_invoke(state, config, **kw)

            def stream(state: Any, config: Any = None, **kw: Any) -> Any:
                recorder.configs.append(dict(config or {}))
                return real_stream(state, config, **kw)

            graph.invoke = invoke  # type: ignore[method-assign]
            graph.stream = stream  # type: ignore[method-assign]
            return graph

        monkeypatch.setattr(WorkflowCompiler, "build", build)

    @property
    def budget(self) -> int:
        assert self.configs, "nothing was invoked"
        return int(self.configs[-1]["recursion_limit"])


class TestTheHttpDoor:
    """`/api/runs` and `/api/runs/stream` — the editor's door and `/chat`'s.

    Both post the whole document and neither sends `recursion_limit`, which
    is precisely why reading it here fixes both surfaces at once.
    """

    def _client(self) -> TestClient:
        return TestClient(create_app(workflows_root=REPO / "workflows"))

    def test_a_saved_budget_reaches_the_invoke(self, monkeypatch: Any) -> None:
        rec = _Recorder()
        rec.install(monkeypatch)
        response = self._client().post(
            "/api/runs",
            json={"workflow": _with_budget(123), "question": "hello", "model": "ollama:unused"},
        )
        assert response.status_code == 200, response.text
        assert rec.budget == 123

    def test_an_enveloped_document_is_read_through_its_envelope(
        self, monkeypatch: Any
    ) -> None:
        rec = _Recorder()
        rec.install(monkeypatch)
        response = self._client().post(
            "/api/runs",
            json={
                "workflow": {"version": 1, "name": "b", "document": _with_budget(321)},
                "question": "hello",
                "model": "ollama:unused",
            },
        )
        assert response.status_code == 200, response.text
        assert rec.budget == 321

    def test_no_setting_still_means_fifty(self, monkeypatch: Any) -> None:
        rec = _Recorder()
        rec.install(monkeypatch)
        response = self._client().post(
            "/api/runs",
            json={"workflow": MINIMAL_DOCUMENT, "question": "hello", "model": "ollama:unused"},
        )
        assert response.status_code == 200, response.text
        assert rec.budget == DEFAULT_STEP_BUDGET

    def test_an_explicit_request_value_still_wins(self, monkeypatch: Any) -> None:
        rec = _Recorder()
        rec.install(monkeypatch)
        response = self._client().post(
            "/api/runs",
            json={
                "workflow": _with_budget(123),
                "question": "hello",
                "model": "ollama:unused",
                "recursion_limit": 456,
            },
        )
        assert response.status_code == 200, response.text
        assert rec.budget == 456

    def test_the_stream_door_reads_it_too(self, monkeypatch: Any) -> None:
        rec = _Recorder()
        rec.install(monkeypatch)
        with self._client().stream(
            "POST",
            "/api/runs/stream",
            json={"workflow": _with_budget(234), "question": "hello", "model": "ollama:unused"},
        ) as response:
            assert response.status_code == 200, response.text
            for _ in response.iter_lines():
                pass
        assert rec.budget == 234


class TestTheCli:
    """`openstategraph run` goes through `CompiledWorkflow.ask`."""

    def test_ask_honours_the_documents_saved_budget(self, tmp_path: Path) -> None:
        import json

        from openstategraph.loader import load_workflow

        package = tmp_path / "budgeted"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(_with_budget(150)))

        seen: list[Any] = []
        compiled = load_workflow(package)
        real_invoke = compiled.graph.invoke
        compiled.graph.invoke = lambda state, config=None, **kw: (  # type: ignore[method-assign]
            seen.append(config),
            real_invoke(state, config, **kw),
        )[1]
        compiled.ask("hello")
        assert seen[-1]["recursion_limit"] == 150

    def test_an_explicit_argument_still_wins(self, tmp_path: Path) -> None:
        import json

        from openstategraph.loader import load_workflow

        package = tmp_path / "budgeted2"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(_with_budget(150)))

        seen: list[Any] = []
        compiled = load_workflow(package)
        real_invoke = compiled.graph.invoke
        compiled.graph.invoke = lambda state, config=None, **kw: (  # type: ignore[method-assign]
            seen.append(config),
            real_invoke(state, config, **kw),
        )[1]
        compiled.ask("hello", recursion_limit=99)
        assert seen[-1]["recursion_limit"] == 99
