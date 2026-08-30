"""A run's own diagram, in the reader's words — `workflow-gallery` 62.

`workflow-gallery` 56 taught the *preview* route to splice a composition and
relabel it per audience. Three **run** surfaces published a diagram beside an
actual answer and did neither: `RunResponse.mermaid`, the terminal SSE `done`
frame, and MCP's `run_workflow`. All three called
`graph.get_graph().draw_mermaid()`, so a caller who had asked for the customer
channel received

    __start__(<p>__start__</p>)
    in1(in1)
    mount_mid(mount_mid)
    __default_error_handler__(<p>__default_error_handler__</p>)

— the compiler's own vocabulary, which is precisely what `api/customer_graph`
exists to remove — with three levels of `nested-mounts` flattened into one box.

**A run frame draws exactly what the preview draws, deliberately.** The two
answer different questions ("what did the compiler build" against "what just
ran"), but they answer them about the *same compiled graph*, and a reader who
opens the preview and then runs the workflow must not be shown two different
shapes for one workflow. So the assertion below is equality with the preview
route, per audience, rather than a restatement of the preview's own rules.

Driven through the endpoints and the MCP tool, never through the seam: a test
of `workflow_mermaid` stays green if a caller forgets to call it. The last
class is the guard against exactly that — a fifth surface that draws its own.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openstategraph.api.audience import Audience

BACKEND = Path(__file__).resolve().parent.parent
EXAMPLES = BACKEND / "openstategraph" / "examples"


def _document(slug: str) -> dict[str, Any]:
    return dict(json.loads((EXAMPLES / slug / "workflow.json").read_text())["document"])


@pytest.fixture(scope="module", autouse=True)
def _scripted_model() -> Any:
    """A real compiled graph, driven by a model that always answers.

    There is no provider credential in this environment and a run — unlike a
    preview — needs one. The graph, the mounts and the diagram are all real;
    only the sentences the agents produce are scripted.
    """
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from openstategraph import chat_model as chat_model_module

    original = chat_model_module.build_chat_model
    chat_model_module.build_chat_model = lambda _name: FakeListChatModel(
        responses=["A scripted sentence."] * 50
    )
    yield
    chat_model_module.build_chat_model = original


@pytest.fixture(scope="module")
def client() -> TestClient:
    """`workflows_root` as an argument, never as an environment variable —
    the variable is process-wide and a module-scoped fixture that sets it
    turned 37 unrelated tests red once (gallery 56's instrument note)."""
    from openstategraph.api.main import create_app

    return TestClient(create_app(workflows_root=EXAMPLES))


def _run_mermaid(client: TestClient, slug: str, audience: str) -> str:
    response = client.post(
        "/api/runs",
        json={
            "workflow": _document(slug),
            "workflow_slug": slug,
            "question": "hi",
            "audience": audience,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["mermaid"])


def _stream_mermaid(client: TestClient, slug: str, audience: str) -> str:
    response = client.post(
        "/api/runs/stream",
        json={
            "workflow": _document(slug),
            "workflow_slug": slug,
            "question": "hi",
            "audience": audience,
        },
    )
    assert response.status_code == 200, response.text
    for line in response.text.splitlines():
        if line.startswith("data:") and '"mermaid"' in line:
            return str(json.loads(line[5:])["mermaid"])
    raise AssertionError("no terminal frame carried a diagram")


def _preview_mermaid(client: TestClient, slug: str, audience: str) -> str:
    response = client.get(
        f"/api/workflows/{slug}/graph", params={"audience": audience}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["mermaid"])


class TestTheCustomerChannelStopsSpeakingCompiler:
    @pytest.fixture(scope="class")
    def diagram(self, client: TestClient) -> str:
        return _run_mermaid(client, "nested-mounts", "customer")

    def test_the_composition_is_open(self, diagram: str) -> None:
        assert "subgraph mount_mid" in diagram
        assert "subgraph mount_mid_mount_inner" in diagram

    def test_every_node_carries_its_own_authors_title(self, diagram: str) -> None:
        assert "(Summarise)" in diagram
        assert "(Cut to one sentence)" in diagram
        assert "Nested Mounts (middle)" in diagram

    def test_no_compiler_vocabulary_survives(self, diagram: str) -> None:
        assert "__start__" not in diagram
        assert "__end__" not in diagram
        assert "(in1)" not in diagram
        assert "(out1)" not in diagram

    def test_no_error_handler_leaks_from_any_depth(self, diagram: str) -> None:
        """Each spliced child brings its own, and `draw_mermaid` escapes the
        `:` in a prefixed id as `\\3a` — gallery 56's root cause."""
        assert "__default_error_handler__" not in diagram

    def test_the_terminal_frame_says_the_same_thing(self, client: TestClient) -> None:
        assert _stream_mermaid(client, "nested-mounts", "customer") == _run_mermaid(
            client, "nested-mounts", "customer"
        )


class TestTwoMountsSideBySideAreNotConfused:
    """A block stack that never pops draws `nested-mounts` perfectly and
    mislabels the first document with two siblings in it."""

    @pytest.fixture(scope="class")
    def diagram(self, client: TestClient) -> str:
        return _run_mermaid(client, "same-package-twice", "customer")

    def test_each_instance_keeps_the_title_its_author_gave_it(
        self, diagram: str
    ) -> None:
        assert "Instance A — terse" in diagram
        assert "Instance B — analogy" in diagram

    def test_both_children_are_drawn(self, diagram: str) -> None:
        assert diagram.count("(Summarise)") == 2


class TestBothDoorsDrawOneWorkflow:
    @pytest.mark.parametrize("audience", ["developer", "customer"])
    @pytest.mark.parametrize("slug", ["nested-mounts", "same-package-twice", "sql-qa"])
    def test_a_run_draws_what_the_preview_draws(
        self, client: TestClient, slug: str, audience: str
    ) -> None:
        assert _run_mermaid(client, slug, audience) == _preview_mermaid(
            client, slug, audience
        )

    @pytest.mark.parametrize("audience", ["developer", "customer"])
    def test_so_does_the_terminal_frame(self, client: TestClient, audience: str) -> None:
        assert _stream_mermaid(client, "nested-mounts", audience) == _preview_mermaid(
            client, "nested-mounts", audience
        )


class TestTheDeveloperLosesNothing:
    @pytest.fixture(scope="class")
    def diagram(self, client: TestClient) -> str:
        return _run_mermaid(client, "nested-mounts", "developer")

    def test_the_compilers_own_names_are_kept(self, diagram: str) -> None:
        """A mount bug is reported under the name the compiler used."""
        assert "__start__" in diagram
        assert "in1(in1)" in diagram

    def test_and_the_composition_is_open_here_too(self, diagram: str) -> None:
        assert "subgraph mount_mid" in diagram
        assert r"mount_mid\3amount_mid_mount_inner\3asummarise1" in diagram


class TestAMountlessWorkflowIsUnchanged:
    def test_the_developer_diagram_is_what_langgraph_drew(
        self, client: TestClient
    ) -> None:
        """The inverse, and it is load-bearing: for a document that mounts
        nothing the splice must be invisible, byte for byte."""
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = _document("sql-qa")
        runtime = NodeRuntime(model=None)
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        assert _run_mermaid(client, "sql-qa", "developer") == graph.get_graph(
            xray=True
        ).draw_mermaid()

    def test_the_customer_diagram_still_drops_the_machinery(
        self, client: TestClient
    ) -> None:
        diagram = _run_mermaid(client, "sql-qa", "customer")
        assert "__start__" not in diagram
        assert "(Analyst)" in diagram


class TestTheMcpRunToolDrawsTheCompositionToo:
    def test_run_workflow_opens_its_mounts(self, tmp_path: Any) -> None:
        """MCP's *stateless* `compile_workflow` is flat for a recorded reason
        — it holds no library, so a mount resolves to nothing. `run_workflow`
        is the other case: it ran the child, so it can draw it."""
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowRuns

        services = WorkflowServices(EXAMPLES)
        try:
            result = WorkflowRuns(services).run(
                slug="nested-mounts", question="hi", audience=Audience.CUSTOMER
            )
        finally:
            services.close()

        assert result.get("error") is None, result
        assert "subgraph mount_mid" in str(result["mermaid"])


class TestNoSurfaceDrawsItsOwn:
    """The seam, guarded. Four call sites that must each remember two calls is
    how this ticket happened; one seam plus this test is the replacement."""

    def test_every_api_diagram_goes_through_the_seam(self) -> None:
        offenders = []
        for path in sorted((BACKEND / "openstategraph").rglob("*.py")):
            relative = path.relative_to(BACKEND / "openstategraph").as_posix()
            if relative in {"api/diagram.py", "loader.py"}:
                # `api/diagram.py` IS the seam. `loader.py` is the SDK's own
                # `CompiledWorkflow.mermaid`, which does its own expansion,
                # takes an `xray` toggle and has no audience to relabel for.
                continue
            # Parsed, not grepped: half this repository's prose says
            # `draw_mermaid()` while explaining why never to call it bare.
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "draw_mermaid"
                ):
                    offenders.append(relative)
                    break
        assert not offenders, (
            "these draw a diagram without the audience and the mounts: "
            f"{offenders} — call api.diagram.workflow_mermaid"
        )
