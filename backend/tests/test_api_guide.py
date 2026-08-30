"""`docs/api.md` — the page a stranger builds a client from.

Scale-and-adopt ticket 05. Two things here are load-bearing enough to be
tested rather than trusted:

**The SSE vocabulary.** It is the part OpenAPI cannot carry, so it is the part
a custom client gets wrong. The event names are read from the code, not
retyped here — adding a seventh event name and forgetting the guide is
exactly the failure this catches.

**The pasteable example.** It lives in `docs/examples/minimal-client.html` as
a real file (so it can be opened, run and reviewed) and appears in the guide
verbatim. One of the two going stale is a reader pasting something that does
not work, so the guide's fenced block is compared byte for byte.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from openstategraph.api.catalogue_events import CATALOGUE_EVENT
from openstategraph.api.streaming import FRAME_FIELDS, RUN_EVENTS, TERMINAL_EVENTS

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "docs" / "api.md"
EXAMPLE = REPO / "docs" / "examples" / "minimal-client.html"


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


class TestTheStreamVocabularyIsDocumented:
    @pytest.mark.parametrize("event", RUN_EVENTS)
    def test_each_run_event_is_named(self, guide: str, event: str) -> None:
        assert f"`{event}`" in guide, (
            f"The run stream emits `{event}` and the guide never mentions it."
        )

    def test_the_terminal_frames_are_called_terminal(self, guide: str) -> None:
        # The guarantee, not just the names: a client must know that exactly
        # one of these three ends the stream, and that anything else means
        # keep waiting.
        assert "terminal" in guide.lower()
        for event in TERMINAL_EVENTS:
            assert f"`{event}`" in guide

    def test_the_catalogue_event_is_named(self, guide: str) -> None:
        assert f"`{CATALOGUE_EVENT}`" in guide

    def test_the_active_node_hint_is_documented(self, guide: str) -> None:
        # The field both surfaces read instead of guessing which node is
        # running. A custom client that misses it re-invents the guess.
        assert "`activeNode`" in guide


class TestTheFiveCalls:
    @pytest.mark.parametrize(
        "call",
        [
            "GET /api/workflows?surface=chat",
            "GET /api/workflows/{slug}",
            "POST /api/runs/stream",
            "POST /api/runs/resume",
            "GET /api/workflows/{slug}/graph",
        ],
    )
    def test_it_is_shown(self, guide: str, call: str) -> None:
        assert call in guide


class TestThePasteableExample:
    def test_the_file_exists(self) -> None:
        assert EXAMPLE.is_file()

    def test_the_guide_embeds_it_verbatim(self, guide: str) -> None:
        assert EXAMPLE.read_text(encoding="utf-8").strip() in guide, (
            f"{EXAMPLE} and its copy in {GUIDE} have drifted."
        )

    def test_it_stays_short_enough_to_read(self) -> None:
        # The promise is "about forty lines you can paste", not an app.
        assert len(EXAMPLE.read_text(encoding="utf-8").splitlines()) <= 60


class TestTheGuideIsReachable:
    @pytest.mark.parametrize(
        ("page", "link"),
        [
            # The index inside docs/ links relatively; everything outside it
            # links by repository path.
            ("docs/README.md", "(api.md)"),
            ("README.md", "docs/api.md"),
            ("site/index.html", "docs/api.md"),
        ],
    )
    def test_it_is_linked_from(self, page: str, link: str) -> None:
        assert link in (REPO / page).read_text(encoding="utf-8")


class TestTheContractItselfIsExplained:
    def test_the_openapi_snapshot_is_named(self, guide: str) -> None:
        assert "docs/openapi.json" in guide
        assert "/openapi.json" in guide

    def test_cors_is_stated(self, guide: str) -> None:
        assert "CORS" in guide
        assert "OPENSTATEGRAPH_ALLOWED_ORIGINS" in guide

    def test_the_typed_client_decision_is_recorded(self, guide: str) -> None:
        assert "openapi-typescript" in guide


#: The fields a frame carries **only sometimes**, with the condition each one
#: rides on, read off the emitters in `api/streaming.py`. Everything else in
#: `FRAME_FIELDS` is on every frame of its kind, which is what lets the example
#: check below ask for a whole frame rather than a plausible one.
#:
#: Small on purpose, and asserted to be a real subset below: a name added here
#: buys an example the right to omit a field, so this list growing is the way
#: this gate would be quietly turned off.
CONDITIONAL_FIELDS: dict[str, frozenset[str]] = {
    # A grader's own frame, when a deterministic check rejected the candidate
    # before any model was invoked — `streaming.py` `_grader_check_payload`.
    "update": frozenset({"check", "reason"}),
    # Rides only a frame that was emptied for a customer.
    "token": frozenset({"withheld"}),
    "invoked": frozenset({"withheld"}),
    # `verdict` and `reason` only when a grader produced the candidate;
    # `check` only when that verdict cost no model call.
    "interrupt": frozenset({"verdict", "reason", "check"}),
    # Only a developer run gets the developer channel.
    "done": frozenset({"developer"}),
}

#: How an example says *"fields are missing here on purpose"*: a bare ellipsis
#: where a key would go, at the end of the object. An ellipsis inside a string
#: value — `"agent1:d03d731c-…"` — elides a *value* and is not this, which is
#: the distinction that stops the marker being earned by accident.
_ABBREVIATIONS = (", ...}", ", …}")


@dataclass(frozen=True)
class Example:
    """One fenced `event:` / `data:` block on the page."""

    event: str
    payload: dict[str, object]
    abbreviated: bool
    line: int


def _examples(guide: str) -> list[Example]:
    """Every SSE frame the page shows, parsed.

    Blocks whose `data:` is not a JSON object are skipped — the framing
    illustration at the top of §2 is `data: <one line of JSON>`, a shape rather
    than a frame, and reading it as one would be the false firing this gate
    cannot afford.
    """
    found: list[Example] = []
    lines = guide.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("event: ") or index + 1 >= len(lines):
            continue
        if not lines[index + 1].startswith("data: "):
            continue
        event = line[len("event: ") :].strip()
        body = [lines[index + 1][len("data: ") :]]
        for follower in lines[index + 2 :]:
            if not follower[:1].isspace() or not follower.strip():
                break
            body.append(follower)
        text = " ".join(part.strip() for part in body)
        if not text.startswith("{"):
            continue
        abbreviated = any(mark in text for mark in _ABBREVIATIONS)
        for mark in _ABBREVIATIONS:
            text = text.replace(mark, "}")
        try:
            payload = json.loads(text)
        except ValueError as exc:  # pragma: no cover - a malformed example is the failure
            raise AssertionError(
                f"{GUIDE}:{index + 1} — the `{event}` example is not one line of "
                f"JSON, which is what §2 promises every frame is: {exc}"
            ) from exc
        found.append(Example(event, payload, abbreviated, index + 1))
    return found


class TestTheFrameTableCarriesEveryField:
    """The level below the names, which is where the drift was.

    `RUN_EVENTS` was pinned and the ~40 field names inside those frames were
    not, so `redactions` and `detail` reached the wire while the page kept
    describing the frame without them. The names are enumerable on both sides,
    so this is the same shape `test_documented_cli_surface.py` uses.
    """

    @staticmethod
    def _table(guide: str) -> list[str]:
        """The frame table's rows, and only that table's.

        Scoped rather than searched page-wide, because `| `error` |` is also a
        row of the `outcome` table further down — and the two mean different
        things, which is the sort of collision this repository keeps paying
        for.
        """
        lines = guide.splitlines()
        header = lines.index("| Event | Meaning | Payload |")
        rows = []
        for line in lines[header + 2 :]:
            if not line.startswith("| `"):
                break
            rows.append(line)
        return rows

    @classmethod
    def _row(cls, guide: str, event: str) -> str:
        prefix = f"| `{event}` |"
        rows = [line for line in cls._table(guide) if line.startswith(prefix)]
        assert len(rows) == 1, (
            f"The frame table has {len(rows)} rows for `{event}`; it needs "
            "exactly one, because that row is the contract for that frame."
        )
        return rows[0]

    def test_the_table_has_a_row_per_frame_and_no_others(self, guide: str) -> None:
        listed = [line.split("`")[1] for line in self._table(guide)]
        # Set equality, not order: the page groups `invoked` beside `spawn`
        # because that is how a reader meets them, and the emitters group it
        # last because that is when it was added. Neither ordering is wrong,
        # and pinning one would make a readable table a test failure.
        assert sorted(listed) == sorted(RUN_EVENTS), (
            f"The frame table lists {sorted(listed)}; the server emits "
            f"{sorted(RUN_EVENTS)}."
        )
        assert len(listed) == len(set(listed))

    @pytest.mark.parametrize("event", sorted(FRAME_FIELDS))
    def test_every_field_of_every_frame_is_named(self, guide: str, event: str) -> None:
        row = self._row(guide, event)
        # `withheld` is written `` `withheld: true` `` in two rows, because
        # the row says what the value means as well as that the key exists.
        missing = [
            field
            for field in FRAME_FIELDS[event]
            if f"`{field}`" not in row and f"`{field}:" not in row
        ]
        assert not missing, (
            f"The `{event}` frame carries {missing} and its row in {GUIDE} "
            "never names them. §6 tells a reader to derive their client types "
            "from this page, so a field documented nowhere is a field no "
            "client handles."
        )

    def test_the_conditional_list_is_real(self) -> None:
        # A name here excuses an example from carrying a field, so it may not
        # name a field that does not exist — that is how an excuse outlives
        # the thing it was written for.
        for event, fields in CONDITIONAL_FIELDS.items():
            assert event in FRAME_FIELDS, f"`{event}` is not a frame."
            unknown = sorted(fields - set(FRAME_FIELDS[event]))
            assert not unknown, f"`{event}` does not carry {unknown}."


class TestEveryExampleIsAFrameTheServerCouldSend:
    """The captured responses, which the name-only gate could never see.

    Three of them were pre-clock — no `seq`, no `elapsedMs`, a `spawn` with no
    `spawnId` and no `settled` closing it, a resumed `done` missing `routes`,
    `publishedRejected` and `usage`. The table above them was maintained
    throughout. That is the coverage boundary, exactly.
    """

    def test_the_page_still_shows_some(self, guide: str) -> None:
        # Guards the sweep against going vacuous if the parser stops matching.
        assert len(_examples(guide)) >= 10

    def test_each_names_a_frame_that_exists(self, guide: str) -> None:
        known = set(FRAME_FIELDS) | {CATALOGUE_EVENT}
        for example in _examples(guide):
            assert example.event in known, (
                f"{GUIDE}:{example.line} shows an `{example.event}` frame and "
                "the server has no such event name."
            )

    def test_no_example_carries_a_field_the_frame_does_not(self, guide: str) -> None:
        for example in _examples(guide):
            if example.event not in FRAME_FIELDS:
                continue
            unknown = sorted(set(example.payload) - set(FRAME_FIELDS[example.event]))
            assert not unknown, (
                f"{GUIDE}:{example.line} — the `{example.event}` example shows "
                f"{unknown}, which that frame does not carry."
            )

    def test_an_unabbreviated_example_is_a_whole_frame(self, guide: str) -> None:
        for example in _examples(guide):
            if example.abbreviated or example.event not in FRAME_FIELDS:
                continue
            expected = set(FRAME_FIELDS[example.event]) - CONDITIONAL_FIELDS.get(
                example.event, frozenset()
            )
            missing = sorted(expected - set(example.payload))
            assert not missing, (
                f"{GUIDE}:{example.line} — the `{example.event}` example is "
                f"missing {missing}. An example that means to elide fields says "
                "so with a trailing `, …}`; one that does not is read as the "
                "whole frame, and a client written from it would never handle "
                "the fields it left out."
            )
