"""Where the workflows root resolves to — the defect the clean-venv proof found.

Ticket 06. Four modules each computed the root as
`Path(__file__).resolve().parents[N] / "workflows"`, which is the repository
only while the file is inside one. Installed as a wheel it is
`<venv>/lib/python3.13/workflows`, and the symptom was not a crash — it was
`platform_list_workflows` replying **"No workflows exist yet."** with the
adopter's packages sitting in their project directory. A confident wrong answer
is the failure class this codebase names the worst kind, so it gets tests.

`checkout_root` is monkeypatched to `None` to stand in for "installed": inside
this repository it is legitimately not None, and a test that could only pass
outside its own checkout is a test nobody runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph import workflows_root as module
from openstategraph.workflows_root import (
    WORKFLOWS_ROOT_ENV,
    checkout_root,
    content_root,
    workflows_root,
)


@pytest.fixture(autouse=True)
def _no_ambient_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WORKFLOWS_ROOT_ENV, raising=False)


def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend this module is inside a wheel rather than the checkout."""
    monkeypatch.setattr(module, "checkout_root", lambda: None)


class TestInsideThisCheckoutNothingChanges:
    def test_the_root_is_the_repositorys_own_workflows(self) -> None:
        checkout = checkout_root()

        assert checkout is not None, "this test suite runs from the source tree"
        assert workflows_root() == checkout / "workflows"

    def test_and_the_read_jail_is_the_repository(self) -> None:
        assert content_root() == checkout_root()


class TestInstalledAsAWheel:
    def test_the_root_falls_back_to_the_processs_own_workflows(
        self, monkeypatch, tmp_path
    ) -> None:
        """`./workflows` is where `openstategraph new` already writes, so the
        first thing an adopter scaffolds is the first place we look."""
        installed(monkeypatch)
        monkeypatch.chdir(tmp_path)

        assert workflows_root() == tmp_path / "workflows"

    def test_it_never_resolves_inside_site_packages(self, monkeypatch, tmp_path) -> None:
        """The regression itself, stated as the thing that must not happen."""
        installed(monkeypatch)
        monkeypatch.chdir(tmp_path)

        assert "site-packages" not in str(workflows_root())
        assert Path(module.__file__).parent not in workflows_root().parents

    def test_the_read_jail_becomes_the_adopters_project(self, monkeypatch, tmp_path) -> None:
        installed(monkeypatch)
        monkeypatch.chdir(tmp_path)

        assert content_root() == tmp_path


class TestTheDeploymentGetsTheLastWord:
    def test_the_environment_variable_wins_over_the_checkout(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "elsewhere"))

        assert workflows_root() == tmp_path / "elsewhere"

    def test_it_is_read_per_call_not_frozen_at_import(self, monkeypatch, tmp_path) -> None:
        """A constant computed at import is exactly how the original bug became
        unoverridable — by the time anyone knew it was wrong, it was already
        baked into four modules."""
        first = workflows_root()
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path))

        assert workflows_root() == tmp_path != first

    def test_a_relative_value_is_resolved(self, monkeypatch, tmp_path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, "flows")

        assert workflows_root().is_absolute()


class TestTheFourCallersFollowIt:
    def test_the_store_defaults_to_it(self, monkeypatch, tmp_path) -> None:
        from openstategraph.api.workflow_store import WorkflowStore

        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path))

        assert WorkflowStore().root == tmp_path

    def test_the_store_accepts_a_string_root(self, tmp_path) -> None:
        """It used to fail one call later, in another module, with
        `unsupported operand type(s) for /: 'str' and 'str'`."""
        from openstategraph.api.workflow_store import WorkflowStore

        assert WorkflowStore(root=str(tmp_path)).root == tmp_path

    def test_the_platform_tool_lists_the_packages_that_are_there(
        self, monkeypatch, tmp_path
    ) -> None:
        from openstategraph.prebuilt_platform import PLATFORM_TOOLS

        package = tmp_path / "hello-there"
        package.mkdir()
        (package / "workflow.json").write_text(
            '{"name": "Hello There", "published": true, "document": {"nodes": [], "edges": []}}'
        )
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path))
        tool = next(t for t in PLATFORM_TOOLS if t.node_type == "tool.platform-list-workflows")

        assert "Hello There" in tool.run().content

    def test_the_sql_tool_resolves_a_database_under_it(self, monkeypatch, tmp_path) -> None:
        import sqlite3

        from openstategraph.prebuilt_sql import _resolve_database

        (tmp_path / "pkg" / "data").mkdir(parents=True)
        database = tmp_path / "pkg" / "data" / "x.sqlite"
        sqlite3.connect(database).close()
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path))

        assert _resolve_database("pkg/data/x.sqlite") == database.resolve()

    def test_the_email_outbox_follows_it_too(self, monkeypatch, tmp_path) -> None:
        from openstategraph.prebuilt_email import EmailSendTool, outbox

        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path))
        result = EmailSendTool(to="someone@example.com").run(subject="Hi", body="There")

        assert outbox() == tmp_path / "_outbox"
        assert result.ok and list((tmp_path / "_outbox").glob("*.eml"))
