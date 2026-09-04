"""Bundled skills, installed project-locally — `kanban-patrol/24`.

Same idiom `agent_brief.py` already uses for `AGENTS.md`: the wheel carries
the material, a console script the user already runs puts it where their
coding agent looks. The difference here is a skill is a **whole file this
project fully owns** (nobody else writes into `.claude/skills/ticket-forge/
SKILL.md`), so there is no user-content marker to preserve — the state is
simpler: created, refreshed (content differs from what we'd write now), or
current (already byte-identical).

**Two directories, one write each** — different coding agents scan
`.claude/skills/` and `.agents/skills/`, and installing to only one makes the
skill invisible to whichever agent looks elsewhere.
"""

from __future__ import annotations

import re
from pathlib import Path

from openstategraph.bundled_skills import (
    BUNDLED_SKILLS,
    CREATED,
    CURRENT,
    REFRESHED,
    SKILL_ROOTS,
    install_bundled_skills,
)

ROOT = Path(__file__).resolve().parents[2]

#: Every `name:` a `SKILL.md` frontmatter declares, in every directory a
#: coding agent might actually scan for skills — `skills/` (this repository's
#: own, agent-agnostic skills) and the bundled files this module installs.
_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)


def _declared_names() -> dict[str, list[str]]:
    """`{name: [paths]}` for every `SKILL.md` that declares a frontmatter
    `name:` — not every one does (some in `skills/` are a bare heading and no
    frontmatter at all), and a file with no declared name cannot collide with
    one by that mechanism."""
    by_name: dict[str, list[str]] = {}
    sources = [path for path in (ROOT / "skills").glob("*/SKILL.md")]
    sources += list(BUNDLED_SKILLS.values())
    for path in sources:
        match = _NAME.search(path.read_text())
        if not match:
            continue
        by_name.setdefault(match.group(1), []).append(str(path.relative_to(ROOT)))
    return by_name


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
        edited = tmp_path / SKILL_ROOTS[0] / "ticket-forge" / "SKILL.md"
        edited.write_text("someone's local edit")

        results = install_bundled_skills(tmp_path)

        assert results[(SKILL_ROOTS[0], "ticket-forge")] == REFRESHED
        assert edited.read_text() == BUNDLED_SKILLS["ticket-forge"].read_text()


class TestThePatrolSkillStatesTheSelfReferenceTrap:
    """`kanban-patrol/08`. A patrol that reads every recorded thread reads
    the threads its own work produced — and the coding agent following this
    file is the one that produces them, so this file is where it must be told.

    Told is not enough on its own; there is a mechanism (`patrol.py`'s
    `card_session_id`) and this asserts the file hands the agent the marker
    rather than describing the hazard and leaving it there.
    """

    def _skill(self) -> str:
        return BUNDLED_SKILLS["kanban-patrol"].read_text()

    def test_it_tells_the_agent_to_mark_the_runs_it_makes(self) -> None:
        text = self._skill()

        assert "card:<task_id>" in text, (
            "The skill file never gives the agent the marker to set, so every "
            "run it makes while working a card is read back by the next patrol."
        )
        assert "--session-id" in text
        assert "session_id" in text, "the MCP door's argument is not named"

    def test_it_states_the_trap_itself_not_only_the_remedy(self) -> None:
        """A rule with no reason beside it is a rule an agent talks itself
        out of the first time it is inconvenient."""
        text = self._skill().lower()

        assert "its own" in text or "self-reference" in text


class TestNoTwoSkillsShareAName:
    """osg-agent-experience/21. `skills/atom-forge/SKILL.md` (build a new
    module — route, nine-dimension interview, honesty gates) and the bundled
    ticket-authoring sheet were both named `atom-forge`, and `init` installs
    the bundled one straight into `.claude/skills/atom-forge/`, beside the
    checkout's own — so a coding agent standing at this repository's root saw
    one name pointing at two different documents.
    """

    def test_every_declared_skill_name_is_unique(self) -> None:
        by_name = _declared_names()
        collisions = {name: paths for name, paths in by_name.items() if len(paths) > 1}

        assert collisions == {}, (
            f"two or more skill files declare the same name: {collisions}"
        )
