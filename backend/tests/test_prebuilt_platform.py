"""Read-only platform tools (ticket 67 refinement: no write, everything else)."""

from __future__ import annotations

from openstategraph.prebuilt_platform import (
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


class TestDotfilesAreSecrets:
    def test_env_and_any_dotfile_are_unreadable(self) -> None:
        assert PlatformReadTool().run(path=".env").error is not None
        assert PlatformReadTool().run(path=".env.example").error is not None
        assert PlatformLsTool().run(path=".github").error is not None
