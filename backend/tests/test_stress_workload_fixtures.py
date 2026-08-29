"""
Stress-test fixtures: compile and assert expected outcomes.

These are negative and positive fixtures found by stress-testing a complex
composite workflow (launch-readiness tickets 174-178). Each package tests
a specific defect or capability boundary.

No model is called; compilation and validation run offline with no network.
"""

import json
from pathlib import Path

import pytest

from openstategraph.validation import validate_document


STRESS_DIR = Path(__file__).parent / "workflows" / "stress"


def get_stress_packages() -> list[tuple[str, Path]]:
    """Return list of (package_name, path) for all stress fixtures."""
    packages = []
    if STRESS_DIR.exists():
        for pkg_dir in sorted(STRESS_DIR.iterdir()):
            if pkg_dir.is_dir() and (pkg_dir / "workflow.json").exists():
                packages.append((pkg_dir.name, pkg_dir))
    return packages


class TestStressFixturesExist:
    """A test that fails when a fixture is added but not covered."""

    # The expected fixtures as of the commit that added them.
    EXPECTED_FIXTURES = {
        "stress-review",
        "stress-review-audit",
        "stress-review-lint",
        "stress-deep",
        "stress-parallel-drop",
        "stress-async-probe",
        "stress-bad-static-cycle",
        "stress-bad-two-producers",
        "stress-bad-fallback",
        "stress-bad-ghost-mount",
    }

    def test_all_expected_fixtures_present(self) -> None:
        """Every expected fixture exists."""
        packages = get_stress_packages()
        found = {name for name, _ in packages}
        assert found == self.EXPECTED_FIXTURES, (
            f"Fixtures changed:\n"
            f"  Added: {found - self.EXPECTED_FIXTURES}\n"
            f"  Removed: {self.EXPECTED_FIXTURES - found}"
        )

    def test_no_unexpected_fixtures(self) -> None:
        """No fixtures exist that are not in EXPECTED_FIXTURES.

        This test fails when a new fixture is added, catching it before
        coverage is written. The test author must then:
        1. Add the package name to EXPECTED_FIXTURES
        2. Add a coverage test below (or update an existing parametrize)
        """
        packages = get_stress_packages()
        found = {name for name, _ in packages}
        unexpected = found - self.EXPECTED_FIXTURES
        if unexpected:
            pytest.fail(
                f"Unexpected fixtures found (update EXPECTED_FIXTURES and add coverage):\n"
                f"  {sorted(unexpected)}"
            )


class TestStressFixturesCompile:
    """Compile and assert expected outcomes for each stress fixture."""

    @pytest.mark.parametrize("package_name,package_path", get_stress_packages())
    def test_stress_fixture_compiles(
        self, package_name: str, package_path: Path
    ) -> None:
        """Load and compile each fixture, asserting expected outcome.

        Tickets:
        - 174: Two producers on parallel router (stress-parallel-drop)
        - 175: Routes field not published (stress-review, stress-parallel-drop)
        - 176: Step budget exhaustion message (stress-review)
        - 177: All-static cycle detection (stress-bad-static-cycle)
        - 178: Deep agent subagent recording (stress-deep)
        """
        workflow_json_path = package_path / "workflow.json"
        assert workflow_json_path.exists(), f"No workflow.json in {package_path}"

        with open(workflow_json_path) as f:
            raw_doc = json.load(f)

        # Extract the document from the wrapper
        document = raw_doc.get("document", raw_doc)

        # Validate the workflow
        is_valid, warnings = validate_document(document)

        # Compile and check expectations per package
        if package_name == "stress-bad-static-cycle":
            # This one should emit a warning about always_taken_cycles
            assert not is_valid, (
                "stress-bad-static-cycle should fail validation due to all-static cycle"
            )
            # Check that the warning mentions the cycle or loop
            warnings_text = "\n".join(str(w) for w in warnings).lower()
            assert "loop" in warnings_text or "cycle" in warnings_text, (
                f"Expected loop/cycle warning, got: {warnings_text}"
            )

        elif package_name == "stress-bad-ghost-mount":
            # This validates OK at the document level (mount resolution happens at load time)
            # So just verify it's syntactically valid
            assert is_valid, (
                f"stress-bad-ghost-mount should have valid document structure.\n"
                f"Warnings: {warnings}"
            )
            # Verify it has a mount node with a ghost reference
            has_ghost_mount = any(
                n.get("type") == "workflow.subgraph"
                and n.get("data", {}).get("workflow") == "no-such-package"
                for n in document.get("nodes", [])
            )
            assert has_ghost_mount, "stress-bad-ghost-mount should have a mount to non-existent package"

        else:
            # All other fixtures should compile successfully
            assert is_valid, (
                f"{package_name} should compile successfully.\n"
                f"Warnings: {warnings}"
            )

    def test_stress_review_is_complex(self) -> None:
        """stress-review has router, supervisor, workers, grader, mount."""
        package_path = STRESS_DIR / "stress-review"
        workflow_json_path = package_path / "workflow.json"

        with open(workflow_json_path) as f:
            raw_doc = json.load(f)
        document = raw_doc.get("document", raw_doc)

        # Check for expected node types
        node_types = {n.get("type") for n in document.get("nodes", [])}
        assert any("route" in t for t in node_types), "Expected router node"
        assert any("agent" in t for t in node_types), "Expected agent node(s)"
        assert any("orchestrate" in t for t in node_types), "Expected orchestrator"
        assert any("grade" in t for t in node_types), "Expected grader node"

        # Validate successfully
        is_valid, warnings = validate_document(document)
        assert is_valid, f"stress-review should compile. Warnings: {warnings}"

    def test_stress_deep_has_deep_agent(self) -> None:
        """stress-deep has at least one agent.llm node with tier: 'deep'."""
        package_path = STRESS_DIR / "stress-deep"
        workflow_json_path = package_path / "workflow.json"

        with open(workflow_json_path) as f:
            raw_doc = json.load(f)
        document = raw_doc.get("document", raw_doc)

        # Check for a node with tier: 'deep' (deep agents are agent.llm with tier config)
        has_deep_tier = any(
            n.get("data", {}).get("tier") == "deep" for n in document.get("nodes", [])
        )
        assert has_deep_tier, "stress-deep should have agent with tier: 'deep'"

        # Validate successfully
        is_valid, warnings = validate_document(document)
        assert is_valid, f"stress-deep should compile. Warnings: {warnings}"

    def test_stress_parallel_drop_has_parallel_router(self) -> None:
        """stress-parallel-drop has matchMode: 'all' router."""
        package_path = STRESS_DIR / "stress-parallel-drop"
        workflow_json_path = package_path / "workflow.json"

        with open(workflow_json_path) as f:
            raw_doc = json.load(f)
        document = raw_doc.get("document", raw_doc)

        # Find router with matchMode: "all"
        has_parallel_router = any(
            n.get("type") == "route.classifier"
            and n.get("data", {}).get("matchMode") == "all"
            for n in document.get("nodes", [])
        )
        assert has_parallel_router, "stress-parallel-drop should have parallel router"

        # Validate successfully (the defect is in execution/reporting, not compilation)
        is_valid, warnings = validate_document(document)
        assert is_valid, f"stress-parallel-drop should compile. Warnings: {warnings}"
