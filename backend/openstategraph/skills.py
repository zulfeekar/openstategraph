"""What a skill file **is** on disk, and how its text reaches a prompt.

One sentence: a skill is a Markdown file whose body is a rules layer, with
optional YAML frontmatter carrying `name` and `description`.

**This module is the only implementation of that format.** `SkillDocument`
parses it and `SkillDocument.render` writes it, so a reader and a writer cannot
drift apart. Nothing in the editor composes the header: a Skill node emits its
*body* on the wire and carries `name` and `description` as document data, and
frontmatter appears only where a file does (`plugin_interop`'s `SKILL.md`
export). See `docs/decisions/skill-layer.md`.

Two decisions are worth reading before changing anything here.

**The body is the whole prompt contribution.** Everything before the closing
`---` is metadata for humans and pickers; only the body is composed into a
`SystemPrompt`. That is what makes a plain `.md` file with no frontmatter — the
seeded `sql-analyst.md` — a valid skill with nothing added to it, and it is why
picking a real `SKILL.md` off disk no longer drips raw YAML into the model's
system prompt.

**Frontmatter is `name` and `description`, and nothing of ours.** Those two
fields are the Agent Skills specification's own required frontmatter, which
`deepagents` reads at discovery (docs-langchain: *"parses each SKILL.md
frontmatter, and injects the name and description fields into the system
prompt"*). Adopting them costs one parser and buys interop in both directions:
`plugin_interop` exports through `render()` and now *keeps* a description a
file declares, synthesizing one only when there is none — the lossy conversion
it used to do unconditionally existed only because nothing here could read it.

There is deliberately **no `mode:` field**. Whether a skill extends or replaces
the rules beneath it belongs to the *wiring*, not the file: the same skill is an
addendum on one node and a complete persona on another, and a setting readable
from two places is how a developer ends up with a prompt they cannot predict.
The consuming node owns it, once, as `rulesMode`.

Parsed by hand rather than with PyYAML on purpose: this project's four-dependency
floor is deliberate (see `pyproject.toml`), and the specification's
frontmatter is a flat string map — `key: value`, plus YAML's folded `>-` for a
long description. Anything richer is not a skill header.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_FENCE = "---"


def _dquote(value: str) -> str:
    """A YAML double-quoted scalar for `value` — valid regardless of content,
    including an embedded colon (see `SkillDocument.render`)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(value: str) -> str:
    """Inverse of `_dquote` for a double-quoted value; a single-quoted or
    bare value is returned with only its outer quote characters stripped,
    same as before this module double-quoted its own output."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        out: list[str] = []
        i = 0
        while i < len(inner):
            c = inner[i]
            if c == "\\" and i + 1 < len(inner) and inner[i + 1] in ("\\", '"'):
                out.append(inner[i + 1])
                i += 2
                continue
            out.append(c)
            i += 1
        return "".join(out)
    return value.strip("'\"")


@dataclass(frozen=True)
class SkillDocument:
    """One skill file, split into what a picker shows and what a model reads."""

    #: The declared `name`, or the file stem when none is declared.
    name: str
    #: The declared `description` — what a picker shows, and what an agent that
    #: chooses between skills matches against. Empty when undeclared; never
    #: synthesized from the body, because a guessed description read as
    #: authoritative is worse than an absent one.
    description: str
    #: The Markdown after the frontmatter. **This is the only part that reaches
    #: a prompt.**
    body: str

    @classmethod
    def parse(cls, text: str, *, name: str = "") -> SkillDocument:
        front, body = _split_frontmatter(text or "")
        return cls(
            name=front.get("name", "").strip() or name,
            description=front.get("description", "").strip(),
            body=body.strip(),
        )

    def render(self) -> str:
        """The file, written back out — the inverse of `parse`.

        **The one place this format is composed**, and it is here so that no
        second implementation of it can exist. The editor's Skill node used to
        build the same string in TypeScript and ship it over the wire, so the
        format had a reader in Python and a writer in TypeScript, free to
        drift; `plugin_interop` then had a third spelling of the header for its
        `SKILL.md` export. A skill now travels as its **body**, and the header
        is a *disk* format written here, from the identity the document
        already carries.

        `description` is emitted on one line: `parse` folds a wrapped scalar
        into a single space-joined string, so anything else would not survive
        the round trip. An empty description is omitted rather than written
        blank, because a declared-but-empty field reads as authoritative.

        Always double-quoted, never left as a bare plain scalar: a
        description written as an instruction ("MANDATORY: read this
        before...", the shape `launch-readiness/134` recommends) routinely
        carries a colon, and `key: value: rest` is a scanner error to a real
        YAML parser — found live when `deepagents.middleware.skills`
        (`yaml.safe_load`) choked on exactly that shape, silently skipping
        the skill (missing description) rather than raising, which is worse.
        This project's own hand-rolled parser above never cared — it splits
        on the *first* colon only — so the ambiguity was invisible until
        something read the file with real YAML.
        """
        fields = [f"name: {self.name}"]
        description = " ".join(self.description.split())
        if description:
            fields.append(f"description: {_dquote(description)}")
        header = "\n".join(fields)
        return f"{_FENCE}\n{header}\n{_FENCE}\n\n{self.body.strip()}\n"

    @classmethod
    def load(cls, path: Path) -> SkillDocument:
        """Reads `path`, naming the skill after its stem when it declares none.

        An unreadable file is an empty skill, not an exception: a skill is
        additive customisation, and a run that dies because one optional file
        lost its permissions is a worse failure than a run without it.
        """
        try:
            text = path.read_text()
        except OSError:
            text = ""
        return cls.parse(text, name=path.stem)


def skill_text(text: str) -> str:
    """The prompt contribution of raw skill text — frontmatter stripped.

    The one function the compile path calls. A wired skill arrives as a string
    through state (the canvas cannot hand a `Path` across the wire), so the
    parse has to happen on text, not on a file.
    """
    return SkillDocument.parse(text).body


def has_frontmatter(text: str) -> bool:
    """Did this file declare a header? — i.e. is there anything to lose.

    Exists for `plugin_interop`, whose import path flattens a `SKILL.md` to our
    plain `skills/*.md` and has to tell the caller when metadata went with it.
    It used to answer that with a second, subtly different fence parser of its
    own; the answer belongs beside the parser that decides it.
    """
    fields, _ = _split_frontmatter(text or "")
    return bool(fields)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """`(fields, body)`. No frontmatter — the common case — is `({}, text)`."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return {}, text
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == _FENCE)
    except StopIteration:
        # An opening fence with no closing one is not frontmatter — it is a
        # horizontal rule, and eating the rest of the file as metadata would
        # silently produce a skill with no instructions at all.
        return {}, text
    return _parse_fields(lines[1:end]), "\n".join(lines[end + 1 :])


def _parse_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    key = ""
    folded: list[str] = []

    def flush() -> None:
        if key:
            fields[key] = " ".join(folded).strip() if folded else fields.get(key, "")

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line[:1].isspace() and key:
            # A continuation line of a folded (`>-`) or wrapped scalar.
            folded.append(line.strip())
            continue
        flush()
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        folded = []
        if value in (">", ">-", "|", "|-"):
            fields[key] = ""
        else:
            fields[key] = _unquote(value)
    flush()
    return fields


__all__ = ["SkillDocument", "has_frontmatter", "skill_text"]
