"""The editor's copy of the locked prompt layers, pinned to Python's (ticket 38).

`29572f4` collapsed four families' loose prompt constants into one `PROMPT`
ClassVar each. It was **Python-only** — it touched no file under `src/nodes/` —
and the TypeScript half then drifted for five days in three measurable ways:

- `GRADER_DEFAULT_CRITERIA` had three bullets where `BaseGrader` had four. The
  missing one was *"an answer that honestly declines … is a PASS"*, added after
  a live trace in which a correct honest decline was graded FAIL, the retries
  returned empty strings, and the revision loop destroyed the right answer it
  already held.
- `ROUTER_PREAMBLE` was the two-sentence version; `BaseRouter` had a third
  sentence about classifying follow-ups in conversational light.
- TypeScript had no router `default_rules` layer **at all** — the layer that
  exists so a bare Router works out of the box.

## Why a mirror is allowed to exist here, and why it needs this file

CLAUDE.md permits a hand-written mirror of a Python contract *only* when a
drift test pins it: "a new hand-mirror **without** that pin is what this rule
forbids." These constants are the mirror; this is the pin that was never
written.

The mirror earns its place because of *when* the string is needed. It is what
the inspector shows a developer **while they type**, so that they can see what
the machinery already says instead of duplicating or contradicting it — the
locked-sections rule. That has to render with no server necessarily reachable,
so fetching it from `/api/node-contracts` at edit time is not available.

The consequence of the drift is therefore not a wrong run — the run always used
Python's copy. It is worse in a quieter way: **the editor showed the developer a
prompt their workflow was not running.** A grader card promising three rules
while the grader obeyed four is a lie told by the one surface built to prevent
exactly that.

## What is compared

The rendered *text*, not the source spelling. TypeScript wraps these across
several concatenated string literals and Python does not, so the comparison
normalises whitespace runs and the two typographic apostrophes to one form.
Anything stricter would fail on a line-wrap and teach the next person to
delete the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openstategraph.abc.grader import BaseGrader
from openstategraph.abc.router import BaseRouter

SRC = Path(__file__).resolve().parents[2] / "src" / "nodes" / "routing"
ROUTER_TS = SRC / "RouterNode.ts"
GRADER_TS = SRC / "GraderNode.ts"


def _normalise(text: str) -> str:
    """Comparable form: one apostrophe, no line-wrap artefacts, no edge space."""
    return re.sub(r"\s+", " ", text.replace("’", "'")).strip()


def _ts_constant(source: Path, name: str) -> str:
    """The rendered value of an exported string constant in a `.ts` file.

    Handles both shapes these files use: a run of `'…' + '…'` concatenations,
    and an array of string literals joined with `\\n`. Deliberately a small
    reader rather than a parser — if it ever cannot find the constant it raises
    instead of returning `""`, because an extractor that silently matches
    nothing would make every assertion below vacuous.
    """
    text = source.read_text()
    match = re.search(rf"export const {name} =(.*?);\n", text, re.S)
    if not match:
        raise AssertionError(f"{name} not found in {source.name} — has it been renamed?")
    body = match[1]
    literals = re.findall(r"'((?:[^'\\]|\\.)*)'", body)
    if not literals:
        raise AssertionError(f"{name} in {source.name} holds no string literals")
    joiner = "\n" if ".join(" in body else ""
    return joiner.join(literals).replace("\\n", "\n").replace("\\'", "'")


@pytest.mark.parametrize(
    ("source", "constant", "expected"),
    [
        (ROUTER_TS, "ROUTER_PREAMBLE", BaseRouter.PROMPT.preamble),
        (ROUTER_TS, "ROUTER_OUTPUT_CONTRACT", BaseRouter.PROMPT.output_contract),
        (ROUTER_TS, "ROUTER_DEFAULT_RULES", BaseRouter.PROMPT.default_rules),
        (GRADER_TS, "GRADER_DEFAULT_CRITERIA", BaseGrader.PROMPT.default_rules),
        (GRADER_TS, "GRADER_OUTPUT_CONTRACT", BaseGrader.PROMPT.output_contract),
    ],
)
def test_the_editor_shows_what_the_runtime_runs(
    source: Path, constant: str, expected: str
) -> None:
    assert _normalise(_ts_constant(source, constant)) == _normalise(expected), (
        f"{constant} in {source.name} has drifted from its Python source. "
        "The editor shows this string to a developer as the locked layer their "
        "node runs under; if the two disagree, the card is lying. Update the "
        "TypeScript to match Python — Python is the source of truth."
    )


def test_the_extractor_would_notice_a_rename() -> None:
    """The positive control (ticket 47's lesson, applied on the way past).

    Every assertion above compares an extracted string. If `_ts_constant` ever
    silently returned `""` for a renamed constant it would compare `""` to
    `""`-normalised Python and could pass. It raises instead, and this is what
    says so.
    """
    with pytest.raises(AssertionError, match="not found"):
        _ts_constant(ROUTER_TS, "ROUTER_PREAMBLE_THAT_DOES_NOT_EXIST")
