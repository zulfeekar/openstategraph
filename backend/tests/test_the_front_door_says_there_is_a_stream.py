"""The front page names the run stream, and never invents a frame name.

`docs-onramp/14`. The owner, 2026-09-06: *"is it clear in the README — the
workflow editor and the customer-facing chat — if a user wants to implement
their own, is there an endpoint they can listen to out of the box as an async
stream?"* The answer was yes and the front page said none of it: `/chat`
appeared twice inside a paragraph about wheel size, nothing called it the
customer-facing app, the editor was never contrasted with it, and
`POST /api/runs/stream` was not named at all. The only pointer routed through
the adoption page first.

What is pinned here is the same thing `test_api_guide.py` pins one level down,
and for the same reason: **a frame name written on a page is a claim about the
wire.** So no name in this file is typed. `started` and the three terminal
frames are read out of `docs/openapi.json` — the generated artifact, one
sentence of which (`Event names:` / `ends with one of`) is written straight
from the emitters — and the README is checked against what that says today. A
frame renamed in the code renames it here, and the front page goes red with the
API guide instead of quietly keeping the old word.

The prose is deliberately not pinned, exactly as `test_the_front_door_stays_short.py`
argues: how the two surfaces are introduced is taste. What is checked is that
the block exists, names both surfaces, names the endpoint, gets the frame names
right, tells a browser developer the one thing that will otherwise cost them an
afternoon (`EventSource` cannot POST), and links to the page that carries the
rest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
OPENAPI = REPO / "docs" / "openapi.json"

#: The heading the block sits under. Resolved from the file, never counted to.
BLOCK_HEADING = "## Two surfaces, one API"


def _stream_description() -> str:
    """The published description of the `POST /api/runs/stream` 200 response."""
    document = json.loads(OPENAPI.read_text(encoding="utf-8"))
    response = document["paths"]["/api/runs/stream"]["post"]["responses"]["200"]
    described = response["description"]
    assert "Frame fields:" in described, (
        "docs/openapi.json no longer carries the `Frame fields:` sentence this "
        "file derives from. Regenerate it with scripts/generate_openapi.py; if "
        "the sentence genuinely moved, move this reader with it rather than "
        "typing the names in."
    )
    return described


def _event_names() -> list[str]:
    described = _stream_description()
    listed = re.search(r"Event names: (.+?)\. Frame fields:", described)
    assert listed, "the `Event names:` sentence is gone from docs/openapi.json"
    return re.findall(r"`([a-zA-Z]+)`", listed.group(1))


def _terminal_names() -> list[str]:
    described = _stream_description()
    guarantee = re.search(r"ends with one of ([^.]+?) is in", described)
    assert guarantee, "the terminal-frame sentence is gone from docs/openapi.json"
    return re.findall(r"`([a-zA-Z]+)`", guarantee.group(1))


def _block() -> str:
    """The section's text, from its heading to the next `## `."""
    lines = README.read_text(encoding="utf-8").splitlines()
    starts = [n for n, line in enumerate(lines) if line.strip() == BLOCK_HEADING]
    assert len(starts) == 1, (
        f"README.md carries {len(starts)} copies of {BLOCK_HEADING!r}; it needs "
        "exactly one, because that section is where the front page answers "
        "'can I listen to a run myself?'"
    )
    start = starts[0]
    for offset, line in enumerate(lines[start + 1 :], start=start + 1):
        if line.startswith("## "):
            return "\n".join(lines[start:offset])
    return "\n".join(lines[start:])


def test_the_sources_were_actually_found() -> None:
    """A sweep over nothing passes."""
    assert README.is_file() and OPENAPI.is_file()
    assert len(_event_names()) >= 5
    assert _terminal_names()


class TestTheFrontPageNamesBothSurfaces:
    def test_the_editor_and_the_chat_are_contrasted(self) -> None:
        block = _block()
        assert "`/chat`" in block, "the block never names the chat surface's path"
        assert "editor" in block.lower()
        assert "customer" in block.lower(), (
            "nothing on the front page says `/chat` is the customer-facing app, "
            "which is the sentence `docs-onramp/14` was filed for"
        )

    def test_both_are_said_to_be_clients_of_the_api(self) -> None:
        assert "`/api`" in _block()


class TestTheStreamIsNamedOnTheFrontPage:
    def test_the_endpoint_is_named(self) -> None:
        assert "POST /api/runs/stream" in _block()

    def test_the_first_frame_is_the_one_the_server_sends_first(self) -> None:
        first = _event_names()[0]
        assert f"`{first}`" in _block(), (
            f"the stream opens with `{first}` and the front page does not say so"
        )

    @pytest.mark.parametrize("event", _terminal_names())
    def test_each_terminal_frame_is_named(self, event: str) -> None:
        assert f"`{event}`" in _block(), (
            f"`{event}` ends a run stream and the front page never names it, so "
            "a reader cannot tell when to stop reading the body"
        )

    def test_it_invents_no_frame_name(self) -> None:
        """The direction a names-are-present check cannot see.

        A block naming `finished` or `complete` would pass every assertion
        above and still send a reader looking for a frame that never arrives.
        """
        known = set(_event_names())
        # Only the fenced-prose backticked words that look like frame names —
        # a lowercase bare word, which is what every event name is. Paths,
        # flags and JSON keys carry `/`, `-` or capitals and are left alone.
        quoted = set(re.findall(r"`([a-z]+)`", _block()))
        # Words the block legitimately quotes that are not frames.
        allowed = {"fetch", "get", "post"}
        invented = sorted(quoted - known - allowed)
        assert not invented, (
            f"the block quotes {invented}, which the run stream does not emit. "
            "Every frame name on this page is derived from docs/openapi.json; "
            "add a genuinely non-frame word to `allowed` above, deliberately."
        )


class TestTheOneSentenceABrowserDeveloperNeeds:
    def test_eventsource_is_ruled_out_and_fetch_is_named(self) -> None:
        block = _block()
        assert "EventSource" in block, (
            "the run stream is a POST, so `EventSource` cannot read it. A front "
            "page that names an SSE endpoint without saying this has sent every "
            "browser developer down the one road that does not work."
        )
        assert "fetch" in block

    def test_the_curl_is_pasteable(self) -> None:
        block = _block()
        assert "```bash" in block and "curl" in block
        assert "/api/runs/stream" in block
        # A run takes the document as input, so a one-call curl cannot exist;
        # the example has to fetch the document first, and a reader who copies
        # only the second half gets a 422.
        assert "/api/workflows/" in block

    def test_it_links_to_the_page_that_carries_the_rest(self) -> None:
        assert "docs/api.md" in _block()
