"""**View compiled graph** shows the composition, not one box — `workflow-gallery` 56.

`CompiledWorkflow.mermaid(xray=True)` learned to open a mount to any depth in
gallery 28. The HTTP route the editor's top bar calls did not: it built its own
graph and called `get_graph(xray=True).draw_mermaid()`, and LangGraph cannot
see through the closure a mount compiles to. So `nested-mounts` — three
documents, three levels, six nodes below the top — arrived at the editor as
`in1 --> mount_mid --> out1`.

Driven through the route rather than through `expand_mounts` or
`customer_mermaid`, because a test of either helper stays green if the route
never calls it. That is the exact shape of failure this repository has paid for
twice.

The customer half is the part that needed a decision, and it is here as
assertions: a customer is shown the composition with **every** node carrying
the title its own author gave it, resolved from the child's own document, and
the compiler's vocabulary — prefixed ids, `__default_error_handler__` at any
depth, the mount's graph name on the block — removed at every level, not only
at the top.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"


@pytest.fixture(scope="module")
def gallery_client() -> TestClient:
    """A server whose library is the shipped examples.

    `workflows_root` as an argument and never as an environment variable: the
    variable is process-wide, so a module-scoped fixture that sets it points
    every *other* test file's workflow lookups at `examples/` too. That is not
    hypothetical — it turned 37 unrelated tests red once here.
    """
    from openstategraph.api.main import create_app

    return TestClient(create_app(workflows_root=EXAMPLES))


def _diagram(client: TestClient, slug: str, audience: str) -> str:
    response = client.get(f"/api/workflows/{slug}/graph", params={"audience": audience})
    assert response.status_code == 200, response.text
    return str(response.json()["mermaid"])


@pytest.fixture(scope="module")
def developer_diagram(gallery_client: TestClient) -> str:
    return _diagram(gallery_client, "nested-mounts", "developer")


@pytest.fixture(scope="module")
def customer_diagram(gallery_client: TestClient) -> str:
    return _diagram(gallery_client, "nested-mounts", "customer")


class TestTheDeveloperSeesTheComposition:
    def test_the_mount_is_a_block_rather_than_a_box(self, developer_diagram: str) -> None:
        assert "subgraph mount_mid" in developer_diagram

    def test_the_grandchild_is_a_block_inside_it(self, developer_diagram: str) -> None:
        assert "subgraph mount_mid_mount_inner" in developer_diagram

    def test_the_innermost_documents_own_nodes_are_drawn(
        self, developer_diagram: str
    ) -> None:
        """`chained-summarizer`, three levels down. `\\3a` is how
        `draw_mermaid` escapes the `:` in a prefixed id."""
        assert r"mount_mid\3amount_mid_mount_inner\3asummarise1" in developer_diagram
        assert r"mount_mid\3amount_mid_mount_inner\3ashorten1" in developer_diagram

    def test_the_compilers_own_names_are_kept(self, developer_diagram: str) -> None:
        """A mount bug is reported under the name the compiler used."""
        assert "__start__" in developer_diagram


class TestTheCustomerSeesTheSameCompositionInItsAuthorsWords:
    def test_the_composition_is_open(self, customer_diagram: str) -> None:
        assert "subgraph mount_mid" in customer_diagram

    def test_a_node_three_levels_down_carries_its_authors_title(
        self, customer_diagram: str
    ) -> None:
        assert "(Summarise)" in customer_diagram
        assert "(Cut to one sentence)" in customer_diagram

    def test_the_block_is_named_by_the_mount_the_author_titled(
        self, customer_diagram: str
    ) -> None:
        """`mount_mid` is a `safe_name`; `Nested Mounts (middle)` is what its
        author called that mount on the parent's canvas."""
        assert "Nested Mounts (middle)" in customer_diagram
        assert "Chained Summarizer" in customer_diagram

    def test_no_error_handler_leaks_from_any_depth(self, customer_diagram: str) -> None:
        """Each expanded child brings its own, and the substring strip only
        ever saw the top one."""
        assert "__default_error_handler__" not in customer_diagram

    def test_no_compiler_vocabulary_survives_anywhere(
        self, customer_diagram: str
    ) -> None:
        assert "__start__" not in customer_diagram
        assert "__end__" not in customer_diagram
        # A prefixed id is the compiler's word for a node, and it was the
        # obstacle this ticket named: the declaration parser did not match one,
        # so every nested label came through unrelabelled.
        assert "(in1)" not in customer_diagram
        assert "(out1)" not in customer_diagram


class TestAMountlessWorkflowIsUnchanged:
    """The inverse, and it is load-bearing: the expansion must be invisible to
    every document that mounts nothing."""

    def test_the_developer_diagram_has_no_blocks(self, gallery_client: TestClient) -> None:
        diagram = _diagram(gallery_client, "chained-summarizer", "developer")
        assert "subgraph" not in diagram
        assert "summarise1(summarise1)" in diagram
        assert "__default_error_handler__" in diagram

    def test_the_customer_diagram_is_what_it_always_was(
        self, gallery_client: TestClient
    ) -> None:
        diagram = _diagram(gallery_client, "chained-summarizer", "customer")
        assert "subgraph" not in diagram
        assert "summarise1(Summarise)" in diagram
        assert "__" not in diagram
