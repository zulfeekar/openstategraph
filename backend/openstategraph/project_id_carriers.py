"""One writer per config carrier, each of which knows how to add
`project_id` without destroying the rest of somebody else's file.

team-board-and-gap-reports/01. `project_id` is committed in the project's
config, and until this module the only writer was a YAML append
(`kanban-patrol/23`). That append was correct and stays: a column-0 key at end
of file is a valid top-level mapping key whatever precedes it, so nothing above
it is parsed, re-ordered or de-commented. What was wrong is that it was the
*only* writer, while `config_file.py` documents **four** carriers —
`openstategraph.yaml`, `.yml`, `.json`, and `pyproject.toml
[tool.openstategraph]`. On the other two, `adopt_project_id` refused, so
`project_id_for_board()` raised and the board could not file a card at all,
permanently, on a configuration the docs invite.

## Why one writer each rather than one clever writer

The refusal `kanban-patrol/23` argued for was right about the mechanism —
appending a YAML line to a TOML or JSON file is corruption — and wrong only in
concluding there was nothing else to do. "Add a key" has a different safe edit
per format, and each of these functions is that format's edit and nothing else:

- **YAML** — append at column 0, at end of file.
- **JSON** — insert the pair immediately after the opening brace. JSON has no
  comments to lose, but it does have an author's layout, and a
  `json.dumps` round-trip would reflow the whole document to add one key.
- **TOML** — insert the key on the line after the `[tool.openstategraph]`
  header. `tomllib` **reads only** (there is no TOML writer in the standard
  library and this package will not take a dependency for one key), so this is
  a textual insertion into a located table, never a re-serialisation.

## What each writer refuses, and why refusing is the feature

A writer that cannot make its exact insertion **raises and writes nothing**.
It never falls back to rewriting the file from a parsed structure, because that
is the corruption the original refusal existed to prevent, dressed up as a
success. Refused by name, with the key spelled out for a hand edit:

- a top-level JSON document that is not an object (there is nowhere to put a
  key);
- a JSON file that does not parse (this code does not own it, and guessing
  where the brace is in a broken file is guessing);
- a `pyproject.toml` whose table is written as an inline value under `[tool]`
  (`openstategraph = {version = 1}`) or as a dotted key: the same table to a
  reader, and a different file to a writer — there is no header line to insert
  under, and a line inserted anyway would land in `[tool]` itself;
- a `pyproject.toml` that does not parse, or whose table is missing entirely;
- any suffix with no writer at all.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from openstategraph.project_identity import ProjectIdentityError

#: The provenance comment every carrier that can hold one writes above the key.
#: One sentence, one owner — JSON is the carrier that cannot take it, and that
#: is a property of JSON rather than a second policy.
_COMMENT_BODY = (
    "project_id — added by openstategraph on {today} for the patrol board "
    "(kanban-patrol/03); a copy of this file into another project must not keep it"
)

_YAML_KEY = re.compile(r"^project_id\s*:", re.MULTILINE)

#: `[tool.openstategraph]` on a line of its own, which is the only form this
#: module can insert under. Whitespace and a trailing comment are allowed;
#: an inline table or a dotted key is not this pattern and is refused.
_PYPROJECT_HEADER = re.compile(
    r"^[ \t]*\[[ \t]*tool[ \t]*\.[ \t]*openstategraph[ \t]*\][ \t]*(#.*)?$",
    re.MULTILINE,
)


def _comment(prefix: str) -> str:
    return f"{prefix} {_COMMENT_BODY.format(today=date.today().isoformat())}\n"


def _refuse(config_path: Path, because: str) -> ProjectIdentityError:
    return ProjectIdentityError(
        f"cannot add project_id to {config_path.name} — {because}. "
        "Add `project_id` to it by hand and re-run."
    )


# --- YAML -------------------------------------------------------------------


def _read_yaml(config_path: Path, text: str) -> str | None:
    found = _YAML_KEY.search(text)
    if found is None:
        return None
    value = text[found.end() :].splitlines()[0].strip().strip("\"'")
    return value or None


def _write_yaml(config_path: Path, text: str, project_id: str) -> str:
    # Exactly one newline between the last line somebody wrote and ours,
    # whether or not their file ended with one: a config that already ends in
    # a newline must not grow a blank line every time this runs.
    if text and not text.endswith("\n"):
        text += "\n"
    return text + _comment("#") + f"project_id: {project_id}\n"


# --- JSON -------------------------------------------------------------------


def _json_document(config_path: Path, text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _refuse(config_path, f"it is not valid JSON (line {exc.lineno}: {exc.msg})") from exc
    if not isinstance(data, dict):
        raise _refuse(config_path, "its top level is not an object, so it has nowhere to hold a key")
    return data


def _read_json(config_path: Path, text: str) -> str | None:
    value = _json_document(config_path, text).get("project_id")
    return value if isinstance(value, str) and value else None


def _write_json(config_path: Path, text: str, project_id: str) -> str:
    document = _json_document(config_path, text)
    pair = json.dumps({"project_id": project_id})[1:-1]
    if not document:
        # Nothing to preserve, so nothing is preserved by hand: an empty object
        # has no layout an author chose.
        return "{\n  " + pair + "\n}\n"
    brace = text.index("{")
    indent = _first_key_indent(text[brace + 1 :])
    return f"{text[:brace + 1]}\n{indent}{pair},{text[brace + 1:]}"


def _first_key_indent(rest: str) -> str:
    """The indentation the author already uses for a top-level key, so the
    inserted pair lines up with its neighbours rather than with a default."""
    for line in rest.splitlines():
        if line.strip():
            return line[: len(line) - len(line.lstrip())] or "  "
    return "  "


# --- pyproject.toml ---------------------------------------------------------


def _pyproject_table(config_path: Path, text: str) -> dict[str, Any] | None:
    import tomllib

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _refuse(config_path, f"it is not valid TOML ({exc})") from exc
    table = data.get("tool", {}).get("openstategraph") if isinstance(data, dict) else None
    return table if isinstance(table, dict) else None


def _read_pyproject(config_path: Path, text: str) -> str | None:
    table = _pyproject_table(config_path, text)
    value = table.get("project_id") if table is not None else None
    return value if isinstance(value, str) and value else None


def _write_pyproject(config_path: Path, text: str, project_id: str) -> str:
    if _pyproject_table(config_path, text) is None:
        raise _refuse(config_path, "it has no [tool.openstategraph] table to put a key in")
    header = _PYPROJECT_HEADER.search(text)
    if header is None:
        raise _refuse(
            config_path,
            "its [tool.openstategraph] is written as an inline value or a dotted key, "
            "so there is no table header to insert under and this will not guess",
        )
    # `tomllib` reads only, so this is an insertion rather than a dump: the key
    # goes on the line directly after the header, which is inside that table
    # and before any other, whatever the table already holds.
    cut = header.end()
    return f"{text[:cut]}\n{_comment('#')}project_id = {json.dumps(project_id)}{text[cut:]}"


# --- the seam ---------------------------------------------------------------

#: A carrier's two halves: read the key this file already holds, and return
#: the text it should hold with the key added.
_Reader = Callable[[Path, str], "str | None"]
_Writer = Callable[[Path, str, str], str]

#: Suffix to its pair of functions. A dict rather than a `Registry` on purpose:
#: this is the fixed set of carriers `config_file.CONFIG_FILENAMES` and
#: `PYPROJECT_FILENAME` name, not an extension point — a fifth carrier is a
#: change to what this project reads, and it must be made in both places at
#: once.
_CARRIERS: dict[str, tuple[_Reader, _Writer]] = {
    ".yaml": (_read_yaml, _write_yaml),
    ".yml": (_read_yaml, _write_yaml),
    ".json": (_read_json, _write_json),
    ".toml": (_read_pyproject, _write_pyproject),
}


def read_project_id(config_path: Path) -> str | None:
    """The `project_id` this carrier already holds, or `None`.

    Read through the carrier's own format, never through one regex over four
    formats: `project_id = "x"` in a TOML file and `"project_id": "x"` in a
    JSON one are the same field and not the same text.
    """
    reader = _carrier(config_path)[0]
    return reader(config_path, config_path.read_text())


def write_project_id(config_path: Path, project_id: str) -> None:
    """Add `project_id` to an existing config, preserving everything else.

    Writes the file once, or raises `ProjectIdentityError` and writes nothing.
    Never called for a config that already carries the key — that is
    `adopt_project_id`'s only-add-never-replace rule, and it is checked there
    so every carrier inherits it.
    """
    writer = _carrier(config_path)[1]
    text = config_path.read_text()
    config_path.write_text(writer(config_path, text, project_id))


def _carrier(config_path: Path) -> tuple[_Reader, _Writer]:
    carrier = _CARRIERS.get(config_path.suffix.lower())
    if carrier is None:
        raise _refuse(
            config_path,
            "openstategraph does not read that file as a config, so it will not write to it",
        )
    return carrier
