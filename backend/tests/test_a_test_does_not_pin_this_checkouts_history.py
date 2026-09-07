"""No test asserts about a commit only this clone has — `stable-beta-public/35`.

Three tests in `test_ticket_ledger.py` asked the ledger for the subject line of
two real commits of the beta repository and asserted the words. Every clone
that carries those commits agreed, so they were green here for weeks; the first
CI run of the public repository (2026-09-07, run 34065336942, one parentless
commit) was red on exactly those three, in both Python versions, green
everywhere else — `assert '(no such commit here)' == 'Name our ste…'`. A
shallow clone and a fork fail the same way. `stable-beta-public/01` had already
met the symptom and answered it with `fetch-depth: 0` on the backend job, which
bought silence rather than a fix: the tests still tested the checkout.

**A literal sha in code is one of two things**, and this is the census that
keeps them apart:

* a **fixture id** — an opaque token the test made up, which must therefore
  resolve to nothing here (`test_ticket_ledger.py` spells them `f1c71xx`); or
* a **pin on this checkout's history**, which is the defect above.

The two are indistinguishable by reading, and `git cat-file -e` tells them
apart in one call. So: every hex run of 7–40 characters in a string literal
under `backend/tests/` is resolved against this repository, and one that
resolves is refused.

**Prose is exempt and that is the whole reason this passes today.** Forty-seven
test files cite a real sha in a docstring or a comment as provenance — *found
in `a86b4d8`* — and none of them reads history: nothing executes a docstring. A
census that refused those would be red on the day it was written for forty-odd
honest sentences, which is how a pin acquires a suppression and stops measuring
anything. So docstrings are skipped, comments never reach the AST at all, and a
**multi-line** string constant is skipped too: this repository writes its
arguments into block strings (`test_module_size_ceiling.py`'s reason rows cite
`7b81a17c` and `a95dc9f` that way), and a value code passes to something is
never a paragraph.

**The exception, if one is ever needed, is declared in `RECORDED_PINS` below**
— the offending file and sha as the key, the argument as the value, in this
file beside the rule rather than as a comment in the file it excuses. It is
empty, and an empty table is the claim: nothing in `backend/tests/` pins this
history today.

This census needs no history of its own. On a shallow clone `git cat-file -e`
answers *no* for commits that exist upstream, so the worst it can do there is
under-report — it can never fail on a clone for being a clone, which is the
property the tests it polices did not have.
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
TESTS = pathlib.Path(__file__).resolve().parent

#: A hex run long enough for `git` to resolve as an abbreviated commit.
HEX = re.compile(r"\b([0-9a-f]{7,40})\b")

#: Declared exceptions: ``(file name, sha) -> the argument for keeping it``.
#: Ceiling zero. A row here is a promise that the test still passes on a clone
#: that has never seen this repository's history — say why in the value.
RECORDED_PINS: dict[tuple[str, str], str] = {}


def _resolves_here(sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=REPO,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _docstring_nodes(tree: ast.Module) -> set[int]:
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            found.add(id(body[0].value))
    return found


def _executable_strings(source: str) -> list[str]:
    """Every string literal that is neither a docstring nor a block of prose."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        if "\n" in node.value:  # a paragraph, not a value
            continue
        values.append(node.value)
    return values


def _test_files() -> list[pathlib.Path]:
    return sorted(TESTS.glob("*.py"))


def test_the_census_has_files_to_read() -> None:
    """A census that read nothing would pass loudest of all."""
    assert len(_test_files()) > 50


def test_no_test_names_a_commit_this_repository_has() -> None:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("no git checkout here — nothing to resolve shas against")

    offenders: list[str] = []
    for path in _test_files():
        for value in _executable_strings(path.read_text(encoding="utf-8", errors="replace")):
            for sha in HEX.findall(value):
                if (path.name, sha) in RECORDED_PINS:
                    continue
                if _resolves_here(sha):
                    offenders.append(f"{path.name}: {sha}")

    assert offenders == [], (
        "A test names a commit of this checkout as a value: "
        + ", ".join(sorted(set(offenders)))
        + ". A fixture id must resolve to nothing (see test_ticket_ledger.py's"
        " f1c71xx ids); a sentence about a real commit belongs in a docstring or"
        " a comment; anything else needs a row in RECORDED_PINS with its"
        " argument. stable-beta-public/35."
    )


class TestTheCensusItself:
    """The rule has three parts and each one can be wrong on its own."""

    def test_a_sha_in_a_docstring_is_not_a_pin(self) -> None:
        source = '"""Found in f1c71aa, which this file only talks about."""\n'

        assert _executable_strings(source) == []

    def test_a_sha_in_a_block_of_prose_is_not_a_pin(self) -> None:
        source = 'REASON = """\nA row, citing f1c71bb, in an argument nobody executes.\n"""\n'

        assert _executable_strings(source) == []

    def test_a_sha_passed_as_a_value_is_seen(self) -> None:
        source = 'assert commit_subject("f1c71aa") == "something"\n'

        assert "f1c71aa" in _executable_strings(source)

    def test_the_hex_run_must_be_long_enough_to_resolve(self) -> None:
        assert HEX.findall("facade") == []
        assert HEX.findall("deadbee") == ["deadbee"]
