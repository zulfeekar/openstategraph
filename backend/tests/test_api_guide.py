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

from pathlib import Path

import pytest

from openstategraph.api.catalogue_events import CATALOGUE_EVENT
from openstategraph.api.streaming import RUN_EVENTS, TERMINAL_EVENTS

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
