"""Measured, no model: whether disclosure actually reaches the packages we
ship, and the actual byte delta when it does.

`launch-readiness/134`. `SkillsMiddleware` requires both `name` and
`description` in a skill's frontmatter and silently skips a file missing
either — so `workflows/workflow-architect/skills/document-grammar.md` and
`interview.md`, which shipped with no frontmatter at all, could never be
disclosed: disclosing the package wholesale would have deleted both from the
prompt with no line saying they exist. Both now declare `name`/`description`.

This file pins two facts with the real `deepagents` disclosure library
(`SkillsMiddleware`, `FilesystemBackend`) — no model, no network call:

1. `workflow-architect`'s skills are disclosed (loaded with no error) and the
   disclosed prompt fragment is materially smaller than the flat
   concatenation `discover_skills()` produces — the saving this ticket
   exists to claim.
2. `concierge`'s single skill stays correctly below the library's own
   break-even (its skills-system-prompt scaffolding costs bytes before a
   single skill is even listed), so disclosure is not a net win there — and
   this test pins that as the **expected**, correct shape, not a defect.

Mirrors, standalone, the projection `deep_tier_offload._project_skills`
performs on the `wt/wire-skills-offload` branch (`<package>/skills/*.md` ->
`<root>/<name>/SKILL.md`) — that function isn't on `main` yet, so this
exercises the same two library entry points (`SkillDocument.render()` +
`SkillsMiddleware`) directly rather than importing it.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("deepagents")

from deepagents.backends import FilesystemBackend  # noqa: E402
from deepagents.middleware.skills import SkillsMiddleware  # noqa: E402
from langchain_core.messages import SystemMessage  # noqa: E402

from openstategraph.api.capability_discovery import discover_skills  # noqa: E402
from openstategraph.skills import SkillDocument  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class _FakeRequest:
    """The minimal `ModelRequest` surface `SkillsMiddleware.modify_request`
    reads/writes: `.state`, `.system_message`, `.override(...)`."""

    def __init__(self, state: dict) -> None:
        self.state = state
        self.system_message = SystemMessage(content="")

    def override(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        return self


def _measure(package_dir: Path) -> tuple[int, int, list[str], list[str]]:
    """`(flat_bytes, disclosed_bytes, disclosed_skill_names, load_errors)`.

    `flat_bytes` is what `discover_skills()` — the compiler's current, only
    path — concatenates into every model call today. `disclosed_bytes` is
    what `SkillsMiddleware`'s own system-prompt fragment costs once the
    package's skills are projected into the layout it expects.
    """
    flat = discover_skills(package_dir)
    flat_bytes = len(flat.encode("utf-8"))

    skills_dir = package_dir / "skills"
    tmp = Path(tempfile.mkdtemp())
    try:
        for path in sorted(skills_dir.glob("*.md")):
            doc = SkillDocument.load(path)
            target = tmp / doc.name
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text(doc.render(), encoding="utf-8")

        backend = FilesystemBackend(root_dir=str(tmp), virtual_mode=True)
        middleware = SkillsMiddleware(backend=backend, sources=["/"])

        state: dict = {}
        update = middleware.before_agent(state, None, {})
        if update:
            state.update(update)

        request = _FakeRequest(state)
        new_request = middleware.modify_request(request)
        disclosed_bytes = len(new_request.system_message.text.encode("utf-8"))

        names = [s["name"] for s in state.get("skills_metadata", [])]
        errors = list(state.get("skills_load_errors", []))
        return flat_bytes, disclosed_bytes, names, errors
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class TestWorkflowArchitectDisclosesBothSkillsNow:
    """The failure this ticket names, made unable to regress: both skills
    load with no error, and the disclosed prompt fragment beats the flat one
    by a wide, stated margin — not just "is smaller"."""

    def test_both_skills_load_with_no_error(self) -> None:
        _, _, names, errors = _measure(_REPO_ROOT / "workflows" / "workflow-architect")
        assert errors == []
        assert set(names) == {"document-grammar", "interview"}

    def test_disclosure_saves_a_material_number_of_bytes_per_call(self) -> None:
        flat_bytes, disclosed_bytes, _, _ = _measure(
            _REPO_ROOT / "workflows" / "workflow-architect"
        )
        assert disclosed_bytes < flat_bytes
        # Loose bound, not the exact measured 2,718 B: pins "materially
        # smaller", the claim this ticket makes, without making the test
        # brittle to a body-copy edit in either skill file.
        assert flat_bytes - disclosed_bytes > 1500


class TestConciergeCorrectlyStaysFlat:
    """`launch-readiness/134`'s "Watch for": concierge's single skill is
    below the library's own disclosure break-even, so disclosure is not a
    win there — and must not be "fixed" by lowering a threshold. Pinned as
    the expected shape, not chased as a regression."""

    def test_disclosure_is_not_smaller_for_the_single_small_skill(self) -> None:
        flat_bytes, disclosed_bytes, names, errors = _measure(
            _REPO_ROOT / "workflows" / "concierge"
        )
        assert errors == []
        assert names  # the skill does load — it just isn't worth disclosing
        assert disclosed_bytes >= flat_bytes
