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
