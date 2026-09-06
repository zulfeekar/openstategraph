"""Every ``openstategraph <verb>`` a document prints, held against argparse.

`docs-onramp/07`. `openwiki/quickstart.md` told its reader:

> A package of your own is run with `openstategraph test <package>` rather than
> by the root sweep.

There is no `test` verb and there never has been. A reader who pastes that line
gets a usage error and exit 2, with no way to tell whether the verb was removed
or they mistyped it.

## Why this is a gate and not a typo fix

`docs/cli.md` has been held against the real parser since `production-ready/20`
— which is exactly why its coverage is clean at 20/20 while the sentence above
stood two directories away. **The instrument existed and its corpus was one
page.** Twelve other files name CLI commands in prose, and the command in a
quickstart is the one a stranger copies first.

So the rule is widened rather than the sentence corrected: `README.md`,
`backend/README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, `docs/**` and
`openwiki/**` are swept, and each word is compared with `cli.build_parser()`
rather than with a list written here — the construction rule
`test_no_document_repeats_a_retracted_claim.py` states: derive the fact, never
literalise it.

## What is matched, and what deliberately is not

Only a line that **is** an invocation: the program name is the first token of a
shell code block's line (a `$ ` prompt allowed) or of a backtick span.
`openstategraph` is also a Python package, an install target and a directory,
so `from openstategraph import load_workflow`, `pip install
openstategraph[server]` and `ruff check openstategraph tests` are all ordinary
and none of them is a command anybody can paste. A rule that fired on those
would be a rule with a suppression in its future — forbid distinctive shapes,
never ordinary English.

Two escapes, both narrow:

- **A non-shell fence is skipped by its own info string.** A ```` ```python ````
  block is code in another language that happens to name our package.
- **A negated sentence is the correction, not the claim.** `docs/adoption.md`
  says *"There is no `openstategraph upgrade` command"* on purpose, and a page
  must be able to record a verb that does not exist without asserting it does.
  The same escape hatch, and the same reason, as the past-tense clause in
  `test_no_document_repeats_a_retracted_claim.py`.

The failure prints the file, the line and the word, so the row can be read
where it is printed rather than one `grep` away.

**Subcommands are deliberately out of scope.** `docs/cli.md`'s own pin already
walks the whole tree — every leaf, and every flag in both directions — for the
one page that enumerates them. This file is the shallow, wide half: it asks
only whether the first word after the program name is a command at all, which
is the failure a reader meets as *"invalid choice"*.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from openstategraph import cli

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every hand-written page a reader treats as instructions they can paste.
CORPUS = (
    [
        REPO_ROOT / "README.md",
        REPO_ROOT / "backend" / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "CLAUDE.md",
    ]
    + sorted((REPO_ROOT / "docs").rglob("*.md"))
    + sorted((REPO_ROOT / "openwiki").rglob("*.md"))
)

#: An invocation: the program name first, then the subcommand. A `$ ` prompt
#: and leading whitespace are allowed because that is how shell blocks are
#: written; anything else before it means this is not a command line.
INVOCATION = re.compile(r"^\s*(?:[$>]\s+)?openstategraph\s+([a-z][a-z0-9-]*)")

#: Fence info strings whose contents are shell. A bare ``` counts: this
#: repository writes plain fences for commands throughout.
SHELL_FENCES = frozenset({"", "bash", "sh", "shell", "console", "zsh"})

FENCE = re.compile(r"^\s*```+\s*([A-Za-z0-9_+-]*)")
SPAN = re.compile(r"`([^`\n]+)`")

#: A sentence saying a verb does **not** exist. Narrow on purpose: a page has
#: to be able to record a retired or never-existing command.
NEGATED = re.compile(r"\b(no|not|never|removed|retired|deleted)\b", re.IGNORECASE)


def real_verbs() -> set[str]:
    """The top-level subcommands the real parser accepts."""
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("the CLI parser has no subcommands")


def documented_verbs() -> dict[str, list[tuple[int, str]]]:
    """`{"docs/cli.md": [(41, "run"), …]}` — file, line, word."""
    found: dict[str, list[tuple[int, str]]] = {}
    for page in CORPUS:
        relative = str(page.relative_to(REPO_ROOT))
        fence: str | None = None
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            opening = FENCE.match(line)
            if opening:
                fence = None if fence is not None else opening.group(1).lower()
                continue
            if fence is not None:
                match = INVOCATION.match(line) if fence in SHELL_FENCES else None
                if match:
                    found.setdefault(relative, []).append((number, match.group(1)))
                continue
            if NEGATED.search(line):
                continue
            for span in SPAN.findall(line):
                match = INVOCATION.match(span)
                if match:
                    found.setdefault(relative, []).append((number, match.group(1)))
    return found


def test_the_corpus_was_actually_found() -> None:
    """A sweep over nothing passes. This is the guard that says it swept."""
    assert len(CORPUS) > 20
    assert all(page.is_file() for page in CORPUS)
    assert len(documented_verbs()) > 5, "no page appears to name a command at all"


def test_the_parser_still_has_the_verbs_this_file_compares_against() -> None:
    """Without this, a renamed `build_parser` turns the rule into a no-op."""
    verbs = real_verbs()
    assert len(verbs) >= 20
    assert {"run", "validate", "nodes", "init"} <= verbs


def test_a_documented_verb_is_one_the_parser_accepts() -> None:
    verbs = real_verbs()
    offenders = [
        f"{page}:{number} — `openstategraph {word}`"
        for page, hits in documented_verbs().items()
        for number, word in hits
        if word not in verbs
    ]
    assert not offenders, (
        "these documents print a command the CLI does not accept — a reader "
        "who pastes one gets a usage error and exit 2:\n  "
        + "\n  ".join(sorted(offenders))
    )
