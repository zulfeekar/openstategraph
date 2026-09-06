"""An override through the parent took effect and said nothing about whose
node it changed — `launch-readiness` 40.

Stranger run 4 (`docs/decisions/stranger-install-2026-08-24-run4.md`) edited
`nested-mounts-mid`'s `mount-inner` node to override the leaf package's
`shorten1.systemPrompt`, three levels down inside `nested-mounts`. The
override worked — confirmed by a literal tag in the model's own answer — but
neither `validate` nor `run` printed which mount path or instance it reached.
That matters most for `same-package-twice`: two sibling mounts of one package,
each carrying its own `data.overrides`, where a misrouted override would
silently change the wrong instance and look like success.

`Finding.OVERRIDE_APPLIED` (`compile/diagnostics.py`) is the fix: recorded at
the mount that applies an override, keyed by that mount's own node id rather
than by package slug, so two mounts of one package produce two distinct
sentences instead of the one `CompileDiagnostics.absorb` would collapse them
to by package identity (the way `OVERRIDE_PROBLEM` and friends already do,
deliberately, for findings that ARE a property of the package).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"


def _load_warnings(package_dir: Path) -> list[str]:
    from openstategraph import load_workflow

    with load_workflow(package_dir, model=object()) as workflow:
        return list(workflow.warnings)


class TestApplyMountOverridesReportsWhatItWrote:
    """The unit underneath the compiler-level behaviour: `apply_mount_overrides`
    is the one owner of the merge (`api/mount_resolution.py`'s docstring), so
    it is the one place that can say which field of which child node a write
    actually reached."""

    def test_a_successful_write_is_recorded(self) -> None:
        from openstategraph.compile.node_runtime import apply_mount_overrides

        child = {"nodes": [{"id": "shorten1", "type": "agent.llm", "data": {}}]}
        applied: list[tuple[str, str]] = []
        apply_mount_overrides(
            child, {"shorten1": {"systemPrompt": "be terse"}}, applied=applied
        )
        assert applied == [("shorten1", "systemPrompt")]

    def test_an_unknown_target_records_nothing(self) -> None:
        from openstategraph.compile.node_runtime import apply_mount_overrides

        child = {"nodes": [{"id": "shorten1", "type": "agent.llm", "data": {}}]}
        applied: list[tuple[str, str]] = []
        apply_mount_overrides(child, {"nonsense": {"criteria": "x"}}, applied=applied)
        assert applied == []

    def test_no_out_param_means_no_tracking_and_no_new_behaviour(self) -> None:
        """Every existing 2-tuple call site passes nothing here — this must
        stay a strict no-op for them."""
        from openstategraph.compile.node_runtime import apply_mount_overrides

        child = {"nodes": [{"id": "shorten1", "type": "agent.llm", "data": {}}]}
        doc, warnings = apply_mount_overrides(child, {"shorten1": {"systemPrompt": "x"}})
        assert doc["nodes"][0]["data"]["systemPrompt"] == "x"
        assert warnings == []


class TestSamePackageMountedTwice:
    """The shipped `same-package-twice` example: two sibling mounts of
    `chained-summarizer`, each overriding `shorten1.systemPrompt` with a
    DIFFERENT prompt. This is exactly the case ticket 40 says matters most —
    a misrouted override here is a silently wrong instance, not a crash."""

    def test_both_instances_are_named_and_distinct(self) -> None:
        warnings = _load_warnings(EXAMPLES / "same-package-twice")
        applied = [w for w in warnings if w.startswith("Mount override applied")]
        assert len(applied) == 2
        assert any('"mount-terse"' in w for w in applied)
        assert any('"mount-analogy"' in w for w in applied)
        # Not merely two lines — two DIFFERENT lines, one per mount's own
        # node id, both naming the same child node and field.
        assert len(set(applied)) == 2
        for line in applied:
            assert 'chained-summarizer#shorten1.systemPrompt' in line

    def test_an_unrelated_override_problem_stays_untouched(self) -> None:
        """Guard against the new Finding stealing subjects or breaking the
        existing failure channel: this example carries no OVERRIDE_PROBLEM,
        and OVERRIDE_APPLIED must never reach failure_warnings — it is a
        report, confirmation that the write it describes already succeeded."""
        from openstategraph import load_workflow

        with load_workflow(EXAMPLES / "same-package-twice", model=object()) as workflow:
            assert not any(
                "Mount override applied" in w for w in workflow.failure_warnings
            )


class TestTwoLevelsDeep:
    """`nested-mounts` -> `nested-mounts-mid` -> `chained-summarizer`, the
    exact fixture stranger run 4 used, with the same override added at the
    MIDDLE level it edited. A copy in a temp dir, never the shipped example,
    since `workflows/` and shipped packages are not touched for a test."""

    @pytest.fixture()
    def two_level_package(self, tmp_path: Path) -> Path:
        for slug in ("nested-mounts", "nested-mounts-mid", "chained-summarizer"):
            shutil.copytree(EXAMPLES / slug, tmp_path / slug)
        mid_manifest = tmp_path / "nested-mounts-mid" / "workflow.json"
        doc = json.loads(mid_manifest.read_text())
        for node in doc["document"]["nodes"]:
            if node["id"] == "mount-inner":
                node["data"]["overrides"] = {
                    "shorten1": {"systemPrompt": "end it with the exact tag [OVERRIDE-APPLIED]."}
                }
        mid_manifest.write_text(json.dumps(doc))
        return tmp_path / "nested-mounts"

    def test_the_full_chain_is_named(self, two_level_package: Path) -> None:
        warnings = _load_warnings(two_level_package)
        applied = [w for w in warnings if "Mount override applied" in w]
        assert len(applied) == 1
        line = applied[0]
        # The enclosing document (absorbed with `through=slug`), the mount
        # node inside it, the leaf package, the leaf node, the field — the
        # whole path, not just the nearest hop.
        assert 'Inside mounted workflow "nested-mounts-mid"' in line
        assert '"mount-inner"' in line
        assert 'chained-summarizer#shorten1.systemPrompt' in line

    def test_an_unmodified_copy_names_nothing(self, tmp_path: Path) -> None:
        """The silent case stranger run 4 first hit, before it edited
        anything: no override, no line — confirming this Finding is
        conditioned on an actual write, not on the presence of a mount."""
        for slug in ("nested-mounts", "nested-mounts-mid", "chained-summarizer"):
            shutil.copytree(EXAMPLES / slug, tmp_path / slug)
        warnings = _load_warnings(tmp_path / "nested-mounts")
        assert not any("Mount override applied" in w for w in warnings)


class TestValidateSurfacesIt:
    """`openstategraph validate` — the zero-token gate a developer runs before
    a live model call — is where ticket 40 asks for this, at minimum. It
    reaches `cmd_validate` through `_compiler_findings`, which already splits
    `REPORT_ONLY` findings into a `Notes:` section (`organisms-first-class`
    66); `OVERRIDE_APPLIED` rides that existing channel rather than adding a
    second one."""

    def test_validate_reports_it_as_a_note_not_a_problem(self, capsys: pytest.CaptureFixture[str]) -> None:
        from openstategraph.cli import cmd_validate

        class Args:
            target = str(EXAMPLES / "same-package-twice")

        exit_code = cmd_validate(Args())
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "VALID" in out or "PROBLEMS FOUND" not in out
        assert "Notes:" in out
        assert "Mount override applied" in out
        assert '"mount-terse"' in out
        assert '"mount-analogy"' in out
