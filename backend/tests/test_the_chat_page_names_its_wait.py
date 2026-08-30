"""`/chat` says what it is waiting for while the wire is quiet
(`launch-readiness/141`).

The owner watched a real run and reported *"I don't see anything for a few
seconds"* against a measurement (`launch-readiness/109`) that put the first
frame at 0.09 s. Both were true. Timestamped at the server on a 28-node
package:

    0.06 s  update   in1        (carries the reader's own question back)
    2.16 s  update   router1
    4.99 s  update   prefetch1  + the first `progress` narration
   13.13 s  token    the first word of the answer

and timestamped in the browser, at receipt and at the DOM mutation carrying
it: frame one received at 15.9 ms, on screen at 62.9 ms. So the paint is
prompt and the **wire is quiet** — three nodes run before anything with a
voice does, because narration covers the agent family only (`105`, still
`partially`).

A quiet wire is not a licence to show nothing; it is a licence to say what is
being waited for. Two sentences, and no more, because only one thing is
honestly known — whether anything has come back at all. An `update` frame
fires when a node COMPLETES and carries that same node as its `activeNode`,
so the identity of whatever is now in charge is unknown until it narrates
itself. A line naming a step would be an invention, which is the shape of the
two defects this surface has already shipped this month.

This page is a hand-written HTML asset with no build step and no test
harness, so — as `test_chat_customer_surface_hides_internal_ids.py`
establishes — what is pinned here is **structural**. The behaviour itself is
verified in a browser, not here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CHAT = Path(__file__).resolve().parents[1] / "openstategraph" / "api" / "static" / "chat.html"

TO_START = "Sent your question — waiting for the workflow to start."
NEXT_STEP = "Working — waiting for the next step to say what it is doing."


@pytest.fixture(scope="module")
def page() -> str:
    return CHAT.read_text(encoding="utf-8")


def test_both_sentences_exist_and_name_a_wait(page: str) -> None:
    for sentence in (TO_START, NEXT_STEP):
        assert sentence in page
        assert "waiting" in sentence.lower(), sentence


def test_the_wait_is_shown_before_the_stream_is_even_opened(page: str) -> None:
    """The first sentence's whole job is the window before any frame lands."""

    body = page[page.index("async function stream(") :]
    show = body.index("showWaiting(WAITING_TO_START)")
    fetched = body.index('await fetch(path, { method: "POST"')
    assert show < fetched


def test_a_completed_step_changes_the_wait_but_is_still_a_wait(page: str) -> None:
    body = page[page.index("async function stream(") :]
    update_branch = body.index('if (event === "update") {')
    assert body.index("showWaiting(WAITING_FOR_THE_NEXT_STEP)") > update_branch


def test_the_placeholder_belongs_to_the_opening_silence_only(page: str) -> None:
    """It must not blink in the gaps between two narration lines.

    Measured live on `/chat` before this guard: the placeholder appeared and
    vanished within a millisecond three times between 7.9 s and 12.3 s of one
    run, because `liveLine` clears nothing and every `update` re-showed it.
    Once a step has narrated itself the stack is on screen and stays there;
    the wait it fills is the one before the surface has any voice at all.
    """

    body = page[page.index("async function stream(") :]
    show = body.index("showWaiting(WAITING_FOR_THE_NEXT_STEP)")
    guard = body.rindex('querySelector(":scope > div.thinking")', 0, show)
    # The guard is on the same statement, not merely somewhere above it.
    assert "if (!" in body[guard - 12 : show]


def test_every_voice_of_its_own_removes_the_placeholder(page: str) -> None:
    """`launch-readiness/110` wearing the other hat.

    A placeholder that outlives the thing it stood in for is the same defect
    as a real line erased by machinery one frame later. `progress` is a real
    narration line and `token` is the answer typing itself out; neither may
    share the panel with a claim that nothing has spoken yet.
    """

    body = page[page.index("async function stream(") :]
    for event in ("progress", "token"):
        branch = body.index('} else if (event === "%s") {' % event)
        tail = body[branch : branch + 400]
        assert "clearWaiting()" in tail, event


def test_every_ending_removes_the_placeholder(page: str) -> None:
    """Answered, failed, paused, stopped, dropped, or refused at the door.

    Six endings, and a line reading "waiting for the workflow to start" under
    a finished answer would be the worst of the lot.
    """

    body = page[page.index("async function stream(") :]
    for event in ("done", "error", "interrupt"):
        branch = body.index('} else if (event === "%s") {' % event)
        assert "clearWaiting()" in body[branch : branch + 400], event
    # The three that are not frames at all: a door that refused before any
    # stream opened, a stop, and a socket that died with nothing on it.
    assert body.count("clearWaiting()") >= 7


def test_the_placeholder_is_not_the_narration_stack(page: str) -> None:
    """`liveLine` claims `div.thinking.live`, and would append into it.

    A placeholder that collected the narration frames it exists to be replaced
    by would put "Sent your question" permanently at the top of every account.
    """

    assert 'row.className = "waiting"' in page
    assert re.search(r"\.steps p\.waiting\b", page)
    assert 'querySelector(":scope > p.waiting")' in page
