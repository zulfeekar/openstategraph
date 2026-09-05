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

    def test_a_carrier_with_no_writer_at_all_is_refused_by_name(self, tmp_path: Path) -> None:
        """The refusal survives `team-board-and-gap-reports/01`; what changed
        is which files reach it. A `.ini` is not a carrier this project reads
        or writes, so it is named rather than guessed at."""
        import pytest

        from openstategraph.project_identity import ProjectIdentityError, adopt_project_id

        config = tmp_path / "openstategraph.ini"
        config.write_text("[openstategraph]\nversion = 1\n")

        with pytest.raises(ProjectIdentityError) as exc:
            adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert "openstategraph.ini" in str(exc.value)


class TestEveryCarrierCanBeGivenAnId:
    """team-board-and-gap-reports/01. `project_id` is committed in
    `openstategraph.yaml`, and until this ticket the only writer was a YAML
    append — so a project whose carrier is `openstategraph.json` or
    `pyproject.toml [tool.openstategraph]` could never be given an id at all
    and `project_id_for_board()` raised on it, permanently.

    One writer per carrier, each of which knows how to add the key without
    destroying the rest of the file: append for YAML, an exact insertion for
    JSON and for the `[tool.openstategraph]` table. Where a file's own shape
    makes that impossible the writer refuses **by name** — it never rewrites a
    file it cannot preserve.
    """

    JSON_CONFIG = (
        "{\n"
        '  "version": 1,\n'
        '  "workflows_dir": "workflows",\n'
        '  "providers": [\n'
        '    {"id": "ollama", "enabled": true}\n'
        "  ]\n"
        "}\n"
    )

    PYPROJECT = (
        "[project]\n"
        'name = "their-project"\n'
        'version = "0.1.0"\n'
        "\n"
        "# our openstategraph settings, hand ordered\n"
        "[tool.openstategraph]\n"
        "version = 1\n"
        'workflows_dir = "workflows"\n'
        "\n"
        "[tool.ruff]\n"
        "line-length = 100\n"
    )

    def test_a_yml_config_is_appended_to_like_its_yaml_sibling(self, tmp_path: Path) -> None:
        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "openstategraph.yml"
        config.write_text("version: 1\n")

        result = adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert result.state is ProjectIdentityState.MINTED
        assert config.read_text().endswith(f"project_id: {result.project_id}\n")

    def test_a_json_config_keeps_every_other_key_and_its_own_layout(self, tmp_path: Path) -> None:
        import json

        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "openstategraph.json"
        config.write_text(self.JSON_CONFIG)
        before = json.loads(self.JSON_CONFIG)

        result = adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        text = config.read_text()
        assert result.state is ProjectIdentityState.MINTED
        after = json.loads(text)
        assert after.pop("project_id") == result.project_id
        assert after == before
        # An exact insertion, not a re-serialisation: every line somebody else
        # wrote is still in the file, byte for byte.
        for line in self.JSON_CONFIG.splitlines()[1:]:
            assert line in text.splitlines()
        assert (tmp_path / ".openstategraph" / "project_identity").read_text().strip() == result.project_id

    def test_a_pyproject_table_gains_one_key_and_nothing_else_moves(self, tmp_path: Path) -> None:
        import tomllib

        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "pyproject.toml"
        config.write_text(self.PYPROJECT)
        before = tomllib.loads(self.PYPROJECT)

        result = adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        text = config.read_text()
        assert result.state is ProjectIdentityState.MINTED
        after = tomllib.loads(text)
        assert after["tool"]["openstategraph"].pop("project_id") == result.project_id
        assert after == before
        for line in self.PYPROJECT.splitlines():
            assert line in text.splitlines()
        # The key lands inside the table it belongs to, never in a later one.
        lines = text.splitlines()
        assert lines.index(f'project_id = "{result.project_id}"') < lines.index("[tool.ruff]")
        assert "# project_id — added by openstategraph on " in text

    def test_an_id_already_in_a_json_config_survives_untouched(self, tmp_path: Path) -> None:
        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "openstategraph.json"
        original = '{"version": 1, "project_id": "already-there"}\n'
        config.write_text(original)

        result = adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert config.read_text() == original
        assert result.project_id == "already-there"
        assert result.state is not ProjectIdentityState.MINTED

    def test_an_id_already_in_a_pyproject_table_survives_untouched(self, tmp_path: Path) -> None:
        from openstategraph.project_identity import adopt_project_id

        config = tmp_path / "pyproject.toml"
        original = '[tool.openstategraph]\nversion = 1\nproject_id = "already-there"\n'
        config.write_text(original)

        result = adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert config.read_text() == original
        assert result.project_id == "already-there"
        assert result.state is not ProjectIdentityState.MINTED

    def test_a_pyproject_whose_table_is_an_inline_value_is_refused_by_name(
        self, tmp_path: Path
    ) -> None:
        """`openstategraph = {version = 1}` under `[tool]` is the same table
        to a reader and a different file to a writer: there is no header line
        to insert under, and an inserted line would land in `[tool]` itself.
        Refused, with the file named and the edit spelled out."""
        import pytest

        from openstategraph.project_identity import ProjectIdentityError, adopt_project_id

        config = tmp_path / "pyproject.toml"
        original = "[tool]\nopenstategraph = {version = 1}\n"
        config.write_text(original)

        with pytest.raises(ProjectIdentityError) as exc:
            adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert "pyproject.toml" in str(exc.value)
        assert "project_id" in str(exc.value)
        assert config.read_text() == original

    def test_a_json_config_that_is_not_an_object_is_refused_by_name(self, tmp_path: Path) -> None:
        import pytest

        from openstategraph.project_identity import ProjectIdentityError, adopt_project_id

        config = tmp_path / "openstategraph.json"
        original = "[1, 2, 3]\n"
        config.write_text(original)

        with pytest.raises(ProjectIdentityError) as exc:
            adopt_project_id(config_path=config, state_dir=tmp_path / ".openstategraph")

        assert "openstategraph.json" in str(exc.value)
        assert config.read_text() == original

    def test_the_board_resolves_an_id_on_all_four_carriers(self, tmp_path: Path, monkeypatch) -> None:
        """The symptom this ticket was filed for: `project_id_for_board()`
        raised `ProjectIdentityError` on two of the four carriers, so the
        board could not file a card there at all."""
        from openstategraph.config_file import reset_active_config
        from openstategraph.project_identity import project_id_for_board

        carriers = {
            "openstategraph.yaml": "version: 1\n",
            "openstategraph.yml": "version: 1\n",
            "openstategraph.json": '{"version": 1}\n',
            "pyproject.toml": "[tool.openstategraph]\nversion = 1\n",
        }
        seen = set()
        for name, body in carriers.items():
            home = tmp_path / name.replace(".", "-")
            home.mkdir()
            config = home / name
            config.write_text(body)
            monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
            reset_active_config()

            project_id = project_id_for_board()

            assert project_id
            seen.add(project_id)
            # Read back through the config loader, not just the writer.
            reset_active_config()
            assert project_id_for_board() == project_id
        assert len(seen) == 4


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

    def test_a_pyproject_project_is_adopted_now_rather_than_skipped(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Until `team-board-and-gap-reports/01` this door asserted the
        opposite — a `pyproject.toml` project got no note, because it could get
        no id. It gets both now, through the same one function."""
        from openstategraph.cli import adopted_project_id_note
        from openstategraph.config_file import reset_active_config

        config = tmp_path / "pyproject.toml"
        config.write_text("[tool.openstategraph]\nversion = 1\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()

        note = adopted_project_id_note()

        assert note is not None
        assert note.split()[1] in config.read_text()

    def test_a_carrier_it_cannot_write_to_never_stops_the_server(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A refusal is still a refusal — it is just rarer. An inline
        `[tool]` table has no header to insert under, and the door swallows
        that rather than refusing to start."""
        from openstategraph.cli import adopted_project_id_note
        from openstategraph.config_file import reset_active_config

        config = tmp_path / "pyproject.toml"
        original = "[tool]\nopenstategraph = {version = 1}\n"
        config.write_text(original)
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()

        assert adopted_project_id_note() is None
        assert config.read_text() == original
