"""No string a user can reach from `--help` names an internal ticket id.

`docs-onramp/08`. `openstategraph --help` on 0.3.0rc14 printed, on the first
screen a new install shows:

    kanban    attend and advance a kanban-board card (kanban-patrol/19) — ...
    patrol    the in-built patrol — read findings, file new kanban cards
              (kanban-patrol/07)

`kanban-patrol/19` is a file under `.scratch/`, which is gitignored and ships
in no wheel. A reader cannot resolve it, and a reader who tries concludes the
tool is half-finished. The provenance is worth keeping — it stays in a comment
or a docstring beside the string, where a contributor reads it and a user never
does.

## Walked, not listed

The census builds the real parser and recurses its subparsers, because a
hand-picked list of the two somebody already noticed would cover exactly those
two and nothing added tomorrow.

## The other user-facing output

`init`, `open` and `providers` print prose the parser never sees, so the walk
above cannot reach it. That prose is censused too, by reading the module's
source and testing every string literal that is *printed* — the assertion is
deliberately about `print(...)` arguments and the helpers that render them,
since a module-level constant holding a ticket id for a comment's sake is not
user-facing. What is **not** covered, stated rather than implied: a message
assembled from an f-string whose ticket id arrives through a variable. Nothing
in this CLI does that today, and a proxy broad enough to catch it flags every
docstring in the file — which is how a pin acquires a suppression and then
measures nothing.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from openstategraph.cli import build_parser

#: A map name and a number: `kanban-patrol/19`, `docs-onramp/08`.
TICKET_ID = re.compile(r"\b[a-z][a-z-]*[a-z]/\d+\b")


def _parsers(parser: argparse.ArgumentParser) -> list[argparse.ArgumentParser]:
    found = [parser]
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for sub in choices.values():
                if isinstance(sub, argparse.ArgumentParser):
                    found.extend(_parsers(sub))
    return found


def _help_strings(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    where = parser.prog
    strings = [
        (where, text)
        for text in (parser.description, parser.epilog)
        if isinstance(text, str)
    ]
    for action in parser._actions:
        for text in (action.help, getattr(action, "metavar", None)):
            if isinstance(text, str):
                strings.append((f"{where} {action.dest}", text))
        # `add_parser(help=...)` — the line the top-level `--help` prints
        # beside the verb, which is where 08 was found — is stored on the
        # subparsers action as a pseudo-action, not on the child parser.
        for pseudo_action in getattr(action, "_choices_actions", []):
            if isinstance(pseudo_action.help, str):
                strings.append((f"{where} {pseudo_action.dest}", pseudo_action.help))
    return strings


def test_no_help_string_in_the_whole_parser_names_a_ticket() -> None:
    offenders = [
        (where, text, TICKET_ID.search(text).group(0))  # type: ignore[union-attr]
        for parser in _parsers(build_parser())
        for where, text in _help_strings(parser)
        if TICKET_ID.search(text)
    ]
    assert offenders == [], (
        "help text a user sees names an internal ticket id: "
        + "; ".join(f"{where}: {found!r} in {text!r}" for where, text, found in offenders)
    )


def _printed_literals(source: Path) -> list[tuple[int, str]]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    printed: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name not in {"print", "echo", "write"}:
            continue
        for argument in node.args:
            for piece in ast.walk(argument):
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    printed.append((piece.lineno, piece.value))
    return printed


def test_nothing_the_cli_prints_names_a_ticket() -> None:
    import openstategraph.cli as cli_module

    source = Path(cli_module.__file__)
    offenders = [
        (line, text) for line, text in _printed_literals(source) if TICKET_ID.search(text)
    ]
    assert offenders == [], (
        "printed CLI output names an internal ticket id: "
        + "; ".join(f"cli.py:{line}: {text!r}" for line, text in offenders)
    )
