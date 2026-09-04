"""Every SSE endpoint is described on the page its own contract points at.

`stable-beta-public/04`. `api/sse_contract.py` ends every streaming
endpoint's OpenAPI description with *"… is in `docs/api.md` — OpenAPI cannot
express it."* That is the right split — OpenAPI 3.1 genuinely cannot type an
unbounded frame sequence — but it makes `docs/api.md` a **destination**, and
nothing checked that a reader following the pointer arrives somewhere that
mentions the endpoint they came from.

Two of the four had drifted by the time this was measured:
`GET /api/kanban/patrol/events` (`kanban-patrol/31`) was described nowhere at
all, and the page's own summary table still read *"The three event streams"*
after the fourth shipped. A count in prose has no way to fail; a pointer that
lands on a page with no mention of you is worse, because the reader assumes
they missed it.

## What is pinned

- Every path in `docs/openapi.json` that answers `text/event-stream` is named
  verbatim in `docs/api.md`.
- The page states no total for them — the same rule
  `test_documented_mcp_tool_surface.py` keeps for tools, and for the same
  reason. Naming them all is what makes a total unnecessary.

`docs/openapi.json` is the source rather than a live app, deliberately: it is
generated, committed and already gated both ways
(`test_openapi_contract.py`, CI's `generated-openapi`), so reading it here
adds no third description of the route table.

## What this file does not pin, and where that went

`sse_responses` used to append the `done`/`interrupt`/`error` terminal-frame
sentence to **all four** endpoints, while the catalogue and patrol streams
emit none of those names — they end when the connection does. That was an
over-promise in the generator rather than in the page; it is fixed
(`stable-beta-public/20`, filed here as 19 before the renumber) and pinned by
`test_a_stream_says_how_it_ends.py`, which decides from `TERMINAL_EVENTS`
what each published description is allowed to claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "api.md"
OPENAPI = ROOT / "docs" / "openapi.json"


def _streaming_paths() -> list[str]:
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    found = []
    for path, operations in spec["paths"].items():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            content = operation.get("responses", {}).get("200", {}).get("content", {})
            if "text/event-stream" in content:
                found.append(path)
    return sorted(set(found))


def test_the_spec_still_declares_streaming_endpoints() -> None:
    """The guard: if `text/event-stream` ever stops appearing in the committed
    spec, the assertion below starts passing over an empty list."""
    assert len(_streaming_paths()) >= 3


def test_every_streaming_endpoint_is_named_in_the_page_it_points_at() -> None:
    text = DOC.read_text(encoding="utf-8")
    missing = [path for path in _streaming_paths() if path not in text]
    assert not missing, (
        "these endpoints answer `text/event-stream` and their own OpenAPI "
        "description sends the reader to `docs/api.md`, which never names them: "
        f"{missing}"
    )


def test_the_page_states_no_stream_count() -> None:
    """The sentence this file was written for. `docs/api.md` said *the three
    event streams* while shipping four."""
    text = DOC.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in text.splitlines()
        if re.search(
            r"\b(two|three|four|five|six)\b[^.\n]{0,20}\b(event )?streams\b",
            line,
        )
    ]
    assert not offenders, (
        "`docs/api.md` counts its event streams in prose; name them instead — a "
        f"count has no way to fail: {offenders}"
    )
