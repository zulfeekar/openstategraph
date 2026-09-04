""""What did the work cost" asked of the store instead of of one run.

`stable-beta-public/03`, slice 2 of `docs/plans/token-status-bar/04-slices.md`.
Slice 1 landed the door and the published shape with every figure at its
fresh-install value; this is the query behind it.

**Every fixture is written through `SqliteRunSink`.** Nothing here inserts a
row by hand, and that is the point rather than tidiness: the column this sum
reads (`total_tokens`) is *derived on write* by `_column`, from a mapping keyed
by model, and a hand-written `INSERT` would let a test agree with itself about
a number the product never computes. A fixture that goes through the sink is a
fixture that would notice.

The two answers that are easy to conflate, and are separated here on purpose:

- `usage == {}` is **nobody reported**. It is a run — it happened, it is
  counted in its sitting — and it contributes no tokens and no model row. A
  by-model table with a nameless row in it would be inventing a model.
- A sitting's order is by **instant**, not by the text of `at`
  (`the-cost-of-one-more/11`). The stamps below differ only in offset, so a
  reader that sorted them as text would pass every other assertion in this file
  and fail that one.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.run_sinks import (
    RunRecord,
    SqliteRunSink,
    spend_summary,
)


def write(path: Path, *records: RunRecord) -> Path:
    """A store holding exactly these runs, written the way a run writes them."""
    sink = SqliteRunSink(path)
    for record in records:
        sink.record(record)
    sink.close()
    return path


def run(
    *,
    at: str = "2026-09-04T10:00:00+0000",
    session_id: str = "s-1",
    usage: dict | None = None,
) -> RunRecord:
    return RunRecord(
        kind="run",
        at=at,
        session_id=session_id,
        thread_id="t",
        workflow_slug="w",
        usage=usage or {},
    )


def spent(model: str, *, inp: int, out: int, **details: dict) -> dict:
    """One model's row of `usage`, in LangChain's own `UsageMetadata` shape.

    `details` takes `input_token_details` / `output_token_details` verbatim and
    **omits either when it is not passed** — which is the whole subject of the
    tri-state below. A helper that always wrote `{"cache_read": 0}` would make
    every fixture a provider that reports caching, and the `None` rule would
    have nothing to be tested against.
    """
    row: dict = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
    row.update(details)
    return {model: row}


class TestAStoreWithNothingInIt:
    def test_a_fresh_store_is_zero_not_missing(self, tmp_path: Path) -> None:
        """No file at all — the first thing a fresh install asks.

        A raise here would put an error in the editor's status bar on a
        machine that has simply not run anything yet, which is the ordinary
        state of every install on its first morning.
        """
        summary = spend_summary(tmp_path / "never-written.sqlite")

        assert summary.grand_total == 0
        assert summary.cached_total is None
        assert summary.by_model == ()
        assert summary.sessions == ()
        assert summary.session_by_model == ()
        assert summary.session_total == 0


class TestTheGrandTotal:
    def test_grand_total_sums_every_run_across_sessions(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
            run(session_id="s-1", usage=spent("m", inp=200, out=20)),
            run(session_id="s-2", usage=spent("m", inp=300, out=30)),
        )

        assert spend_summary(store).grand_total == 660

    def test_a_run_that_reported_nothing_counts_zero_tokens_and_one_run(
        self, tmp_path: Path
    ) -> None:
        """*Nobody reported* is not *nothing was spent*, and neither is it *no run*.

        The row is real: it is counted in its sitting, so a person reading the
        sessions list sees the run they remember making. What it may not do is
        add a zero to a model's table, because there is no model to add it to.
        """
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("m", inp=100, out=10)),
            run(usage={}),
        )

        summary = spend_summary(store)

        assert summary.grand_total == 110
        assert [row.model for row in summary.by_model] == ["m"]
        assert summary.by_model[0].runs == 1
        assert summary.sessions[0].runs == 2


class TestTheModels:
    def test_by_model_keeps_two_models_apart(self, tmp_path: Path) -> None:
        """*Which model cost what* is only answerable while they are apart —
        `RunRecord.usage`' own rule, carried through the sum."""
        store = write(
            tmp_path / "runs.sqlite",
            RunRecord(
                kind="run",
                at="2026-09-04T10:00:00+0000",
                session_id="s-1",
                usage={
                    **spent("big", inp=1000, out=100),
                    **spent("small", inp=10, out=1),
                },
            ),
        )

        summary = spend_summary(store)

        assert [row.model for row in summary.by_model] == ["big", "small"]
        assert (summary.by_model[0].input_tokens, summary.by_model[0].output_tokens) == (
            1000,
            100,
        )
        assert summary.by_model[0].total_tokens == 1100
        assert summary.by_model[1].total_tokens == 11

    def test_the_largest_model_is_first(self, tmp_path: Path) -> None:
        """Ordered by what it cost, not by the order it was met in: the bar
        shows the head of this list, and the head should be the answer to
        *what is expensive*."""
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("cheap", inp=1, out=1)),
            run(usage=spent("dear", inp=900, out=90)),
        )

        assert [row.model for row in spend_summary(store).by_model] == ["dear", "cheap"]

    def test_one_model_over_several_runs_is_one_row(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
            run(session_id="s-2", usage=spent("m", inp=200, out=20)),
        )

        summary = spend_summary(store)

        assert len(summary.by_model) == 1
        assert summary.by_model[0].runs == 2
        assert summary.by_model[0].total_tokens == 330



class TestTheThreeDetailsAreThreeValued:
    """Slice 4 of `stable-beta-public/03`: `cache_read`, `cache_creation`,
    `reasoning` — each `int | None`, and the `None` is a claim.

    `0` says *this model was called and none of it came from cache*. `None`
    says *no run for this model carried the key at all*, which is what a
    provider that does not publish the detail — or an OpenAI stream nobody
    opted into usage on — leaves behind. Flattening the second into the first
    is the one thing no later slice could undo: a zero is indistinguishable
    from a measurement, and the bar would print `0` for something nobody
    measured.
    """

    def test_cached_is_none_when_nobody_reported(self, tmp_path: Path) -> None:
        store = write(tmp_path / "runs.sqlite", run(usage=spent("m", inp=1, out=1)))

        summary = spend_summary(store)

        assert summary.by_model[0].cached_tokens is None
        assert summary.by_model[0].cache_creation_tokens is None
        assert summary.by_model[0].reasoning_tokens is None
        assert summary.cached_total is None

    def test_cached_sums_only_rows_that_carry_the_key(self, tmp_path: Path) -> None:
        """100 and *absent* is 100 — never 100 + 0.

        Arithmetically the same answer, and that is exactly why it is asserted
        on the tri-state as well: the run that said nothing must not turn the
        model's `None` into a `0`, and the sum must not become a claim about a
        run that made none.
        """
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("m", inp=100, out=10, input_token_details={"cache_read": 100})),
            run(usage=spent("m", inp=100, out=10)),
        )

        summary = spend_summary(store)

        assert summary.by_model[0].cached_tokens == 100
        assert summary.cached_total == 100
        # The other two keys were on neither row.
        assert summary.by_model[0].cache_creation_tokens is None
        assert summary.by_model[0].reasoning_tokens is None

    def test_a_reported_zero_stays_a_zero(self, tmp_path: Path) -> None:
        """The other side of the same rule, and the one a `or 0` breaks."""
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("m", inp=100, out=10, input_token_details={"cache_read": 0})),
        )

        summary = spend_summary(store)

        assert summary.by_model[0].cached_tokens == 0
        assert summary.by_model[0].cached_tokens is not None
        assert summary.cached_total == 0

    def test_reasoning_and_cache_creation_follow_the_same_none_rule(
        self, tmp_path: Path
    ) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(
                usage=spent(
                    "m",
                    inp=100,
                    out=10,
                    input_token_details={"cache_creation": 7},
                    output_token_details={"reasoning": 40},
                )
            ),
            run(usage=spent("m", inp=100, out=10)),
        )

        row = spend_summary(store).by_model[0]

        assert row.cache_creation_tokens == 7
        assert row.reasoning_tokens == 40
        assert row.cached_tokens is None

    def test_two_models_keep_their_own_answers(self, tmp_path: Path) -> None:
        """One provider reporting a cache figure may not speak for the other."""
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("dear", inp=900, out=90, input_token_details={"cache_read": 500})),
            run(usage=spent("quiet", inp=10, out=1)),
        )

        summary = spend_summary(store)

        by_name = {row.model: row for row in summary.by_model}
        assert by_name["dear"].cached_tokens == 500
        assert by_name["quiet"].cached_tokens is None
        # The grand cache figure is over the models that answered, and the
        # silent one contributes nothing rather than a zero.
        assert summary.cached_total == 500

    def test_the_session_block_reads_the_details_too(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(
                session_id="s-1",
                usage=spent("m", inp=100, out=10, input_token_details={"cache_read": 60}),
            ),
            run(session_id="s-2", usage=spent("m", inp=100, out=10)),
        )

        summary = spend_summary(store, session_id="s-1")

        assert summary.session_by_model[0].cached_tokens == 60

    def test_a_detail_that_is_not_a_number_is_not_a_report(self, tmp_path: Path) -> None:
        """Read tolerantly, trust strictly. A `usage` document is whatever the
        build that wrote it put there, and a string where a count belongs is
        *nobody said* rather than a crash."""
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("m", inp=1, out=1, input_token_details={"cache_read": "lots"})),
        )

        assert spend_summary(store).by_model[0].cached_tokens is None
        assert spend_summary(store).cached_total is None


#: Three sittings, in the order they happened, spelled in three zones — the
#: fixture shape `test_newest_first_is_the_latest_instant.py` arrived at. Read
#: as text the newest sorts last, so a `max(at)` reads this list backwards.
BY_INSTANT: tuple[tuple[str, str], ...] = (
    ("oldest", "2026-10-25T03:10:00+0300"),  # 00:10Z
    ("middle", "2026-10-25T02:50:00+0200"),  # 00:50Z
    ("newest", "2026-10-25T01:30:00+0000"),  # 01:30Z
)


class TestTheSittings:
    def test_the_fixture_is_wrong_under_a_text_sort(self) -> None:
        """The control, so the ordering test below cannot pass vacuously."""
        assert [name for name, _ in sorted(BY_INSTANT, key=lambda p: p[1])] == [
            "newest",
            "middle",
            "oldest",
        ]

    def test_sessions_are_newest_first_by_last_at(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            *(
                run(at=at, session_id=name, usage=spent("m", inp=1, out=1))
                for name, at in BY_INSTANT
            ),
        )

        assert [row.session_id for row in spend_summary(store).sessions] == [
            "newest",
            "middle",
            "oldest",
        ]

    def test_a_sitting_carries_its_span_and_its_count(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(at=BY_INSTANT[0][1], session_id="s", usage=spent("m", inp=1, out=1)),
            run(at=BY_INSTANT[2][1], session_id="s", usage=spent("m", inp=3, out=1)),
        )

        (sitting,) = spend_summary(store).sessions

        assert sitting.runs == 2
        assert sitting.total_tokens == 6
        assert (sitting.first_at, sitting.last_at) == (
            BY_INSTANT[0][1],
            BY_INSTANT[2][1],
        )

    def test_every_sitting_is_listed(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1"),
            run(session_id="s-2"),
            run(session_id=""),
        )

        assert len(spend_summary(store).sessions) == 3


class TestTheAskedAboutSession:
    """Slice 3: `session_by_model` / `session_total`, filtered by `session_id`.

    The all-time table above answers *what has this store ever cost*; this
    one answers *what has this tab cost*, and the two must not leak into each
    other — a session block that quietly summed every session would make the
    bar's "This tab" cell lie the moment a second tab existed.
    """

    def test_session_block_is_only_that_session(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
            run(session_id="s-1", usage=spent("m", inp=50, out=5)),
            run(session_id="s-2", usage=spent("m", inp=900, out=90)),
        )

        summary = spend_summary(store, session_id="s-1")

        assert summary.session_total == 165
        assert [row.model for row in summary.session_by_model] == ["m"]
        assert summary.session_by_model[0].total_tokens == 165
        assert summary.session_by_model[0].runs == 2
        # And the all-time table is untouched by the filter.
        assert summary.grand_total == 1155

    def test_unknown_session_is_empty_not_error(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
        )

        summary = spend_summary(store, session_id="does-not-exist")

        assert summary.session_by_model == ()
        assert summary.session_total == 0
        # Still answers everything else — an unknown session is not a fault.
        assert summary.grand_total == 110

    def test_no_session_id_is_the_same_empty_answer(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
        )

        summary = spend_summary(store, session_id=None)

        assert summary.session_by_model == ()
        assert summary.session_total == 0

    def test_a_session_run_that_reported_nothing_still_counts_its_run(
        self, tmp_path: Path
    ) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
            run(session_id="s-1", usage={}),
        )

        summary = spend_summary(store, session_id="s-1")

        assert summary.session_total == 110
        assert summary.session_by_model[0].runs == 1


class TestAStreamNobodyOptedIntoUsageOn:
    """Where a `None` in the table above actually comes from, in practice.

    Slice 4 of `stable-beta-public/03`. The three details are three-valued
    because a provider can decline to report them — and the commonest way that
    happens is not an exotic vendor, it is **OpenAI while streaming**. The
    chat-completions API returns usage on a streamed response only when the
    caller asks for it (`stream_options.include_usage`, which `langchain_openai`
    spells `stream_usage`); LangChain's own note is explicit that *OpenAI and
    Azure OpenAI chat completions require users opt-in to receiving token usage
    data in streaming contexts* (`/oss/python/langchain/models`, Token usage,
    read 2026-09-04).

    So this is the metering path driven by a stream that carries no
    `usage_metadata` at all, asserting the record it leaves behind is `{}` —
    *nobody said* — and never a row of zeros. A row of zeros would reach
    `spend_summary` as a measurement and the status bar would print `Cached 0`
    for a run nothing measured.

    The opt-in itself is a provider-catalogue fact and is pinned in
    `test_chat_model.py`, beside the other `init_chat_model` keywords: a test
    here could only assert what a fake did.
    """

    def _stream(self, *, reports: bool) -> dict:
        """Drive one streamed model call inside a turn and read the meter."""
        from langchain_core.language_models import BaseChatModel
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        from openstategraph.run_journal import run_turn

        reported = reports

        class StreamedModel(BaseChatModel):
            """A chat model that only streams — the shape of the defect.

            `response_metadata["model_name"]` is on the last chunk and nothing
            else changes between the two cases, so the *only* difference the
            assertions can be reading is the presence of `usage_metadata`.
            """

            @property
            def _llm_type(self) -> str:  # pragma: no cover - LangChain plumbing
                return "streamed-model"

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
                raise NotImplementedError("this model streams")

            def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
                yield ChatGenerationChunk(message=AIMessageChunk(content="Hel"))
                extra = {}
                if reported:
                    extra = {
                        "usage_metadata": {
                            "input_tokens": 11,
                            "output_tokens": 2,
                            "total_tokens": 13,
                            "input_token_details": {"cache_read": 4},
                        }
                    }
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="lo.",
                        response_metadata={"model_name": "gpt-4.1-mini"},
                        **extra,
                    )
                )

        with run_turn(workflow_slug="w", session_id="s-1") as turn:
            list(StreamedModel().stream("hi"))
            return turn.spent()

    def test_an_openai_stream_without_the_usage_opt_in_reads_as_not_reported(self) -> None:
        assert self._stream(reports=False) == {}

    def test_the_same_stream_with_the_opt_in_is_measured(self) -> None:
        """The control. Without it the assertion above passes on a turn that
        never metered anything, which is a different bug wearing the same
        green."""
        spent_ = self._stream(reports=True)

        assert set(spent_) == {"gpt-4.1-mini"}
        assert spent_["gpt-4.1-mini"]["input_token_details"]["cache_read"] == 4

    def test_and_the_store_answers_none_rather_than_zero_for_it(
        self, tmp_path: Path
    ) -> None:
        """The end of the wire: a silent run is a run, and its cache figure is
        a dash rather than a nought."""
        store = write(tmp_path / "runs.sqlite", run(usage=self._stream(reports=False)))

        summary = spend_summary(store)

        assert summary.sessions[0].runs == 1
        assert summary.cached_total is None
        assert summary.by_model == ()
