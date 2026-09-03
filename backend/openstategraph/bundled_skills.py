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

**What ships here, and why only these two.** `atom-forge` and `kanban-patrol`
are OpenStateGraph's own, original text — nothing here is a third party's
skill with a credit note attached. A credit note does not grant permission to
redistribute someone else's unlicensed work, and crediting an influence is a
different act from copying it (`kanban-patrol/24`'s own resolution says why).
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: Package data, beside this module, exactly like `agent_brief.py`'s `BRIEF`.
BUNDLED_SKILLS: dict[str, Path] = {
    "atom-forge": _HERE / "atom_forge_skill.md",
    "kanban-patrol": _HERE / "kanban_patrol_skill.md",
}

#: Both directories a coding agent might scan. Order matters only for the
#: fixture-facing "first one" in tests — no reader depends on which comes
#: first in this project's own runtime.
SKILL_ROOTS: tuple[str, ...] = (".claude/skills", ".agents/skills")

CREATED = "created"
REFRESHED = "refreshed"
CURRENT = "current"


def install_bundled_skills(directory: Path | str) -> dict[tuple[str, str], str]:
    """Write every bundled skill into every root under `directory`.

    Returns `{(root, skill_name): state}` for all of them, so a caller (the
    `init` command's own report) can print one true sentence per file rather
    than a single claim standing in for several different outcomes.
    """
    target = Path(directory)
    results: dict[tuple[str, str], str] = {}
    for root in SKILL_ROOTS:
        for name, source in BUNDLED_SKILLS.items():
            dest = target / root / name / "SKILL.md"
            content = source.read_text(encoding="utf-8")
            if not dest.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                results[(root, name)] = CREATED
                continue
            if dest.read_text(encoding="utf-8") == content:
                results[(root, name)] = CURRENT
                continue
            dest.write_text(content, encoding="utf-8")
            results[(root, name)] = REFRESHED
    return results


__all__ = [
    "BUNDLED_SKILLS",
    "CREATED",
    "CURRENT",
    "REFRESHED",
    "SKILL_ROOTS",
    "install_bundled_skills",
]
