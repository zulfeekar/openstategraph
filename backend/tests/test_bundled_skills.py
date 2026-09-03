"""Bundled skills, installed project-locally — `kanban-patrol/24`.

Same idiom `agent_brief.py` already uses for `AGENTS.md`: the wheel carries
the material, a console script the user already runs puts it where their
coding agent looks. The difference here is a skill is a **whole file this
project fully owns** (nobody else writes into `.claude/skills/atom-forge/
SKILL.md`), so there is no user-content marker to preserve — the state is
simpler: created, refreshed (content differs from what we'd write now), or
current (already byte-identical).

**Two directories, one write each** — different coding agents scan
`.claude/skills/` and `.agents/skills/`, and installing to only one makes the
skill invisible to whichever agent looks elsewhere.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.bundled_skills import (
    BUNDLED_SKILLS,
    CREATED,
    CURRENT,
    REFRESHED,
    SKILL_ROOTS,
    install_bundled_skills,
)


class TestWhatItInstalls:
    def test_both_skills_land_in_both_roots(self, tmp_path: Path) -> None:
        results = install_bundled_skills(tmp_path)

        for root in SKILL_ROOTS:
            for name in BUNDLED_SKILLS:
                assert (tmp_path / root / name / "SKILL.md").is_file()
        assert set(results) == {(root, name) for root in SKILL_ROOTS for name in BUNDLED_SKILLS}

    def test_the_installed_content_matches_the_shipped_file_verbatim(self, tmp_path: Path) -> None:
        install_bundled_skills(tmp_path)

        for name, source in BUNDLED_SKILLS.items():
            installed = (tmp_path / SKILL_ROOTS[0] / name / "SKILL.md").read_text()
            assert installed == source.read_text()

    def test_fresh_install_reports_created(self, tmp_path: Path) -> None:
        results = install_bundled_skills(tmp_path)

        assert all(state == CREATED for state in results.values())


class TestIdempotency:
    def test_a_second_install_with_nothing_changed_reports_current(self, tmp_path: Path) -> None:
        install_bundled_skills(tmp_path)

        results = install_bundled_skills(tmp_path)

        assert all(state == CURRENT for state in results.values())
        # And it must not have rewritten the file — same rule `agent_brief`'s
        # own idempotency test holds: a current block costs nothing to check.

    def test_a_hand_edited_skill_file_is_refreshed_not_merged(self, tmp_path: Path) -> None:
        """Unlike `AGENTS.md`, a skill file has no user-content marker — the
        whole file is this project's, so a local edit is simply overwritten
        on the next install, reported honestly as `refreshed` rather than
        silently kept or silently clobbered without saying so."""
        install_bundled_skills(tmp_path)
        edited = tmp_path / SKILL_ROOTS[0] / "atom-forge" / "SKILL.md"
        edited.write_text("someone's local edit")

        results = install_bundled_skills(tmp_path)

        assert results[(SKILL_ROOTS[0], "atom-forge")] == REFRESHED
        assert edited.read_text() == BUNDLED_SKILLS["atom-forge"].read_text()
