"""`launch-readiness/126` — one question, three answers, and nothing noticing.

## What the ticket reported, and what is left of it

Two questions, each asked three times against an unchanged warehouse. *Persian
Gulf ports*: right, then a refusal offering an invented country set, then a
correct refusal. *Dark vessels* (`116`): 2 / 0 / 0. Every variant delivered with
identical confidence, so a user who asks once cannot know which they got.

Both were diagnosed to named causes and both were fixed — `130`'s merge race
(a concurrent-search merge keyed on arrival) and `131`'s `filter_not_applied`.
Eight runs after those fixes agreed, and the ticket's own audit note says what
survives is cosmetic: *"a column alias and where the `DISTINCT` sits. **Pin the
answer, not the SQL.** A literal-statement pin would be red on a correct run."*

So the defect is closed and the **instrument** is what is missing: nothing
measures whether the same question gives the same answer, so the next
regression of this shape is as invisible as the last one was.

## Why this reports a number instead of passing or failing

The ticket names the trap itself: *"a flaky check that is allowed to stay red
teaches everyone to ignore it."* A run is a full model turn — 40-90 seconds and
real spend — so this can never run on a commit, and a live-model check that is
allowed to go red on a coin flip is worse than no check at all.

So `evaluate(repeat=N)` **reports** an agreement block and gates nothing.
`Scorecard.meets()` is untouched, and `--threshold` still reads
`overall_accuracy` alone. A tracked rate is honest; a green test that only
passes when the coin lands right is not.

## What "agreement" means here, and what it cannot mean

Two answers can be equivalent in different prose, so agreement is not string
equality. It is measured on two axes and they are kept apart:

- **verdicts** — did every repetition grade the same way. Coarse, always
  available, and the one a reader cares about.
- **results** — did every repetition's statement return the same rows,
  compared with the same `result_eq` execution accuracy uses. Immune to the
  alias and `DISTINCT`-position cosmetics the audit note names, which is
  exactly why a statement pin was refused.

A case whose runs executed nothing comparable reports `results_agree: null`,
never `false`. *We could not tell* and *they disagreed* are two situations, and
this map is named after not letting two situations render identically.

## Where the statements come from — `one-chinook-honest/30`

The ticket says comparing the executed SQL *"would be far stronger — which is
blocked on `one-chinook-honest/30`"*. It is unblocked: a run now records what
it executed, so `AskOutcome.statements` carries the statements themselves and
agreement is compared on **what ran** rather than on the model's prose about
what it ran.

`ItemVerdict.sql` and `sql_recovery_rate` deliberately do **not** move. They
measure whether the system *stated* its query — a real property of grading a
product — and reading the record into them would silently turn that metric into
"did anything run a query", which is a different fact under the same name.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.evaluation import AskOutcome, EvalCase, evaluate

from test_evaluation import _tiny_dataset


def _answers(script: dict[str, list[str]]) -> object:
    """An asker that gives a different answer on each repetition of a case."""
    laps: dict[str, int] = {}

    def ask(case: EvalCase) -> AskOutcome:
        index = laps.get(case.id, 0)
        laps[case.id] = index + 1
        replies = script[case.id]
        return AskOutcome(answer=replies[index % len(replies)], outputs={}, seconds=0.1)

    return ask


STABLE = {
    "e01": ["```sql\nSELECT COUNT(*) FROM genre\n```\nThree."],
    "m01": ["```sql\nSELECT name, revenue FROM genre ORDER BY revenue DESC LIMIT 1\n```\nRock."],
    "u01": ["I only answer questions about this music store."],
}


class TestAgreementIsMeasured:
    def test_a_single_pass_reports_no_agreement_block(self, tmp_path: Path, tiny_db: Path) -> None:
        """Absent rather than empty: one run cannot agree or disagree with
        anything, and a block of zeroes would read as *they agreed*."""
        card = evaluate(_tiny_dataset(tmp_path, tiny_db), _answers(STABLE))

        assert card.agreement == {}

    def test_three_identical_runs_disagree_about_nothing(
        self, tmp_path: Path, tiny_db: Path
    ) -> None:
        card = evaluate(_tiny_dataset(tmp_path, tiny_db), _answers(STABLE), repeat=3)

        assert card.agreement["repeat"] == 3
        assert card.agreement["disagreement_rate"] == 0.0
        assert all(case["verdicts_agree"] for case in card.agreement["cases"])

    def test_the_reported_triple_is_caught(self, tmp_path: Path, tiny_db: Path) -> None:
        """The ticket's own shape: right, then a refusal, then a refusal."""
        card = evaluate(
            _tiny_dataset(tmp_path, tiny_db),
            _answers(
                {
                    **STABLE,
                    "e01": [
                        "```sql\nSELECT COUNT(*) FROM genre\n```\nThree.",
                        "I could not find that.",
                        "I could not find that.",
                    ],
                }
            ),
            repeat=3,
        )

        disagreed = [case for case in card.agreement["cases"] if not case["verdicts_agree"]]
        assert [case["case_id"] for case in disagreed] == ["e01"]
        assert disagreed[0]["verdicts"] == ["correct", "no_sql", "no_sql"]
        assert card.agreement["disagreement_rate"] == round(1 / 3, 3)

    def test_every_run_is_actually_made(self, tmp_path: Path, tiny_db: Path) -> None:
        """N times each, not N times over the dataset — the cost is stated in
        `docs/evaluation.md` and must be the cost actually paid."""
        asked: list[str] = []

        def ask(case: EvalCase) -> AskOutcome:
            asked.append(case.id)
            return AskOutcome(answer=STABLE[case.id][0], outputs={}, seconds=0.1)

        evaluate(_tiny_dataset(tmp_path, tiny_db), ask, repeat=3)

        assert sorted(asked) == ["e01"] * 3 + ["m01"] * 3 + ["u01"] * 3


class TestTheCosmeticVarianceIsNotADisagreement:
    """The audit note's whole point, and the reason a statement pin was refused."""

    def test_a_different_alias_and_a_moved_distinct_still_agree(
        self, tmp_path: Path, tiny_db: Path
    ) -> None:
        card = evaluate(
            _tiny_dataset(tmp_path, tiny_db),
            _answers(
                {
                    **STABLE,
                    "e01": [
                        "```sql\nSELECT COUNT(*) AS n FROM genre\n```\nThree.",
                        "```sql\nSELECT COUNT(id) AS total FROM genre\n```\nThree.",
                        "```sql\nSELECT COUNT(*) FROM genre\n```\nThree.",
                    ],
                }
            ),
            repeat=3,
        )

        case = next(c for c in card.agreement["cases"] if c["case_id"] == "e01")
        assert case["verdicts_agree"] is True
        assert case["results_agree"] is True
        assert card.agreement["disagreement_rate"] == 0.0

    def test_two_statements_that_return_different_rows_do_not_agree(
        self, tmp_path: Path, tiny_db: Path
    ) -> None:
        """Same verdict, different rows — which is the *silent* half of this
        ticket: three answers, all confident, all graded the same way."""
        card = evaluate(
            _tiny_dataset(tmp_path, tiny_db),
            _answers(
                {
                    **STABLE,
                    "m01": [
                        "```sql\nSELECT name, revenue FROM genre WHERE name='Rock'\n```",
                        "```sql\nSELECT name, revenue FROM genre WHERE name='Latin'\n```",
                    ],
                }
            ),
            repeat=2,
        )

        case = next(c for c in card.agreement["cases"] if c["case_id"] == "m01")
        assert case["results_agree"] is False
        assert case["distinct_results"] == 2


class TestWhatCouldNotBeToldApart:
    def test_a_case_with_nothing_executable_reports_null_not_false(
        self, tmp_path: Path, tiny_db: Path
    ) -> None:
        """*We could not tell* and *they disagreed* must not render the same."""
        card = evaluate(
            _tiny_dataset(tmp_path, tiny_db),
            _answers({**STABLE, "u01": ["I only answer questions about this music store."]}),
            repeat=2,
        )

        case = next(c for c in card.agreement["cases"] if c["case_id"] == "u01")
        assert case["results_agree"] is None
        assert card.agreement["unmeasurable"] == 1


class TestItComparesWhatRanRatherThanWhatWasSaid:
    """`one-chinook-honest/30`'s record, used for the thing it unblocked."""

    def test_the_recorded_statement_is_preferred_over_the_prose(
        self, tmp_path: Path, tiny_db: Path
    ) -> None:
        """The answers quote the same query; the runs *ran* different ones.
        Prose-only comparison calls that agreement, and it is not."""

        def ask(case: EvalCase) -> AskOutcome:
            if case.id != "e01":
                return AskOutcome(answer=STABLE[case.id][0], outputs={}, seconds=0.1)
            lap = laps.setdefault(case.id, 0)
            laps[case.id] = lap + 1
            ran = "SELECT COUNT(*) FROM genre" if lap == 0 else "SELECT id FROM genre"
            return AskOutcome(
                answer="```sql\nSELECT COUNT(*) FROM genre\n```\nThree.",
                outputs={},
                seconds=0.1,
                statements=[{"node": "a", "tool": "t", "statement": ran, "result": "", "truncated": False}],
            )

        laps: dict[str, int] = {}
        card = evaluate(_tiny_dataset(tmp_path, tiny_db), ask, repeat=2)

        case = next(c for c in card.agreement["cases"] if c["case_id"] == "e01")
        assert case["results_agree"] is False

    def test_the_stated_query_metric_is_left_alone(self, tmp_path: Path, tiny_db: Path) -> None:
        """`sql_recovery_rate` measures whether the system *stated* its query.
        Reading the record into it would rename the fact without saying so."""

        def ask(case: EvalCase) -> AskOutcome:
            return AskOutcome(
                answer="Three.",
                outputs={},
                seconds=0.1,
                statements=[
                    {
                        "node": "a",
                        "tool": "t",
                        "statement": "SELECT COUNT(*) FROM genre",
                        "result": "",
                        "truncated": False,
                    }
                ],
            )

        card = evaluate(_tiny_dataset(tmp_path, tiny_db), ask)

        assert card.sql_recovery_rate == 0.0


class TestNothingIsGatedOnIt:
    def test_a_run_that_disagreed_with_itself_still_meets_its_threshold(
        self, tmp_path: Path, tiny_db: Path
    ) -> None:
        """The trap, as code: this measurement may never turn a build red."""
        card = evaluate(
            _tiny_dataset(tmp_path, tiny_db),
            _answers(
                {
                    **STABLE,
                    "e01": [
                        "```sql\nSELECT COUNT(*) FROM genre\n```",
                        "```sql\nSELECT COUNT(*) FROM genre\n```",
                    ],
                }
            ),
            repeat=2,
        )

        assert card.meets(1.0)

    def test_the_block_survives_the_json_round_trip(self, tmp_path: Path, tiny_db: Path) -> None:
        card = evaluate(_tiny_dataset(tmp_path, tiny_db), _answers(STABLE), repeat=2)

        assert json.loads(json.dumps(card.to_json()))["agreement"]["repeat"] == 2

    def test_the_rendered_card_says_the_rate(self, tmp_path: Path, tiny_db: Path) -> None:
        card = evaluate(_tiny_dataset(tmp_path, tiny_db), _answers(STABLE), repeat=2)

        assert "agreement" in card.render().lower()


class TestARepetitionIsNotAFollowUp:
    """`launch-readiness/12` — the instrument was measuring the conversation.

    `package_asker` gave every case its own thread id so case 12 could not see
    case 11's history. That was written before `--repeat` existed, and the two
    do not compose: with `repeat=2` both laps ran on **the same** thread, so
    lap 2 was not the question asked again — it was the same question asked a
    second time *of an agent that had just answered it*.

    Measured on the shipped `sql-qa` package against a live cloud model: lap 1
    answered with its `SELECT`, lap 2 returned an **empty answer** and no
    statement, so every case graded `no_sql` on the second lap. The card then
    read `agreement 20.0%` beside `overall accuracy 100.0%` on a workflow whose
    two laps, run on independent threads, agree perfectly. A number that
    measures the harness is worse than no number, and this map is named after
    not letting that render as a finding about the product.
    """

    def test_each_repetition_gets_its_own_thread(self, tmp_path: Path) -> None:
        from openstategraph.evaluation.runner import package_asker

        seen: list[str] = []

        class _Door:
            def ask(self, question: str, *, thread_id: str) -> object:
                seen.append(thread_id)
                return _Result()

        class _Result:
            outputs: dict[str, str] = {}
            attempts = 1
            usage: dict[str, object] = {}
            statements: tuple[object, ...] = ()

            def __str__(self) -> str:
                return "an answer"

        case = EvalCase(id="s01", question="how many?", gold_sql="SELECT 1")
        ask = package_asker(_Door())
        ask(case)
        ask(case)

        assert len(set(seen)) == 2, f"both repetitions shared a thread: {seen}"

    def test_two_cases_still_never_share_a_thread(self, tmp_path: Path) -> None:
        """The property the per-case id existed for, kept."""
        from openstategraph.evaluation.runner import package_asker

        seen: list[str] = []

        class _Door:
            def ask(self, question: str, *, thread_id: str) -> object:
                seen.append(thread_id)
                return _Result()

        class _Result:
            outputs: dict[str, str] = {}
            attempts = 1
            usage: dict[str, object] = {}
            statements: tuple[object, ...] = ()

            def __str__(self) -> str:
                return "an answer"

        ask = package_asker(_Door())
        ask(EvalCase(id="s01", question="a?", gold_sql="SELECT 1"))
        ask(EvalCase(id="s02", question="b?", gold_sql="SELECT 1"))

        assert len(set(seen)) == 2
