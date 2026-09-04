"""kanban-patrol/03. `project_id` mint-together + companion-verify.

The story: `openstategraph.yaml` is committed and copyable like any repo
file. Clone it, `cp -r` it, or email a zip to bootstrap a second project from
a first, and a bare `project_id:` line comes along for free — two projects
now share one identity. The fix pairs it with a companion marker in the
gitignored `.openstategraph/` dir, written only at mint time, so a copy that
carries the yaml but not the dotfile is detectable rather than silently
trusted.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.project_identity import (
    ProjectIdentityState,
    ensure_project_identity,
)


class TestMinting:
    def test_no_project_id_mints_both_halves(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".openstategraph"

        result = ensure_project_identity(project_id=None, state_dir=state_dir)

        assert result.state is ProjectIdentityState.MINTED
        assert result.project_id is not None
        assert (state_dir / "project_identity").read_text().strip() == result.project_id

    def test_two_mints_never_collide(self, tmp_path: Path) -> None:
        a = ensure_project_identity(project_id=None, state_dir=tmp_path / "a" / ".openstategraph")
        b = ensure_project_identity(project_id=None, state_dir=tmp_path / "b" / ".openstategraph")

        assert a.project_id != b.project_id


class TestVerifying:
    def test_matching_companion_is_verified_and_writes_nothing_new(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".openstategraph"
        minted = ensure_project_identity(project_id=None, state_dir=state_dir)
        before = (state_dir / "project_identity").stat().st_mtime_ns

        again = ensure_project_identity(project_id=minted.project_id, state_dir=state_dir)

        assert again.state is ProjectIdentityState.VERIFIED
        assert again.project_id == minted.project_id
        assert (state_dir / "project_identity").stat().st_mtime_ns == before


class TestTheCopiedConfigCase:
    def test_a_project_id_with_no_companion_is_unverified_not_trusted(self, tmp_path: Path) -> None:
        """The clone/cp-r story: the yaml's `project_id` arrived, the
        gitignored companion did not."""
        state_dir = tmp_path / ".openstategraph"

        result = ensure_project_identity(project_id="borrowed-from-elsewhere", state_dir=state_dir)

        assert result.state is ProjectIdentityState.UNVERIFIED
        assert result.project_id == "borrowed-from-elsewhere"

    def test_unverified_never_writes_a_companion(self, tmp_path: Path) -> None:
        """Ambiguous cases are answered by asking — this function must never
        pick for the caller by writing a companion that endorses either
        reading."""
        state_dir = tmp_path / ".openstategraph"

        ensure_project_identity(project_id="borrowed-from-elsewhere", state_dir=state_dir)

        assert not (state_dir / "project_identity").exists()

    def test_a_mismatched_companion_is_unverified(self, tmp_path: Path) -> None:
        """Belt-and-suspenders: even if a companion exists but disagrees with
        the yaml (two configs' dotfiles merged by an unrelated copy), that is
        still 'not proven', not 'proven wrong' — same UNVERIFIED state, same
        ask-don't-guess handling downstream."""
        state_dir = tmp_path / ".openstategraph"
        state_dir.mkdir(parents=True)
        (state_dir / "project_identity").write_text("some-other-id\n")

        result = ensure_project_identity(project_id="the-yaml-says-this-one", state_dir=state_dir)

        assert result.state is ProjectIdentityState.UNVERIFIED


class TestNeverOverwritesAnExistingId:
    def test_minted_is_only_reachable_when_project_id_is_none(self, tmp_path: Path) -> None:
        """`InitResult`'s own rule, carried here: only ever add, never
        replace. A present `project_id` — verified or not — never gets
        silently re-minted by this function; only the caller, having asked
        the human, may choose to call this again with `project_id=None`."""
        state_dir = tmp_path / ".openstategraph"

        result = ensure_project_identity(project_id="already-there", state_dir=state_dir)

        assert result.state is not ProjectIdentityState.MINTED


class TestAdoptingAConfigThatPredatesTheField:
    """kanban-patrol/23. `ensure_project_identity` mints for a config being
    *created*; a project made before this field existed has a real file, with
    comments and an order somebody chose, and nothing was ever allowed to add
    the line to it — so the kanban board stayed permanently dead there.

    The owner's decision (2026-09-04): append `project_id:` as the last line,
    with a comment saying who wrote it and why, and print it. A column-0 key
    at EOF is valid YAML whatever precedes it, so nothing above is reparsed
    or rewritten.
    """

    HAND_WRITTEN = (
        "# our project's config — hand edited, order chosen\n"
        "version: 1\n"
        "\n"
        "# where the packages live\n"
        "workflows_dir: workflows\n"
        "providers:\n"
        "  - id: ollama\n"
        "    enabled: true\n"
        "default_model: ollama:gpt-oss:120b-cloud"  # deliberately no trailing newline
    )

    def test_appends_exactly_one_line_and_every_prior_key_survives(self, tmp_path: Path) -> None:
        import yaml

        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "openstategraph.yaml"
        config.write_text(self.HAND_WRITTEN)
        before = yaml.safe_load(self.HAND_WRITTEN)

        result = adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        text = config.read_text()
        assert result.state is ProjectIdentityState.MINTED
        assert len([line for line in text.splitlines() if line.startswith("project_id:")]) == 1
        assert text.endswith(f"project_id: {result.project_id}\n")
        after = yaml.safe_load(text)
        assert after.pop("project_id") == result.project_id
        assert after == before
        # The comment says who wrote it and why, and cites the ticket.
        assert "# project_id — added by openstategraph on " in text
        assert "kanban-patrol/03" in text
        # The other half of the identity, per this module's own story.
        assert (tmp_path / ".openstategraph" / "project_identity").read_text().strip() == result.project_id

    def test_a_file_that_already_ends_in_a_newline_grows_no_blank_line(self, tmp_path: Path) -> None:
        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "openstategraph.yaml"
        config.write_text("version: 1\nworkflows_dir: workflows\n")

        adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        lines = config.read_text().splitlines()
        assert lines[1] == "workflows_dir: workflows"
        assert lines[2].startswith("# project_id —")
        assert lines[3].startswith("project_id: ")
        assert len(lines) == 4

    def test_a_config_that_already_has_one_is_untouched_byte_for_byte(self, tmp_path: Path) -> None:
        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "openstategraph.yaml"
        original = "version: 1\nproject_id: already-there\nworkflows_dir: workflows\n"
        config.write_text(original)

        result = adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert config.read_text() == original
        assert result.state is not ProjectIdentityState.MINTED
        assert result.project_id == "already-there"

    def test_a_carrier_this_cannot_safely_append_to_is_refused_not_guessed(self, tmp_path: Path) -> None:
        """A `pyproject.toml [tool.openstategraph]` or a JSON config is not a
        file where a column-0 YAML key at EOF means anything. Refused by name
        rather than corrupted."""
        import pytest

        from openstategraph.project_identity import ProjectIdentityError, adopt_project_id

        config = tmp_path / "pyproject.toml"
        config.write_text("[tool.openstategraph]\nversion = 1\n")

        with pytest.raises(ProjectIdentityError) as exc:
            adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert "pyproject.toml" in str(exc.value)


class TestTheDoorsThatAdopt:
    """kanban-patrol/23 wires three doors to `adopt_project_id`; the CLI
    `patrol run` one is pinned in `test_cli_kanban.py`, beside its siblings.
    This is the `openstategraph .` / `serve` one, which prints the line
    before anything is bound."""

    def test_serve_prints_the_line_it_just_wrote(self, tmp_path: Path, monkeypatch) -> None:
        from openstategraph.cli import adopted_project_id_note
        from openstategraph.config_file import reset_active_config

        config = tmp_path / "openstategraph.yaml"
        config.write_text("version: 1\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()

        note = adopted_project_id_note()

        assert note is not None
        assert "project_id: " in note
        written = config.read_text()
        assert note.split()[1] in written
        # Said once in a project's life, not on every start.
        reset_active_config()
        assert adopted_project_id_note() is None
        assert config.read_text() == written

    def test_a_carrier_it_cannot_append_to_never_stops_the_server(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from openstategraph.cli import adopted_project_id_note
        from openstategraph.config_file import reset_active_config

        config = tmp_path / "pyproject.toml"
        config.write_text("[tool.openstategraph]\nversion = 1\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()

        assert adopted_project_id_note() is None
