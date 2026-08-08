"""Tests for the Code Workshop tools — the safety rails above all.

Loaded by file path under a synthetic module name, exactly like
`tabular-analytics`'s tests and for the same reason: a hyphenated slug can
never be a package, and putting a second workflow on `pytest.ini`'s
`pythonpath` recreates the `tools` collision its comment warns about.

Every test that needs a workspace builds one in `tmp_path` — the shipped
`data/fixture-repo` is read as the template but never written to, and the
real `scratch/`/`output/` directories are never touched by the suite.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

WORKFLOW_DIR = Path(__file__).resolve().parent.parent


def _load_workshop_module():
    name = "dyflow_workflow_code_workshop_tools_workshop"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, WORKFLOW_DIR / "tools" / "workshop.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


workshop = _load_workshop_module()


@pytest.fixture()
def dirs(tmp_path: Path) -> dict[str, Path]:
    return {
        "scratch_dir": tmp_path / "scratch" / "repo",
        "fixture_dir": workshop.FIXTURE_DIR,
        "output_dir": tmp_path / "output",
    }


@pytest.fixture()
def workspace(dirs: dict[str, Path]) -> dict[str, Path]:
    """A freshly reset workspace in tmp_path, ready for the other tools."""
    result = workshop.ResetWorkspaceTool(**dirs).run()
    assert result.error is None, result.error
    return dirs


class TestResetWorkspace:
    def test_creates_an_isolated_git_workspace_from_the_fixture(self, dirs) -> None:
        result = workshop.ResetWorkspaceTool(**dirs).run()
        assert result.error is None
        assert "stats.py" in result.content
        assert (dirs["scratch_dir"] / ".git").is_dir()
        assert (dirs["scratch_dir"] / "tests" / "test_stats.py").is_file()

    def test_reset_discards_previous_changes(self, workspace) -> None:
        marker = workspace["scratch_dir"] / "leftover.txt"
        marker.write_text("junk")
        result = workshop.ResetWorkspaceTool(**workspace).run()
        assert result.error is None
        assert not marker.exists()

    def test_the_baseline_is_committed_so_diff_starts_empty(self, workspace) -> None:
        result = workshop.DiffTool(**workspace).run()
        assert result.error is None
        assert "No changes" in result.content

    def test_a_missing_fixture_is_a_failure_not_a_crash(self, dirs, tmp_path) -> None:
        dirs = {**dirs, "fixture_dir": tmp_path / "nope"}
        result = workshop.ResetWorkspaceTool(**dirs).run()
        assert result.error is not None


class TestTheJail:
    """The non-negotiable rails: no path leaves the scratch directory."""

    def test_dotdot_escape_is_refused(self, workspace) -> None:
        result = workshop.ReadFileTool(**workspace).run(path="../../outside.txt")
        assert result.error is not None
        assert "escape" in result.error.lower() or "jail" in result.error.lower()

    def test_absolute_path_is_refused(self, workspace) -> None:
        result = workshop.ReadFileTool(**workspace).run(path="/etc/hosts")
        assert result.error is not None

    def test_write_cannot_escape_either(self, workspace, tmp_path) -> None:
        result = workshop.WriteFileTool(**workspace).run(
            path="../escaped.txt", content="nope"
        )
        assert result.error is not None
        assert not (tmp_path / "scratch" / "escaped.txt").exists()

    def test_a_symlink_pointing_outside_is_refused_on_read(self, workspace, tmp_path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("secret")
        os.symlink(secret, workspace["scratch_dir"] / "link.txt")
        result = workshop.ReadFileTool(**workspace).run(path="link.txt")
        assert result.error is not None

    def test_the_git_directory_is_off_limits(self, workspace) -> None:
        read = workshop.ReadFileTool(**workspace).run(path=".git/config")
        write = workshop.WriteFileTool(**workspace).run(path=".git/hooks/pre-commit", content="#!/bin/sh")
        assert read.error is not None
        assert write.error is not None

    def test_every_file_tool_demands_a_workspace_first(self, dirs) -> None:
        for tool in (
            workshop.ListFilesTool(**dirs),
            workshop.RunTestsTool(**dirs),
            workshop.DiffTool(**dirs),
        ):
            result = tool.run()
            assert result.error is not None
            assert "workshop_reset_workspace" in result.error


class TestReadWriteList:
    def test_write_then_read_roundtrip(self, workspace) -> None:
        write = workshop.WriteFileTool(**workspace).run(path="notes.md", content="hello")
        assert write.error is None
        read = workshop.ReadFileTool(**workspace).run(path="notes.md")
        assert read.error is None
        assert read.content == "hello"

    def test_list_shows_fixture_files_but_never_git_internals(self, workspace) -> None:
        result = workshop.ListFilesTool(**workspace).run()
        assert result.error is None
        assert "stats.py" in result.content
        # `.gitignore` is a legitimate listing; `.git/` internals are not.
        assert not any(
            line.startswith(".git/") or line == ".git"
            for line in result.content.splitlines()
        )

    def test_reading_a_missing_file_is_a_failure_naming_it(self, workspace) -> None:
        result = workshop.ReadFileTool(**workspace).run(path="ghost.py")
        assert result.error is not None
        assert "ghost.py" in result.error


class TestRunTests:
    def test_the_seeded_failure_arrives_as_a_report_not_an_exception(self, workspace) -> None:
        result = workshop.RunTestsTool(**workspace).run()
        assert result.error is None  # a failing suite is data, not a tool failure
        assert "TESTS FAILED" in result.content
        assert "test_median_of_even_length_list" in result.content

    def test_fixing_the_bug_turns_the_report_green(self, workspace) -> None:
        fixed = (workspace["scratch_dir"] / "stats.py").read_text().replace(
            "    return ordered[len(ordered) // 2]",
            "    mid = len(ordered) // 2\n"
            "    if len(ordered) % 2 == 0:\n"
            "        return (ordered[mid - 1] + ordered[mid]) / 2\n"
            "    return ordered[mid]",
        )
        write = workshop.WriteFileTool(**workspace).run(path="stats.py", content=fixed)
        assert write.error is None
        result = workshop.RunTestsTool(**workspace).run()
        assert result.error is None
        assert "ALL TESTS PASSED" in result.content


class TestDiff:
    def test_a_change_shows_as_a_unified_diff(self, workspace) -> None:
        original = (workspace["scratch_dir"] / "stats.py").read_text()
        workshop.WriteFileTool(**workspace).run(
            path="stats.py", content=original + "\n# touched\n"
        )
        result = workshop.DiffTool(**workspace).run()
        assert result.error is None
        assert "--- a/stats.py" in result.content
        assert "+# touched" in result.content

    def test_new_files_appear_in_the_diff_too(self, workspace) -> None:
        workshop.WriteFileTool(**workspace).run(path="brand_new.py", content="x = 1\n")
        result = workshop.DiffTool(**workspace).run()
        assert result.error is None
        assert "brand_new.py" in result.content


class TestCreatePr:
    def test_dry_run_writes_patch_and_body_and_never_touches_gh(self, workspace, monkeypatch) -> None:
        tool = workshop.CreatePrTool(**workspace)
        monkeypatch.setattr(
            tool, "_run_gh", lambda *a, **k: pytest.fail("gh invoked in dry-run mode")
        )
        workshop.WriteFileTool(**workspace).run(path="stats.py", content="# rewritten\n")
        result = tool.run(title="Fix median", body="Median of even-length lists.")
        assert result.error is None
        assert "DRY RUN" in result.content
        patch = (workspace["output_dir"] / "change.patch").read_text()
        body = (workspace["output_dir"] / "PR.md").read_text()
        assert "stats.py" in patch
        assert "# Fix median" in body

    def test_no_changes_means_nothing_to_submit(self, workspace) -> None:
        result = workshop.CreatePrTool(**workspace).run(title="Empty", body="Nothing.")
        assert result.error is not None
        assert "no changes" in result.error.lower()

    def test_gh_is_opt_in_via_the_nodes_useGh_field(self, workspace) -> None:
        tool = workshop.CreatePrTool(**workspace)
        assert tool.use_gh is False
        assert tool.configure({}).use_gh is False
        assert tool.configure({"useGh": False}).use_gh is False
        opted_in = tool.configure({"useGh": True})
        assert opted_in.use_gh is True
        assert opted_in is not tool  # fresh instance, never a mutation
        assert opted_in.scratch_dir == tool.scratch_dir

    def test_opted_in_gh_failure_comes_back_as_data(self, workspace, monkeypatch) -> None:
        tool = workshop.CreatePrTool(**workspace).configure({"useGh": True})
        monkeypatch.setattr(
            tool,
            "_run_gh",
            lambda *a, **k: subprocess.CompletedProcess(
                args=["gh"], returncode=1, stdout="", stderr="no remote configured"
            ),
        )
        workshop.WriteFileTool(**workspace).run(path="stats.py", content="# rewritten\n")
        result = tool.run(title="Fix", body="Body.")
        assert result.error is not None
        assert "no remote configured" in result.error
        # The dry-run artifacts are still written even when gh refuses.
        assert (workspace["output_dir"] / "change.patch").is_file()


class TestCatalogue:
    def test_seven_tools_with_unique_names_and_node_types(self) -> None:
        names = [tool.name for tool in workshop.TOOLS]
        node_types = [tool.node_type for tool in workshop.TOOLS]
        assert len(names) == 7
        assert len(set(names)) == 7
        assert len(set(node_types)) == 7
        assert all(t.startswith("tool.workshop-") for t in node_types)

    def test_every_tool_publishes_a_manifest(self) -> None:
        for tool in workshop.TOOLS:
            manifest = tool.manifest()
            assert manifest["name"] == tool.name
            assert manifest["args_schema"]

    def test_timeout_is_configurable_per_node(self) -> None:
        tool = workshop.RunTestsTool()
        configured = tool.configure({"timeoutSeconds": 30})
        assert configured.timeout_seconds == 30
        assert tool.timeout_seconds != 30 or tool is not configured
