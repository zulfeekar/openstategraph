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

from openstategraph.compile.workflow_compiler import WorkflowCompiler
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

        elif package_name == "stress-bad-two-producers":
            # `launch-readiness/174`: two desks writing into ONE output port is
            # the shape `capacityRule` refuses to *draw* and the compiler
            # accepts — and it is the shape that WORKS, returning both halves,
            # which is the inversion 174 found. So the assertion is not
            # "it compiles" but that it is the fan-in, and that the two
            # documents 174 reconciled still say the same thing.
            assert is_valid, f"the forbidden fan-in still compiles: {warnings}"
            into_out = [
                e
                for e in document.get("edges", [])
                if (e.get("target") or {}).get("nodeId") == "out1"
            ]
            assert len(into_out) == 2, (
                "stress-bad-two-producers must keep TWO producers on one output "
                f"port — that is the whole fixture. Found {len(into_out)}."
            )

        elif package_name == "stress-bad-fallback":
            # `launch-readiness/184`, filed the day this fixture was committed.
            # Its router declares `fallback: "nonexistent-branch"`, and the
            # document validates clean. This assertion pins the DEFECT, not the
            # desired behaviour: when 184 lands, this test goes red and whoever
            # fixes it updates the expectation here. A fixture built to show a
            # defect must never be asserted as "compiles successfully" — that
            # encodes the defect as correct and turns a future regression green.
            branch_ids = {
                b.get("id")
                for n in document.get("nodes", [])
                if n.get("type") == "route.classifier"
                for b in n.get("data", {}).get("branches", [])
            }
            fallback = next(
                (
                    n.get("data", {}).get("fallback")
                    for n in document.get("nodes", [])
                    if n.get("type") == "route.classifier"
                ),
                None,
            )
            assert fallback not in branch_ids, (
                "stress-bad-fallback must keep a fallback naming no branch — "
                "that is the whole fixture."
            )
            assert is_valid and not warnings, (
                "Known gap, launch-readiness/184: a fallback naming a branch "
                "that does not exist still validates clean. If this assertion "
                "just failed, 184 was fixed — assert the refusal instead."
            )

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


class TestEveryFixtureReachesTheCompiler:
    """Validation is not compilation, and this file claimed both.

    `validate_document` reads the document; `WorkflowCompiler.plan` is where
    `launch-readiness/177`'s `always_taken_cycles` actually lives and where a
    document that reads well can still fail to build. A fixture set that only
    validates would have missed the rule it was collected to protect.
    """

    @pytest.mark.parametrize(
        "package_name,package_path", get_stress_packages(), ids=lambda v: str(v)
    )
    def test_the_plan_agrees_with_the_document(
        self, package_name: str, package_path: Path
    ) -> None:
        raw_doc = json.loads((package_path / "workflow.json").read_text())
        document = raw_doc.get("document", raw_doc)

        plan = WorkflowCompiler().plan(document)
        is_valid, _ = validate_document(document)

        # The two doors must not disagree about one document: `validate_document`
        # is `plan.warnings` seen from the CLI, so a fixture the compiler flags
        # and the validator passes would mean one of them stopped reading the
        # other (`launch-readiness/177` wired them to one channel deliberately).
        assert bool(plan.warnings) == (not is_valid), (
            f"{package_name}: plan.warnings={[str(w)[:80] for w in plan.warnings]} "
            f"but validate_document said valid={is_valid}"
        )
