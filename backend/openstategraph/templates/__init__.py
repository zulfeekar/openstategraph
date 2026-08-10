"""The scaffold's template catalogue — the one list of starting points.

**Tier 2, provisional** (`docs/stability.md`): importable and documented, may
change in a minor release with a changelog note. The *command line* over it —
`openstategraph new --template <name>` — follows the Tier 1 policy.

**What a template is, and what it is not.** A template is a **scaffold input**:
it produces a `workflow.json` (plus the AGENTS.md that explains it) and then
stops existing. Nothing at runtime, in the canvas, or in a saved document ever
refers back to it. It is emphatically *not* a node type standing beside Team
and Workflow — a document that remembered which template made it would be a
document with a second, invisible owner.

**Why data files rather than Python builders.** A template *is* a workflow.json,
and the person about to own one should be able to read it before they run it —
`openstategraph/templates/routed-qa/workflow.json` is that file, not a function
that returns a dict literal. It costs one substitution pass and buys a
diffable, reviewable, copy-pasteable document. The files sit inside the package
directory, so they are ordinary package data: `pip install openstategraph`
carries them, and `openstategraph new --template routed-qa` works in a
directory that has never seen this repository. `scripts/clean_install_proof.sh`
asserts they are in the built wheel, because nothing in the test suite can.

**Substitution** is deliberately three tokens deep, not a template language:
`{{name}}` (the display name), `{{slug}}` (the frozen package identity) and
whatever a template declares under `defaults` in `index.json` — `{{outcome}}`
for `team`, which `new_team(root, slug, outcome)` has always let a caller
supply. Substitution walks the *parsed* JSON, so a display name containing a
quote cannot corrupt the document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

#: The package-data directory: this module's own, so it moves with the wheel.
#: `__file__` is the right answer here and the wrong one in `workflows_root` —
#: these files really are inside `site-packages`; a user's workflows are not.
DATA = Path(__file__).resolve().parent

#: `minimal` and not `routed-qa`: a stranger's first run must cost one model
#: call and have nothing in it that can reject the answer.
DEFAULT_TEMPLATE = "minimal"


class UnknownTemplateError(ValueError):
    """A template name that is not in the catalogue. The message lists them."""


@dataclass(frozen=True)
class Template:
    """One starting point: a document, an AGENTS.md, and the directories the
    conventions expect to find."""

    name: str
    #: One line, shown by `--list-templates` and by the editor's picker.
    summary: str
    #: Created empty by the scaffold — an empty `tools/` is an invitation.
    directories: tuple[str, ...]
    #: Substitution values this template declares; a caller may override any.
    defaults: Mapping[str, str]

    @property
    def directory(self) -> Path:
        return DATA / self.name

    def document(self, name: str, **overrides: str | None) -> dict[str, Any]:
        """The workflow document, rendered. Never the storage envelope —
        `scaffold` owns that, because publishing state is not a template's
        business."""
        raw = json.loads((self.directory / "workflow.json").read_text())
        rendered = _substitute(raw, self._values(name, overrides))
        assert isinstance(rendered, dict)
        return rendered

    def agents_md(self, name: str, slug: str, **overrides: str | None) -> str:
        """The file a developer opens first."""
        text = (self.directory / "AGENTS.md").read_text()
        rendered = _substitute(text, self._values(name, overrides, slug=slug))
        assert isinstance(rendered, str)
        return rendered

    def _values(
        self, name: str, overrides: Mapping[str, str | None], **extra: str
    ) -> dict[str, str]:
        values = {**self.defaults, "name": name, **extra}
        # `None` is "the caller did not say", not "the empty string" — the CLI
        # passes its optional arguments straight through.
        values.update({k: v for k, v in overrides.items() if v is not None})
        return values


def _substitute(value: Any, values: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for key, replacement in values.items():
            value = value.replace("{{" + key + "}}", replacement)
        return value
    if isinstance(value, list):
        return [_substitute(item, values) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, values) for key, item in value.items()}
    return value


@lru_cache(maxsize=1)
def catalogue() -> tuple[Template, ...]:
    """Every template, in the order they should be offered: cheapest first."""
    index = json.loads((DATA / "index.json").read_text())
    return tuple(
        Template(
            name=entry["name"],
            summary=entry["summary"],
            directories=tuple(entry["directories"]),
            defaults=dict(entry.get("defaults", {})),
        )
        for entry in index["templates"]
    )


def names() -> tuple[str, ...]:
    """The valid `--template` values, in catalogue order."""
    return tuple(template.name for template in catalogue())


def get(name: str) -> Template:
    for template in catalogue():
        if template.name == name:
            return template
    raise UnknownTemplateError(f"unknown template {name!r} — choose from {', '.join(names())}")


__all__ = [
    "DATA",
    "DEFAULT_TEMPLATE",
    "Template",
    "UnknownTemplateError",
    "catalogue",
    "get",
    "names",
]
