"""Read-only platform tools (ticket 67 refinement: no write, everything else)."""

from __future__ import annotations

from pathlib import Path

from openstategraph.prebuilt_platform import (
    EXCLUDED_DIRS,
    DescribeWorkflowTool,
    ListWorkflowsTool,
    PlatformGrepTool,
    PlatformLsTool,
    PlatformReadTool,
)


class TestIntrospection:
    def test_lists_visible_workflows_and_hides_hidden_ones(self) -> None:
        result = ListWorkflowsTool().run()
        assert result.error is None
        assert "tabular-analytics" in result.content
        assert "concierge" not in result.content

    def test_describe_reads_the_packages_own_docs(self) -> None:
        result = DescribeWorkflowTool().run(slug="data-analyst-team")
        assert result.error is None
        assert "Team" in result.content and "Nodes:" in result.content

    def test_describe_refuses_the_hidden_gateway(self) -> None:
        assert DescribeWorkflowTool().run(slug="concierge").error is not None


class TestReadOnlyJail:
    def test_ls_and_read_work_inside_the_repo(self) -> None:
        listing = PlatformLsTool().run(path=".")
        assert listing.error is None and "workflows/" in listing.content
        readme = PlatformReadTool().run(path="README.md")
        assert readme.error is None and "OpenStateGraph" in readme.content

    def test_escapes_are_refused(self) -> None:
        assert PlatformLsTool().run(path="../..").error is not None
        assert PlatformReadTool().run(path="../../etc/passwd").error is not None
        assert PlatformReadTool().run(path=".git/config").error is not None

    def test_grep_finds_and_caps(self) -> None:
        result = PlatformGrepTool().run(pattern="StateGraph", path="backend/openstategraph")
        assert result.error is None
        assert "workflow_compiler" in result.content

    def test_grep_never_reports_a_hit_from_an_excluded_directory(self) -> None:
        """Pins the jail's *result* rather than its traversal.

        The walk was changed to prune `EXCLUDED_DIRS` before descending
        instead of enumerating the whole tree and filtering afterwards. That
        is a traversal change with no visible effect, and this is what says
        so: the admitted set — and therefore every reported line — must be
        identical either way.
        """
        result = PlatformGrepTool().run(pattern="the", path=".")
        assert result.error is None
        for line in result.content.splitlines():
            rel = line.split(":", 1)[0]
            assert not any(
                part in EXCLUDED_DIRS or part.startswith(".") for part in Path(rel).parts
            ), f"grep reported a hit inside an excluded path: {rel}"

    def test_grep_results_are_ordered_by_path(self) -> None:
        """The `MAX_MATCHES` cap makes ordering load-bearing: which 60 lines
        come back depends on the order files are visited, so a traversal
        rewrite must preserve it. Sorted-by-path is that order."""
        result = PlatformGrepTool().run(pattern="StateGraph", path="backend/openstategraph")
        files = [line.split(":", 1)[0] for line in result.content.splitlines() if ":" in line]
        assert files == sorted(files)


class TestDotfilesAreSecrets:
    def test_env_and_any_dotfile_are_unreadable(self) -> None:
        assert PlatformReadTool().run(path=".env").error is not None
        assert PlatformReadTool().run(path=".env.example").error is not None
        assert PlatformLsTool().run(path=".github").error is not None
