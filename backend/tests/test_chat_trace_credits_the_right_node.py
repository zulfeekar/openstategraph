"""`/chat`'s trace credits a step to the node that ran it (ticket 72).

LangGraph emits a node's *inner* frames — `model`, `tools`, a middleware step
— **before** that node's own completion frame. Both trace surfaces folded an
internal frame into "the row above it", which is therefore always the node
that ran *before* the work. On the shipped `chinook-assistant` the customer
page showed `Concierge Router · 25 steps` on a classifier with no tools wired,
while the agent that owns those tools showed nothing.

The evidence was already on every frame: `path` is `RunPathResolver`'s walk of
the checkpoint namespace against a known name->id map, and its last entry is
the frame's own card. The editor's rule is a plain module with real unit tests
(`src/view/ask/traceTree.test.ts`). This page's rule is inline JavaScript in an
HTML asset with no harness, so what is pinned here is **structural**: that the
lookup exists and that both of the page's two trace consumers go through it.
The behaviour itself is verified in a browser, not here — this test exists so
a silent revert to the positional rule cannot pass unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CHAT = Path(__file__).resolve().parents[1] / "openstategraph" / "api" / "static" / "chat.html"


@pytest.fixture(scope="module")
def page() -> str:
    return CHAT.read_text(encoding="utf-8")


def test_the_page_resolves_a_frames_owner_from_the_path_the_server_sent(page: str) -> None:
    assert "function frameOwner(d)" in page
    body = page.split("function frameOwner(d)", 1)[1].split("\n}", 1)[0]
    # `path` first, at its OUTERMOST end: this page shows one document, and
    # the deeper entries name nodes of a mounted child whose ids collide with
    # it. A whole mounted run collapses to the mount's own line.
    assert "path[0]" in body
    assert "path[path.length - 1]" not in body
    # `activeNode` second, for a frame whose path resolved to nothing.
    assert "d.activeNode" in body


def test_both_trace_consumers_use_it(page: str) -> None:
    # The live step strip, and the timeline's own row record.
    assert page.count("frameOwner(d)") >= 2
    assert "owner: frameOwner(d)" in page


def test_the_live_strip_asks_for_the_owners_row_before_guessing(page: str) -> None:
    strip = page.split("Internal machinery collapses", 1)[1].split("} else {", 1)[0]
    assert "openRow(owner)" in strip
    # The positional walk survives only as the fallback for a frame that
    # carries neither field, and it must not run before the lookup.
    assert strip.index("openRow(owner)") < strip.index("steps.lastElementChild")


def test_the_timeline_no_longer_folds_an_internal_frame_into_the_last_bar(page: str) -> None:
    timeline = page.split("function renderTimeline(", 1)[1].split("\nfunction ", 1)[0]
    assert "last.ms += d; last.internal++" not in timeline
    assert "open[owner]" in timeline
