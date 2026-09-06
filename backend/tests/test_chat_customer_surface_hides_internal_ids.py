"""`/chat`'s timeline stops printing raw node ids, and Send stops accepting
whitespace (ticket 82).

Two independent defects on the one surface a non-developer sees:

1. `displayName` fell all the way back to the bare node id (`in1`, `out1`,
   `grader-general`) when a node had no author-given title. Those ids are the
   developer half of a boundary this project draws deliberately elsewhere —
   `docs/api.md` §"Audience: what a customer's run cannot carry" already
   removed `warnings` from a customer's `done` frame for the same reason. The
   fallback now goes through the node's own **type**, humanised, before it
   ever reaches the bare id — the editor's own trace
   (`src/view/ask/traceTree.tsx`) is a developer surface and is deliberately
   left alone; this fallback is reached only on `/chat`.

2. `send()` already refused whitespace-only text via `.trim()`, but silently
   — the button stayed enabled, so pressing it produced no turn, no error,
   and no `POST /api/runs/stream`. `updateSendEnabled` now disables the
   button when the composer is empty and Stop is never disabled by that
   check, only by leaving `inFlight` unset.

This page is a hand-written HTML asset with no build step and no test
harness, so — as `test_chat_trace_credits_the_right_node.py` establishes —
what is pinned here is **structural**: that the fallback chain and the
disabled-state wiring exist. The behaviour itself is verified in a browser,
not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CHAT = Path(__file__).resolve().parents[1] / "openstategraph" / "api" / "static" / "chat.html"


@pytest.fixture(scope="module")
def page() -> str:
    return CHAT.read_text(encoding="utf-8")


def test_display_name_falls_back_to_a_humanised_type_before_the_bare_id(page: str) -> None:
    body = page.split("function displayName(nodeId)", 1)[1].split("\n}", 1)[0]
    assert "humanizeType(hit.type)" in body
    # The bare id is still the floor, for a node with neither a title nor a
    # resolvable type — never delete the fallback entirely.
    assert "return" in body and "bare" in body
    assert body.index("humanizeType(hit.type)") < body.rindex("bare")


def test_humanize_type_names_the_two_families_every_workflow_has(page: str) -> None:
    assert "function humanizeType(type)" in page
    body = page.split("function humanizeType(type)", 1)[1].split("\n}", 1)[0]
    assert '"Your question"' in body
    assert '"Answer"' in body


def test_the_editors_own_trace_module_file_is_untouched() -> None:
    # This ticket is scoped to /chat. The editor's trace is a separate,
    # tested module that deliberately keeps the raw node id for a developer
    # audience — this ticket must not change its fallback behaviour.
    trace = (
        Path(__file__).resolve().parents[2] / "src" / "view" / "ask" / "traceTree.tsx"
    ).read_text(encoding="utf-8")
    assert "humanizeType" not in trace


def test_send_is_disabled_for_whitespace_only_text(page: str) -> None:
    assert "function updateSendEnabled()" in page
    body = page.split("function updateSendEnabled()", 1)[1].split("\n}", 1)[0]
    assert '$("msg").value.trim()' in body
    # Stop must never be disabled by empty text underneath it — only Send.
    assert "!inFlight" in body


def test_send_enabled_state_is_wired_to_typing_and_to_run_state(page: str) -> None:
    assert '$("msg").addEventListener("input", updateSendEnabled)' in page
    # setComposerRunning flips Send/Stop; it must also refresh the disabled
    # state so a run finishing on an empty composer disables Send again.
    running = page.split("function setComposerRunning(running)", 1)[1].split("\n}", 1)[0]
    assert "updateSendEnabled()" in running
