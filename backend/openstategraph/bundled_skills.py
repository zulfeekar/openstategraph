"""Skills the wheel carries, installed project-locally — `kanban-patrol/24`.

Same split `agent_brief.py` already uses: a wheel cannot write into a user's
repository by itself (no install hooks, by PEP 427's own design — see that
module's docstring), so the distribution carries the material and a console
script the user already runs (`openstategraph .`) puts it where a coding
agent looks.

**A skill file is different from `AGENTS.md` in one way that simplifies
this.** `AGENTS.md` is a document a user may also write in themselves, so it
needs marked blocks to protect their own notes. A skill file under
`.claude/skills/<name>/SKILL.md` is not shared with anything else — nobody
else has a reason to write there — so the whole file is ours, and the state
machine is simpler: `created` (nothing was there), `refreshed` (something was
there and it does not match what we ship now), `current` (already
byte-identical, nothing written).

**Two directories, not one.** Different coding agents scan `.claude/skills/`
and `.agents/skills/` for the same thing; installing to only one leaves the
skill invisible to whichever agent looks at the other.

**What ships here, and why only these two.** `ticket-forge` and
`kanban-patrol` are OpenStateGraph's own, original text — nothing here is a
third party's skill with a credit note attached. A credit note does not grant
permission to redistribute someone else's unlicensed work, and crediting an
influence is a different act from copying it (`kanban-patrol/24`'s own
resolution says why).

`ticket-forge` was named `atom-forge` until `osg-agent-experience/21`: this
checkout's own `skills/atom-forge/` (build a new module — route, a
nine-dimension interview, honesty gates) is a completely different document,
and `init` installing the bundled one under the same name put both under one
name in any project that also carries the repo skill — including this one.

**A skill is a directory, and the report is per file** —
`osg-agent-experience/25`. The two sheets above were flat `*_skill.md` files
beside this module and the installer copied each to one `SKILL.md`; the entry
sheet a developer actually meets (`openstategraph`) carries reference pages
beside it, so the unit that moves is a tree. That makes `refreshed` a
per-*file* state, which it has to be: a sheet that is current beside a
reference page that is stale is a real outcome, and a per-skill report has no
word for it.

The folder is `agent_skills/` rather than `skills/`, and that is forced
rather than chosen: `openstategraph/skills.py` already exists — the parser
for the file format these documents are written in — and a package cannot
hold a module and a directory of the same name.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: One home for all of them, beside this module — package data exactly like
#: `agent_brief.py`'s `BRIEF`. Each value is the skill's **directory**: a
#: `SKILL.md` and, from slice 5 of `osg-agent-experience/25`, a `references/`
#: folder beside it.
SKILLS_ROOT: Path = _HERE / "agent_skills"

BUNDLED_SKILLS: dict[str, Path] = {
    "openstategraph": SKILLS_ROOT / "openstategraph",
    "ticket-forge": SKILLS_ROOT / "ticket-forge",
    "kanban-patrol": SKILLS_ROOT / "kanban-patrol",
}

#: Both directories a coding agent might scan. Order matters only for the
#: fixture-facing "first one" in tests — no reader depends on which comes
#: first in this project's own runtime.
SKILL_ROOTS: tuple[str, ...] = (".claude/skills", ".agents/skills")

#: The rules file the MCP server's `get_engineering_rules` serves — package
#: data beside this module, not inside a skill directory, because it has two
#: consumers.
ENGINEERING_RULES: Path = _HERE / "engineering_rules.md"

#: Where the installer writes a copy of it, relative to a skill root.
#:
#: **Generated, never committed a second time.** An agent holding the MCP door
#: calls `get_engineering_rules`; an agent holding only the command line has no
#: such call — there is no `openstategraph rules` verb, and adding one would be
#: a second door onto a file the wheel already carries for a caller who can
#: simply read it. So the sheet's own `references/` gets the text, copied at
#: install time from the one file. A hand-written page here would be a second
#: copy of the rules with nothing pinning the two together, which is precisely
#: the duplication-of-knowledge defect those rules forbid.
RULES_REFERENCE: str = "openstategraph/references/engineering-rules.md"

CREATED = "created"
REFRESHED = "refreshed"
CURRENT = "current"


def bundled_skill_files() -> dict[tuple[str, str], Path]:
    """`{(skill_name, relative_path): source}` for every file the wheel ships.

    The relative path is rooted at `agent_skills/`, so it already carries the
    skill's own directory name — `openstategraph/SKILL.md`,
    `openstategraph/references/interview.md`. That is the path the installer
    writes under each root, and the key the report is stated in.
    """
    files: dict[tuple[str, str], Path] = {}
    for name, source in BUNDLED_SKILLS.items():
        for path in sorted(source.rglob("*.md")):
            files[(name, str(path.relative_to(source.parent)))] = path
    files[("openstategraph", RULES_REFERENCE)] = ENGINEERING_RULES
    return files


def install_bundled_skills(directory: Path | str) -> dict[tuple[str, str], str]:
    """Write every file of every bundled skill into every root under `directory`.

    Returns `{(root, relative_path): state}` for all of them, so a caller (the
    `init` command's own report) can print one true sentence per file rather
    than a single claim standing in for several different outcomes. The key is
    a *file* and not a skill for the reason the module docstring gives: a
    current sheet beside a stale reference page is a state a per-skill report
    cannot express.
    """
    target = Path(directory)
    results: dict[tuple[str, str], str] = {}
    sources = bundled_skill_files()
    for root in SKILL_ROOTS:
        for (_name, relative), source in sources.items():
            dest = target / root / relative
            content = source.read_text(encoding="utf-8")
            if not dest.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                results[(root, relative)] = CREATED
                continue
            if dest.read_text(encoding="utf-8") == content:
                results[(root, relative)] = CURRENT
                continue
            dest.write_text(content, encoding="utf-8")
            results[(root, relative)] = REFRESHED
    return results


__all__ = [
    "BUNDLED_SKILLS",
    "ENGINEERING_RULES",
    "RULES_REFERENCE",
    "SKILLS_ROOT",
    "bundled_skill_files",
    "CREATED",
    "CURRENT",
    "REFRESHED",
    "SKILL_ROOTS",
    "install_bundled_skills",
]
