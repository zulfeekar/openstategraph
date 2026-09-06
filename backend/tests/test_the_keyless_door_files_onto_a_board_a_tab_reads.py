"""One board id, three spellings, and a test that reads all three —
`team-board-and-gap-reports/17`.

`09` (the keyless door) and `04` (the team tab) were built in the same hour.
`04` fixed the boards a card can be on — `kanban_store.BOARD_IDS`, which
`GET /api/kanban/cards` refuses anything outside of **by name** — and `09`
wrote its cards onto `gap-reports`, which is not one of them. Both were
internally consistent; together they put the first live report in a row no tab
lists and no API call can return, and the answer to "can I see it?" was no.

So the fix is not a corrected literal. A corrected literal is the same defect
with a later date on it: three files would still each carry their own copy of
one word. What this asserts is that there is **one** source and two
publications of it —

- `kanban_store.TEAM_BOARD`, the Python constant `04` already made the boards'
  one vocabulary;
- `supabase/functions/gap-report/contract.generated.ts`, emitted from it by
  `scripts/generate_gap_report_ts.py`, because the door is a Deno function and
  cannot import a Python module;
- the `board` column's default in the migrations, which is what the routine
  actually writes.

The third cannot read either of the first two — SQL imports nothing — so the
pin is what makes the three one fact rather than three. That is the same
answer `test_the_shared_board_has_a_reviewable_schema.py` gives for the check
constraints, and for the same stated reason: a file `supabase db push` sends
must be the bytes we applied.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from openstategraph.gap_report import GAP_CARD_CATEGORY
from openstategraph.kanban_postgres import migration_files
from openstategraph.kanban_store import BOARD_IDS, TEAM_BOARD

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    REPO_ROOT / "supabase" / "functions" / "gap-report" / "contract.generated.ts"
)
DOOR_PATH = REPO_ROOT / "supabase" / "functions" / "gap-report" / "index.ts"

#: The board rows were filed onto before this ticket. Named here because two
#: assertions below are about its *absence*, and an absence written as a bare
#: string in three places is the defect this file is about.
ORPHAN_BOARD = "gap-reports"


def migration_sql() -> str:
    """Every migration, in the order both appliers apply them, comments out.

    Commentary stripped for the reason the sibling census strips it: these
    files argue for themselves at length, and a paragraph naming the old board
    would fail an assertion it agrees with.
    """
    lines: list[str] = []
    for path in migration_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            lines.append(line.split("--", 1)[0].rstrip())
    return "\n".join(lines)


def contract() -> dict[str, object]:
    """The generated contract, read as the JSON it is.

    The file is TypeScript with one `export const` in it, so the object
    between the first `{` and the last `}` is the whole of it.
    """
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    body = text[text.index("{") : text.rindex("}") + 1]
    return json.loads(body)


def board_default() -> str:
    """The `board` column's default, as the migrations leave it."""
    defaults = re.findall(
        r"alter column board set default '([^']+)'", migration_sql(), re.IGNORECASE
    )
    assert defaults, "no migration sets the board column's default"
    return defaults[-1]


class TestTheThreeSpellingsAreOne:
    def test_the_generated_contract_carries_the_python_constant(self) -> None:
        assert contract()["board"] == TEAM_BOARD
        assert contract()["category"] == GAP_CARD_CATEGORY

    def test_the_column_default_is_the_same_word(self) -> None:
        assert board_default() == TEAM_BOARD

    def test_the_contract_is_what_the_generator_produces(self) -> None:
        """`--check` rather than a second rendering here: the generator is the
        one implementation, and a test that re-derives the file would be a
        second one to keep in step."""
        assert (
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "generate_gap_report_ts.py"),
                    "--check",
                ],
                capture_output=True,
            ).returncode
            == 0
        )


class TestTheDoorFilesWhereATabCanReadIt:
    def test_the_board_it_files_onto_is_one_a_tab_lists(self) -> None:
        assert board_default() in BOARD_IDS

    def test_no_statement_still_writes_the_boardless_board(self) -> None:
        """The routine is replaced rather than corrected in place, so the
        assertion is about the *last* definition: `0003`'s body is history the
        migration files keep, and history is not what runs."""
        definitions = re.findall(
            r"create or replace function public\.file_gap_report\b.*?\n\$\$;",
            migration_sql(),
            re.DOTALL,
        )
        assert len(definitions) >= 2, "0006 does not replace the routine"
        assert f"'{ORPHAN_BOARD}'" not in definitions[-1]

    def test_the_rows_already_filed_are_moved_rather_than_left(self) -> None:
        """A default fixes the next card and says nothing about the one the
        owner already asked to see."""
        sql = " ".join(migration_sql().split())
        assert (
            f"update public.cards set board = '{TEAM_BOARD}' "
            f"where board = '{ORPHAN_BOARD}'" in sql
        )

    def test_the_category_says_what_the_card_is(self) -> None:
        """The board picks the tab; the category says what the card is. Both
        are the routine's, and the second is `07`'s report kind collapsed to
        the word every other gap card on this board already carries."""
        definitions = re.findall(
            r"create or replace function public\.file_gap_report\b.*?\n\$\$;",
            migration_sql(),
            re.DOTALL,
        )
        assert f"'{GAP_CARD_CATEGORY}'" in definitions[-1]

    def test_the_door_names_the_board_from_the_contract(self) -> None:
        """The door does not *choose* the board — the routine is the single
        writer, and `0003`'s argument for that (one transaction, one round
        trip) is untouched. What it must not do is name it in its own
        language: a log line saying `gap-reports` while the row says
        `osgEngineering` is how this ticket's hour was spent."""
        door = DOOR_PATH.read_text(encoding="utf-8")
        assert "CONTRACT.board" in door
        assert f'"{ORPHAN_BOARD}"' not in door
