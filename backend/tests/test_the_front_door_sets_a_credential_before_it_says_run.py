"""`README.md` must set a credential before it tells anyone to press Run.

`docs-onramp/02`. Followed literally from a fresh TestPyPI install of
`0.3.0rc14` on 2026-09-05, README § *First run* was three commands and an
instruction — `mkdir`, `init .`, `openstategraph .`, *"Press **Run**."* — and
**Run did not run**. Three `POST /api/runs/stream` answered 503; the editor's
banner and the CLI both printed the one line the product actually has for it:

    the only provider integration installed; set OLLAMA_API_KEY or
    OLLAMA_HOST to use it

Reproduced for this ticket in the same install: `openstategraph run
workflows/starter "hello"` exits 1 with that line and nothing else. With
`OLLAMA_API_KEY` exported and nothing else changed, the same command answers in
2.1 seconds.

**The information was never missing from README — it was misplaced.** One
clause at line 58, one mention at line 86 inside a paragraph about what `init`
deliberately does *not* write, and the variable table at line **470**: the fact
arrived 337 lines after the instruction that needed it, by which point the
reader had already pressed the button and been refused.

So this file pins **ordering, not presence**. Presence had been true all along
and did not help, which is the whole finding. A test asserting that
`OLLAMA_API_KEY` appears somewhere on the page would have passed on the 829-line
README that produced the 503.

## What counts as each end of the ordering

- **The credential step** is a line that tells a reader to *set* a credential —
  an assignment they can paste (`OLLAMA_API_KEY=…`) or one of the two commands
  that exist for exactly this (`openstategraph env-example`, `openstategraph
  providers`). A bare mention of `.env` does **not** count, and that exclusion
  is the ticket's finding rather than a technicality: the restructured page
  names `.env` in the `init` table, in a row about a file `init` deliberately
  does not write, three lines above *"Press **Run**"*. A test that accepted it
  would have gone green over the defect.
- **The Run instruction** is the first place the page tells someone to run
  something that costs a model call: *"Press **Run**"* or a pasteable
  `openstategraph run`.

Both are searched over the whole file, so moving either one across the other
fails whichever way the edit goes.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"

#: An instruction to set a credential, not a mention of one.
CREDENTIAL_STEP = re.compile(
    r"openstategraph env-example|openstategraph providers|[A-Z_]*API_KEY=",
)

#: The first thing on the page that costs a model call.
RUN_INSTRUCTION = re.compile(r"Press \*\*Run\*\*|openstategraph run\b")

#: Named in the credential step so the reader recognises the refusal when the
#: product prints it. The wording is the product's, not the page's.
REFUSAL_WORDS = "set `OLLAMA_API_KEY` or `OLLAMA_HOST` to use it"


def first_line_matching(pattern: re.Pattern[str]) -> int:
    for number, line in enumerate(README.read_text(encoding="utf-8").splitlines(), start=1):
        if pattern.search(line):
            return number
    raise AssertionError(f"README.md matches {pattern.pattern!r} nowhere at all")


def test_the_readme_was_actually_found() -> None:
    assert README.is_file() and len(README.read_text(encoding="utf-8")) > 5_000


def test_the_credential_step_comes_before_the_run_instruction() -> None:
    credential = first_line_matching(CREDENTIAL_STEP)
    run = first_line_matching(RUN_INSTRUCTION)
    assert credential < run, (
        f"README.md says how to run (line {run}) before it says to set a "
        f"credential (line {credential}). A reader who follows the page in order "
        "presses Run, gets a 503 and the provider refusal, and has been given no "
        "reason to expect it — which is exactly what a fresh install did on "
        "2026-09-05."
    )


def test_the_credential_step_names_the_commands_that_already_exist() -> None:
    """Two verbs answer this question and neither was on the front page."""
    text = README.read_text(encoding="utf-8")
    for command in ("openstategraph env-example", "openstategraph providers"):
        assert command in text, (
            f"`{command}` prints exactly what a stranger stuck on the credential "
            "wall needs, and the front door does not name it"
        )


def test_the_page_says_what_happens_if_you_skip_it() -> None:
    """In the product's own words, so the refusal is recognisable on sight."""
    assert REFUSAL_WORDS in README.read_text(encoding="utf-8"), (
        "the credential step must quote the line the run actually prints when "
        "there is no credential; a warning the reader cannot match to the error "
        "they get is a warning they will not connect to it"
    )
