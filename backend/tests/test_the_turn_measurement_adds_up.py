"""The arithmetic behind `109`'s answer, pinned so it cannot drift silently.

`launch-readiness/109` asked how much of a turn is model latency we chose and
how much is ours. The answer — 97–99 % chosen, `ours` 0.11–0.14 s warm, of
which the schedulable part is 0.04–0.06 s — is in
`docs/decisions/where-a-turn-goes.md`, and `scripts/measure_turn.py` is the
instrument that produced it.

The instrument needs a live model, so nothing here re-runs a turn. What it
pins is the **arithmetic**, which is where a conclusion of this kind actually
rots: the difference between summing overlapping intervals and merging them is
the difference between "our overhead is four hundredths of a second" and "our
overhead is negative", and a future edit that quietly swapped one for the
other would keep producing numbers and stop producing an answer.

Three properties, and each is load-bearing for a sentence in that document:

- **Overlap is merged, never summed** — because a fan-out runs several calls
  at once, and the whole point of `ours = wall − |providers|` is that the
  right-hand side cannot exceed the turn.
- **`head + gaps + tail` is exactly `ours`** — the three-way split is a
  decomposition, so a second that goes missing between them is a second
  credited to nobody.
- **The clock says which clock it is.** `launch-readiness/180` means a real
  stream's frames arrive unstamped after the first, so the instrument falls
  back to arrival time; it must keep *saying* so rather than presenting a
  fallback as the server-side frame clock.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "measure_turn.py"


@pytest.fixture(scope="module")
def measure() -> Any:
    """The instrument, imported by path — it is a script, not a package."""
    spec = importlib.util.spec_from_file_location("osg_measure_turn", INSTRUMENT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _spans(measure: Any, *intervals: tuple[float, float], kind: str = "model") -> list[Any]:
    made = []
    for start, end in intervals:
        span = measure.Span(kind, "m", start)
        span.end = end
        made.append(span)
    return made


class TestOverlapIsMergedRatherThanSummed:
    def test_two_calls_at_the_same_moment_cost_one_call_of_wall_clock(
        self, measure: Any
    ) -> None:
        """A fan-out that runs two two-second calls together spent two seconds
        of the turn, not four. Summing here is what would drive `ours`
        negative and make the whole measurement unbelievable."""
        together = _spans(measure, (10.0, 12.0), (10.0, 12.0))
        assert measure._merged(together) == pytest.approx(2.0)

    def test_calls_that_merely_touch_are_one_stretch(self, measure: Any) -> None:
        assert measure._merged(
            _spans(measure, (0.0, 1.0), (1.0, 2.0))
        ) == pytest.approx(2.0)

    def test_a_true_gap_between_calls_is_not_counted_as_busy(
        self, measure: Any
    ) -> None:
        """The gap is the bucket this ticket exists to size. It must survive
        the merge, or the instrument can only ever report that we are fast."""
        assert measure._merged(
            _spans(measure, (0.0, 1.0), (3.0, 4.0))
        ) == pytest.approx(2.0)

    def test_a_call_wholly_inside_another_adds_nothing(self, measure: Any) -> None:
        assert measure._merged(
            _spans(measure, (0.0, 10.0), (2.0, 3.0))
        ) == pytest.approx(10.0)

    def test_no_calls_at_all_is_no_busy_time(self, measure: Any) -> None:
        assert measure._merged([]) == 0.0


class TestTheThreeWaySplitIsADecomposition:
    def test_head_gaps_and_tail_are_exactly_the_ours_bucket(
        self, measure: Any
    ) -> None:
        """`ours = wall − |providers|`, and the split explains all of it.
        A second that belongs to none of the three is a second the report
        would lose without saying so."""
        origin, wall = 100.0, 20.0
        spans = _spans(
            measure,
            (102.0, 105.0),  # head 2.0
            (104.0, 106.0),  # overlaps the first
            (108.0, 112.0),  # gap of 2.0
        )
        ours = wall - measure._merged(spans)
        head, gaps, tail = (value for _, value in measure._ours_breakdown(spans, origin, wall))
        assert head == pytest.approx(2.0)
        assert gaps == pytest.approx(2.0)
        assert tail == pytest.approx(8.0)
        assert head + gaps + tail == pytest.approx(ours)

    def test_a_turn_that_called_nothing_is_entirely_ours(self, measure: Any) -> None:
        head, gaps, tail = (value for _, value in measure._ours_breakdown([], 0.0, 3.0))
        assert (head, gaps) == (0.0, 0.0)
        assert tail == pytest.approx(3.0)


class TestTheReportNamesItsClock:
    def _update(self, node: str, arrived: float, elapsed: int | None) -> dict[str, Any]:
        frame: dict[str, Any] = {"event": "update", "node": node, "arrivedS": arrived}
        if elapsed is not None:
            frame["elapsedMs"] = elapsed
        return frame

    def test_a_fully_stamped_stream_is_read_from_the_frame_clock(
        self, measure: Any
    ) -> None:
        spans, clock = measure._node_spans(
            [self._update("in1", 9.0, 100), self._update("agent1", 9.0, 2100)]
        )
        assert "frame clock" in clock
        assert spans == [("in1", 0.0, 0.1), ("agent1", 0.1, 2.1)]

    def test_the_stream_we_actually_get_falls_back_and_says_so(
        self, measure: Any
    ) -> None:
        """`launch-readiness/180`: over a real socket only the first frame is
        stamped. The fallback is legitimate; presenting it as the server-side
        clock would not be."""
        spans, clock = measure._node_spans(
            [self._update("in1", 0.07, 4), self._update("agent1", 2.1, None)]
        )
        assert "client arrival" in clock and "1/2" in clock
        assert spans == [("in1", 0.0, 0.07), ("agent1", 0.07, 2.1)]

    def test_a_mounted_workflow_is_not_timed_twice(self, measure: Any) -> None:
        """A mount's insides arrive as frames of their own. They belong to the
        mount's segment, not beside it."""
        inner = self._update("child", 1.0, 1000)
        inner["namespace"] = ["audit:1"]
        spans, _clock = measure._node_spans(
            [self._update("audit", 2.0, 2000), inner, self._update("out1", 2.5, 2500)]
        )
        assert [node for node, _s, _e in spans] == ["audit", "out1"]
