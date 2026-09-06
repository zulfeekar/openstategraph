"""A node that answered with a fenced code block and nothing else is a
finding, not a clean exit.

**Seen live** (`launch-readiness/35`, the third stranger install run):
`openstategraph run ./workflows/sql-qa "Which artist earned the most
revenue?"`, six times. Five printed the answer and its SQL — "Iron Maiden
earned the most revenue with $138.60." followed by a fenced ```sql block. One
printed **only** the fenced ```sql block: no artist, no figure. Exit code 0,
`"attempts": 1`, `"warnings": []`.

This is a different shape from the one `silent_node_warnings` already
catches. That function's whole premise is `not text.strip()` — a node that
produced *nothing*. Here the node produced plenty of text; none of it was
outside a fenced code block. `sql-qa`'s own `rules` already ask for "answer
the question in one sentence... then state the query" — a package-level
instruction a model can silently skip. The locked output contract
(`AbstractAgentNode.PROMPT.output_contract`, `abc/agent.py`) now forbids this
shape at the source; this function is the second half CLAUDE.md's rule
insists on regardless — "silence is the part that must not survive either
way" — so a run that slips past the prompt fix still says so.

Same channel as `silent_node_warnings` and `forced_pass_warnings`: a report
about how the answer was reached, never a claim the run failed. It is folded
into `RunHealth.silent`, not `RunHealth.failures` — CLAUDE.md's
"a workflow may legitimately answer with nothing at all" applies here too,
were a node's *whole point* to hand back a query (a "write me a SELECT for
this" workflow legitimately answers with only code). This function cannot
tell that case from `sql-qa`'s from the text alone, so it never blocks a run
or changes an exit code — it only stops the run from claiming, silently, that
nothing was worth mentioning.
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import (
    code_fence_only_warnings,
    run_health,
)


class TestACodeFenceWithNoProseIsNamed:
    def test_only_a_fenced_block_is_reported(self) -> None:
        warnings = code_fence_only_warnings(
            {"answer1": "```sql\nSELECT a.Name FROM Artist a\n```"}
        )
        assert len(warnings) == 1
        assert "answer1" in warnings[0]

    def test_leading_and_trailing_whitespace_around_the_fence_still_counts(self) -> None:
        assert code_fence_only_warnings(
            {"answer1": "\n\n```sql\nSELECT 1\n```\n\n"}
        )

    def test_every_such_node_is_named_not_just_the_first(self) -> None:
        warnings = code_fence_only_warnings(
            {
                "a": "```sql\nSELECT 1\n```",
                "b": "```sql\nSELECT 2\n```",
                "c": "Iron Maiden earned the most revenue with $138.60.\n\n```sql\nSELECT 1\n```",
            }
        )
        assert len(warnings) == 2
        assert {"a", "b"} == {w.split('"')[1] for w in warnings}

    def test_it_says_the_answer_looks_like_only_a_query(self) -> None:
        warning = code_fence_only_warnings(
            {"answer1": "```sql\nSELECT a.Name FROM Artist a\n```"}
        )[0]
        assert "fenced code" in warning.lower() or "code block" in warning.lower()


class TestItDoesNotFlagOrdinaryContent:
    def test_prose_before_the_fence_is_left_alone(self) -> None:
        # The five-out-of-six shape: a sentence, then the SQL as evidence.
        assert not code_fence_only_warnings(
            {
                "answer1": (
                    "Iron Maiden earned the most revenue with $138.60.\n\n"
                    "```sql\nSELECT a.Name FROM Artist a\n```"
                )
            }
        )

    def test_prose_after_the_fence_is_left_alone(self) -> None:
        assert not code_fence_only_warnings(
            {"answer1": "```sql\nSELECT a.Name FROM Artist a\n```\n\nThat is Iron Maiden."}
        )

    def test_a_plain_answer_with_no_fence_at_all_is_left_alone(self) -> None:
        assert not code_fence_only_warnings({"answer1": "There are 59 customers."})

    def test_empty_output_is_left_alone_here_silent_node_warnings_owns_that(self) -> None:
        # Not this function's shape — `not text.strip()` is
        # `silent_node_warnings`'s job, and folding it in here would report
        # the same node twice under two different sentences.
        assert not code_fence_only_warnings({"answer1": ""})
        assert not code_fence_only_warnings({"answer1": "   "})

    def test_inline_single_backticks_are_not_a_fence(self) -> None:
        # `SELECT` mentioned in prose, or a single inline `code` span, is not
        # the "only a query" shape this function exists to catch.
        assert not code_fence_only_warnings(
            {"answer1": "Run `sql_query` yourself if you want to check this."}
        )

    def test_a_workflow_whose_whole_point_is_a_snippet_is_not_this_functions_call(self) -> None:
        # Documented in the module docstring: this function cannot tell "the
        # model forgot the answer" from "the workflow's job is to hand back
        # code" from the text alone, so callers that know better (a package
        # that says so explicitly) are not something this module decides —
        # it only ever reports what it sees. Recorded here so a future
        # broadening does not read this test as license to guess intent.
        assert code_fence_only_warnings({"answer1": "```python\nprint('hi')\n```"})


class TestItJoinsTheHealthReport:
    def test_run_health_carries_it_in_silent_never_failures(self) -> None:
        health = run_health({"answer1": "```sql\nSELECT 1\n```"})
        assert health.failures == []
        assert len(health.silent) == 1
        assert "answer1" in health.silent[0]
