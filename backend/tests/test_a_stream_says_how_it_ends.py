"""A stream's published description tells the truth about its last frame.

`stable-beta-public/20`, filed by `04`'s docs sweep. `sse_responses` ended
**every** streaming endpoint's OpenAPI description with the same sentence —
*"The guarantee that every stream ends with one of `done`, `interrupt`,
`error` …"* — and two of the four endpoints have never sent any of those
names. `GET /api/events` emits one event, `workflows.changed`;
`GET /api/kanban/patrol/events` emits one, `patrol.status`. Both end when the
connection does, so the published contract told a client to wait for a frame
that never arrives, on exactly the two endpoints where waiting is the idiom.

The fix is the mechanism `kanban-patrol/31` and `/34` built for frame fields
rather than a second contract: `sse_responses` already receives the endpoint's
event names, so it **decides** the sentence instead of asserting it. A stream
whose names include a terminal one keeps the guarantee, naming the terminal
frames it actually declares; a stream with none says what it does instead.

Everything here is derived from `TERMINAL_EVENTS` and from the published
description's own `Event names:` list. A literal list of which endpoints end
how would be a third copy of the fact, which is the defect this pins against.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from openstategraph.api.sse_contract import sse_responses
from openstategraph.api.streaming import RUN_EVENTS, TERMINAL_EVENTS

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "docs" / "openapi.json"
DOC = ROOT / "docs" / "api.md"

#: The sentence a stream that cannot end with a frame says instead. One
#: spelling, read by both halves of this file.
NO_TERMINAL_PHRASE = "ends when the connection closes"


def _description(entry: dict) -> str:
    return entry[200]["description"] if 200 in entry else entry["200"]["description"]


def _streaming_descriptions() -> dict[str, str]:
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for path, operations in spec["paths"].items():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            response = operation.get("responses", {}).get("200", {})
            if "text/event-stream" in response.get("content", {}):
                found[path] = response.get("description", "")
    return found


def _declared_events(description: str) -> set[str]:
    listed = re.search(r"Event names: (.*?)\.\s", description, re.S)
    assert listed, f"no `Event names:` sentence in: {description!r}"
    return set(re.findall(r"`([^`]+)`", listed.group(1)))


def test_the_spec_still_declares_streaming_endpoints() -> None:
    """Without this the two assertions below can pass over an empty mapping."""
    assert len(_streaming_descriptions()) >= 3


def test_no_published_description_promises_a_frame_its_stream_cannot_send() -> None:
    """The published artifact, endpoint by endpoint, from its own event names."""
    for path, description in _streaming_descriptions().items():
        terminal = _declared_events(description) & set(TERMINAL_EVENTS)
        if terminal:
            assert "ends with one of" in description, (
                f"{path} declares terminal frames {sorted(terminal)} and does not "
                "publish the terminal-frame guarantee"
            )
            continue
        promised = [name for name in TERMINAL_EVENTS if f"`{name}`" in description]
        assert not promised, (
            f"{path} declares none of {sorted(TERMINAL_EVENTS)} among its event "
            f"names, and its description still names {promised}"
        )
        assert NO_TERMINAL_PHRASE in description, (
            f"{path} sends no terminal frame and its description does not say "
            f"what it does instead: {description!r}"
        )


def test_the_generator_decides_rather_than_asserts() -> None:
    """The unit below the artifact: same call, two event vocabularies."""
    ending = _description(sse_responses(RUN_EVENTS, "The run, frame by frame."))
    assert "ends with one of" in ending
    for name in TERMINAL_EVENTS:
        assert f"`{name}`" in ending

    unending = _description(sse_responses(("workflows.changed",), "One frame per change."))
    assert NO_TERMINAL_PHRASE in unending
    assert "ends with one of" not in unending
    for name in TERMINAL_EVENTS:
        assert f"`{name}`" not in unending


def test_the_page_no_longer_carries_the_correction_for_a_fixed_generator() -> None:
    """`docs/api.md` said the generated description was wrong for all four
    endpoints. A correction that outlives its defect is the next stale claim
    — the ticket's own third criterion."""
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    assert "defect in the generator" not in text
