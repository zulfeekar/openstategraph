"""`/chat`'s live flow marks the node inside a mount, not the mount's parent.

## The finding

Reported by the owner: *"`localhost:8123/chat` does not reflect the execution
step — always stayed at router but producing answer."* Frames were on the wire
and the step list beside the diagram read them correctly — `Concierge Router`,
`⤷ spawned Chinook Assistant`, `Chinook Assistant · 56 steps`, `Answer` — while
the diagram sat on `in1` and `Concierge Router` for the whole twenty seconds
the mounted analyst was working, and then jumped to `out1`.

The wire was never the problem. Every one of the ~100 frames emitted from
inside the mount carries `activeNode: "wf-music"` — the *parent's* canvas id
for the mount, which is the honest answer to "which node of THIS document is
the run inside". It was the right answer until `workflow-gallery` 28 and 56
made the diagram **open its mounts**: since then there is no box called
`wf_music` to light, only a mermaid `subgraph` cluster carrying that name and
child nodes spelled `wf_music\3aagent_sql`. Both of `highlightFlow`'s selectors
(`-flowchart-<name>-`, `-<name>-`) therefore matched nothing, once, and every
later frame returned early on the `activeFlowName === name` guard.

The evidence the page needed was already on the same frames and already being
read for the step list: `path: ["wf-music", "agent-sql"]`. `frameOwner` takes
`path[0]` on purpose, because a mount collapses to **one row** in the list.
The diagram opens it, so the diagram must take the other end — the same field,
the opposite entry. That is why the two are separate functions rather than one
with a flag.

## What is pinned here, and why it is structural

`chat.html` is inline JavaScript in a static asset with no harness, and
`test_chat_trace_credits_the_right_node.py` already records the consequence:
what a Python test can hold is that the rule *exists* and that every consumer
goes through it. The behaviour itself is verified in a browser. This file
exists so a silent revert to the `activeNode`-only rule cannot pass unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CHAT = Path(__file__).resolve().parents[1] / "openstategraph" / "api" / "static" / "chat.html"


@pytest.fixture(scope="module")
def page() -> str:
    return CHAT.read_text(encoding="utf-8")


def test_the_diagram_resolves_a_frame_through_its_own_rule(page: str) -> None:
    assert "function flowFrameName(d)" in page


def test_that_rule_reads_the_whole_path_and_not_only_its_head(page: str) -> None:
    body = page.split("function flowFrameName(d)", 1)[1].split("\n}", 1)[0]
    assert "d.path" in body
    # The step list's rule is `path[0]`; this one must not be a second copy of
    # it, or the diagram folds the mount exactly as the list does.
    assert "path[0]" not in body
    # `activeNode` survives as the fallback for a backend that omits `path`.
    assert "activeNode" in body


def test_a_mounted_nodes_diagram_id_is_spelled_the_way_mermaid_spells_it(page: str) -> None:
    body = page.split("function flowFrameName(d)", 1)[1].split("\n}", 1)[0]
    # `Graph.extend(prefix=segment)` joins with a colon and mermaid renders
    # that colon as the CSS escape `\3a`; `compile/composition.mount_segment`
    # joins a nested mount path with `_`. Both spellings are load-bearing.
    assert "\\\\3a" in body
    assert '"_"' in body or "'_'" in body


def test_the_ladder_falls_back_to_the_mount_itself(page: str) -> None:
    """A child document that would not load leaves the mount drawn as one box.

    `api/routes/workflows.py` says so in as many words — a child that will not
    load costs the labels below it — so the diagram may legitimately hold
    `wf_music` and nothing under it, and the resolver has to try both.
    """
    body = page.split("function flowFrameName(d)", 1)[1].split("\n}", 1)[0]
    assert "flowNodeEl(" in body


def test_every_call_site_that_moves_the_marker_goes_through_it(page: str) -> None:
    """`update`, `progress`, `invoked`, `token` — the four frames that can move it.

    Counted rather than named: a fifth frame type that moves the marker its own
    way is the defect this ticket is, one frame type along.
    """
    assert page.count("highlightFlow(flowFrameName(d))") == 4
    # …and no call site may go back to reading a bare id off the frame.
    assert "highlightFlow(d.activeNode" not in page


def test_the_lookup_does_not_go_through_a_css_identifier_escape(page: str) -> None:
    """A mermaid id contains a literal backslash, and `CSS.escape` is for identifiers.

    `CSS.escape("wf_music\\3aagent_sql")` inside a quoted attribute value is two
    escaping grammars stacked on one string. The ids are compared as strings
    instead, which has no grammar to get wrong.
    """
    body = page.split("function flowNodeEl(", 1)[1].split("\n}", 1)[0]
    assert "CSS.escape" not in body
    assert "-flowchart-" in body


def test_an_unresolved_target_is_reported_rather_than_left_silent(page: str) -> None:
    """A ring that cannot find its node used to clear and say nothing.

    Which is how this survived: the page asserted nothing false, so nothing
    looked wrong except the absence of a highlight — and the run *had* moved
    on, so the absence read as an animation quirk. A name the diagram does not
    contain is a disagreement between the compiler and this page, and it should
    cost a developer one console line, not a bug report.
    """
    body = page.split("function highlightFlow(", 1)[1].split("\n}\n", 1)[0]
    assert "console.warn" in body


def test_the_pause_badge_uses_the_same_lookup(page: str) -> None:
    """`pauseFlow` held the second copy of the selector pair, so it had the bug too.

    An approval node inside a mounted workflow got no badge at all — the run
    stopped, the page said so in words, and the diagram showed nothing waiting.
    """
    body = page.split("function pauseFlow(", 1)[1].split("\n}", 1)[0]
    assert "flowNodeEl(" in body
    assert "querySelector(`[id*=" not in body


def test_an_opened_mounts_own_frame_is_not_reported_as_a_disagreement(page: str) -> None:
    """The mount's completion frame has honestly nowhere to put a ring.

    `path: ["wf-music"]` arrives once per mount, and since the diagram opened
    that mount there is a `subgraph` cluster carrying the name and no node. A
    warning there would fire on every normal run of every composed workflow,
    which is how an instrument becomes noise and then becomes ignored — the
    failure mode `DeveloperChannel.redactions` already records in this
    codebase's own words. Resolving to "" leaves the marker on the child it is
    already on, which is where the run still is.
    """
    assert "function flowClusterEl(name)" in page
    body = page.split("function flowFrameName(d)", 1)[1].split("\n}", 1)[0]
    assert "flowClusterEl(" in body
