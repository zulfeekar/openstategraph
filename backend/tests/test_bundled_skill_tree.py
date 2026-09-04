"""`init` installs skill *directories*, and reports every file it wrote.

`osg-agent-experience/25`, slice 1. Until now the wheel carried two flat
`*_skill.md` files and the installer copied each to one `SKILL.md`. The entry
sheet a developer actually meets — `openstategraph` — has reference pages
beside it (slice 5), so the unit the installer moves is a **tree**, and the
three-state report (`created` / `refreshed` / `current`) is now per *file*
rather than per skill. A skill whose `SKILL.md` is current and whose reference
page is stale is a real state, and a per-skill report cannot say it.

`test_bundled_skills.py` keeps the behavioural rules that did not change
(both roots, verbatim content, a hand edit is refreshed and said so). This
file owns the tree: three skills, one home, and every sheet parseable by the
one parser this project has for the format (`skills.SkillDocument`).
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.bundled_skills import (
    BUNDLED_SKILLS,
    CREATED,
    CURRENT,
    SKILL_ROOTS,
    install_bundled_skills,
)
from openstategraph.skills import SkillDocument

EXPECTED = {"openstategraph", "ticket-forge", "kanban-patrol"}


class TestOneHome:
    def test_the_three_skills_are_directories_of_package_data(self) -> None:
        assert set(BUNDLED_SKILLS) == EXPECTED
        for name, source in BUNDLED_SKILLS.items():
            assert source.is_dir(), f"{name} is not a directory of package data"
            assert (source / "SKILL.md").is_file(), f"{name} carries no SKILL.md"

    def test_they_all_live_under_one_folder(self) -> None:
        """One home, one installer. Two of these were flat files beside
        `bundled_skills.py` and the third would have had nowhere to put its
        reference pages."""
        parents = {source.parent for source in BUNDLED_SKILLS.values()}

        assert len(parents) == 1, f"the bundled skills are scattered across {parents}"

    def test_every_sheet_parses_with_a_name_and_a_description(self) -> None:
        """The two fields the Agent Skills specification requires, read by the
        one parser this project has for the format — so a sheet that would be
        silently skipped by an agent's own YAML reader fails here instead."""
        for name, source in BUNDLED_SKILLS.items():
            document = SkillDocument.parse((source / "SKILL.md").read_text(encoding="utf-8"))

            assert document.name == name, f"{name}'s frontmatter declares {document.name!r}"
            assert document.description, f"{name} declares no description"
            assert document.body.strip(), f"{name} has no body"


class TestWhatInitWrites:
    def test_every_file_of_every_skill_lands_in_both_roots(self, tmp_path: Path) -> None:
        install_bundled_skills(tmp_path)

        for root in SKILL_ROOTS:
            for name, source in BUNDLED_SKILLS.items():
                for shipped in sorted(source.rglob("*.md")):
                    relative = shipped.relative_to(source.parent)
                    installed = tmp_path / root / relative
                    assert installed.is_file(), f"{relative} never reached {root}"
                    assert installed.read_text(encoding="utf-8") == shipped.read_text(
                        encoding="utf-8"
                    )

    def test_the_report_names_every_file_not_every_skill(self, tmp_path: Path) -> None:
        """The change of shape, asserted rather than described: a key is a
        file, so a stale reference page can be reported beside a current
        sheet."""
        results = install_bundled_skills(tmp_path)

        shipped = {
            (root, str(path.relative_to(source.parent)))
            for root in SKILL_ROOTS
            for source in BUNDLED_SKILLS.values()
            for path in source.rglob("*.md")
        }
        assert set(results) == shipped
        assert all(state == CREATED for state in results.values())

    def test_a_second_install_reports_current_for_every_file(self, tmp_path: Path) -> None:
        install_bundled_skills(tmp_path)

        results = install_bundled_skills(tmp_path)

        assert all(state == CURRENT for state in results.values())
