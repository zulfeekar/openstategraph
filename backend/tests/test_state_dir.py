"""Pointing at a directory must not write into it. Scale-and-adopt ticket 03.

The defect, stated exactly: `checkpoint_path()` defaulted to
`<workflows root>/.openstategraph/checkpoints.sqlite`, and the workflows root
is the directory the *user* chose. In this checkout that is fine — it is our
directory, it is gitignored, and a developer expects state beside the content
it is state about. Installed and pointed at someone else's folder it is three
different problems: we litter their tree, we may be inside their version
control, and on a read-only mount we cannot write at all.

So READ location (the workflows root) and WRITE location (the state dir) are
now separate questions, answered in one module. The discriminator is the one
this codebase already trusts and already tests — `checkout_root()`:

- **inside a checkout** → today's behaviour, byte-identical;
- **installed** → the platform's per-user state directory, keyed per project so
  two projects on one machine never share a thread namespace.

`OPENSTATEGRAPH_CHECKPOINT_PATH` stays authoritative above all of it.
"""

from __future__ import annotations

import sys

import pytest

import openstategraph.workflows_root as workflows_root_module
from openstategraph.memory import (
    CHECKPOINT_FILE_NAME,
    CHECKPOINT_PATH_ENV,
    build_checkpointer,
    checkpoint_path,
)
from openstategraph.state_dir import (
    STATE_DIR_ENV,
    STATE_DIR_NAME,
    state_dir,
    user_state_home,
)


@pytest.fixture(autouse=True)
def _no_ambient_state_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(STATE_DIR_ENV, raising=False)
    monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)


def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend this module lives in a wheel rather than in the checkout."""
    monkeypatch.setattr(workflows_root_module, "checkout_root", lambda: None)


class TestInsideACheckoutNothingMoves:
    """Ticket 03 explicitly permits keeping today's behaviour for the
    repo/server case, and keeping it is what makes this change reviewable:
    every existing checkpointer test passes untouched."""

    def test_state_sits_beside_the_workflows(self, tmp_path) -> None:
        assert state_dir(tmp_path) == tmp_path / STATE_DIR_NAME

    def test_and_so_does_the_checkpoint_file(self, tmp_path) -> None:
        assert checkpoint_path(tmp_path) == tmp_path / STATE_DIR_NAME / CHECKPOINT_FILE_NAME


class TestInstalledItNeverTouchesTheirFolder:
    def test_state_lands_in_the_per_user_state_directory(self, tmp_path, monkeypatch) -> None:
        installed(monkeypatch)

        resolved = state_dir(tmp_path / "their-project" / "workflows")

        assert user_state_home() in resolved.parents
        assert tmp_path not in resolved.parents

    def test_two_projects_never_share_a_thread_namespace(self, tmp_path, monkeypatch) -> None:
        """What the old default got right by accident and must not lose: the
        state was per-project because the root was. Two projects whose
        directories are both called `workflows` must still differ."""
        installed(monkeypatch)

        first = state_dir(tmp_path / "alpha" / "workflows")
        second = state_dir(tmp_path / "beta" / "workflows")

        assert first != second

    def test_the_same_project_resolves_to_the_same_place_twice(
        self, tmp_path, monkeypatch
    ) -> None:
        installed(monkeypatch)

        assert state_dir(tmp_path / "alpha" / "workflows") == state_dir(
            tmp_path / "alpha" / "workflows"
        )

    def test_the_directory_is_recognisably_the_project(self, tmp_path, monkeypatch) -> None:
        """A per-user state tree full of eight-hex-digit directories is a tree
        nobody can clean up. The label is for the human; the digest is for
        correctness."""
        installed(monkeypatch)

        assert "alpha" in state_dir(tmp_path / "alpha" / "workflows").name


class TestThePlatformConvention:
    def test_linux_follows_the_xdg_base_directory_spec(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

        assert user_state_home() == tmp_path / "xdg" / "openstategraph"

    def test_linux_falls_back_to_the_specs_own_default(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        assert user_state_home() == tmp_path / ".local" / "state" / "openstategraph"

    def test_macos_uses_application_support(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setenv("HOME", str(tmp_path))

        assert user_state_home() == (
            tmp_path / "Library" / "Application Support" / "openstategraph"
        )

    def test_windows_uses_localappdata(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

        assert user_state_home() == tmp_path / "AppData" / "Local" / "openstategraph"


class TestTheEnvironmentIsAuthoritative:
    def test_the_state_dir_can_be_named_outright(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "somewhere"))

        assert state_dir(tmp_path / "workflows") == (tmp_path / "somewhere").resolve()

    def test_the_checkpoint_path_still_outranks_the_state_dir(self, tmp_path, monkeypatch) -> None:
        """One env var already existed and adopters have it in their compose
        files. It stays the most specific answer there is."""
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "somewhere"))
        monkeypatch.setenv(CHECKPOINT_PATH_ENV, str(tmp_path / "explicit" / "cp.sqlite"))

        assert checkpoint_path(tmp_path) == tmp_path / "explicit" / "cp.sqlite"

    def test_and_can_still_opt_out_of_durability(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "somewhere"))
        monkeypatch.setenv(CHECKPOINT_PATH_ENV, "memory")

        assert checkpoint_path(tmp_path) is None


class TestAReadOnlyWorkflowsRoot:
    """The mount case, which is the one that used to crash rather than degrade."""

    @pytest.fixture
    def read_only_root(self, tmp_path):  # noqa: ANN201
        root = tmp_path / "readonly"
        (root / "flow").mkdir(parents=True)
        (root / "flow" / "workflow.json").write_text(
            '{"version": 1, "name": "Flow", "document": {"version": 2, "nodes": [], "edges": []}}'
        )
        root.chmod(0o555)
        yield root
        root.chmod(0o755)

    def test_listing_works(self, read_only_root) -> None:
        from openstategraph import Workflows

        assert [row.slug for row in Workflows(read_only_root).list()] == ["flow"]

    def test_installed_the_checkpointer_never_tries_to_write_there(
        self, read_only_root, monkeypatch, tmp_path
    ) -> None:
        installed(monkeypatch)
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "state"))

        saver = build_checkpointer(read_only_root)

        assert type(saver).__name__ == "SqliteSaver"
        assert (tmp_path / "state" / CHECKPOINT_FILE_NAME).exists()
        assert not (read_only_root / STATE_DIR_NAME).exists()
        from openstategraph.memory import close_resource

        close_resource(saver)

    def test_and_when_it_does_it_degrades_loudly_rather_than_crashing(
        self, read_only_root, caplog
    ) -> None:
        """In a checkout the state dir *is* under the root, so a read-only
        root is a write we cannot make. Losing durability is acceptable;
        losing the process is not — and it must say so."""
        with caplog.at_level("WARNING"):
            saver = build_checkpointer(read_only_root)

        assert type(saver).__name__ == "InMemorySaver"
        assert any("NOT survive a restart" in record.message for record in caplog.records)


class TestTheOutboxIsStateNotContent:
    """A dry-run `.eml` is diagnostic output, not something the user authored,
    so it belongs with the checkpoints and not in their workflows tree — where
    it was also un-gitignored and, on a read-only mount, an exception."""

    def test_it_lives_under_the_state_dir(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "state"))
        from openstategraph.prebuilt_email import outbox

        assert outbox() == (tmp_path / "state").resolve() / "outbox"

    def test_a_dry_run_send_writes_there(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "state"))
        monkeypatch.delenv("OPENSTATEGRAPH_SMTP_HOST", raising=False)
        from openstategraph.prebuilt_email import EmailSendTool

        result = EmailSendTool(to="someone@example.com").run(subject="Report", body="Hello")

        assert result.ok
        assert list((tmp_path / "state" / "outbox").glob("*.eml"))


class TestAPerWorkflowSqliteFileIsStateToo:
    def test_it_no_longer_lands_in_the_processs_working_directory(
        self, tmp_path, monkeypatch
    ) -> None:
        """`settings.checkpointer: "sqlite"` opened `.dev/checkpoints-<slug>.sqlite`
        — relative to the *cwd*, so running a workflow from someone's home
        directory created `~/.dev/`. It is state; it goes to the state dir."""
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "state"))
        monkeypatch.chdir(tmp_path)
        from openstategraph.memory import checkpointer_for, close_resource

        saver = checkpointer_for({"checkpointer": "sqlite"}, "billing", fallback=None)

        assert (tmp_path / "state" / "checkpoints-billing.sqlite").exists()
        assert not (tmp_path / ".dev").exists()
        close_resource(saver)
