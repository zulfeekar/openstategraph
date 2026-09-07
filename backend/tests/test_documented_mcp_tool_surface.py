"""`docs/mcp.md`'s tool enumeration, held against `EXPOSED_TOOLS`.

`stable-beta-public/04`. The page's §6 — the trust boundary, the list a
reader consults before pointing a shared deployment at anything — said **"The
nine exposed tools"** and listed nine, on a server that exposes fifteen. The
six it omitted are the patrol-board tools, which write to a project's board;
a reader auditing what an MCP client can reach came away with an under-count
of exactly the tools that mutate something.

§1 had the same defect one number smaller: `OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`
"removes `run_workflow` … the other eight stay fully functional", which was
fourteen.

## Why a name census and not a count

The page already argues this against itself. §2's vocabulary listing ends:
*"No total is printed here on purpose: a count is the half of this that rots
silently, and the names are the half that matters."* That paragraph was
written about node types and was right about tools too — the two sentences
this file replaced were both counts, and both rotted in the commit that added
a tool, silently, because a number in prose has no way to fail.

So the pin is the same shape `test_documented_cli_surface.py` uses, in both
directions:

- **Source → page.** A tool in `EXPOSED_TOOLS` the page never names is a
  capability a reader auditing the trust boundary never learns about.
- **Page → source.** A backticked `tool_name` the page presents as exposed
  and the server does not register is a client written against a tool that
  does not answer.

What is deliberately *not* pinned is the prose around the names — why runs
are gated, why publishing is absent. That is argument, and
`test_documented_cli_surface.py`'s docstring gives the reason: pin the string
a caller will type, not the sentence explaining it.
"""

from __future__ import annotations

import re
from pathlib import Path

from openstategraph.mcp_server import EXPOSED_TOOLS

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "mcp.md"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_the_page_and_the_tuple_were_both_found() -> None:
    """The guard every gate written this way needs: if either side moves, the
    assertions below start comparing nothing to nothing."""
    assert DOC.is_file()
    assert len(EXPOSED_TOOLS) > 5


def test_every_exposed_tool_is_named_on_the_page() -> None:
    text = _doc()
    missing = [name for name in EXPOSED_TOOLS if f"`{name}`" not in text]
    assert not missing, (
        "these tools are registered over MCP and `docs/mcp.md` never names them, "
        f"so a reader auditing the trust boundary cannot see them: {missing}"
    )


def test_the_trust_boundary_section_lists_every_one() -> None:
    """§6 is the section a deployment decision is made from, so the whole list
    has to be *there* rather than scattered across the page."""
    text = _doc()
    section = text.split("\n## 6.", 1)[1].split("\n## 7.", 1)[0]
    missing = [name for name in EXPOSED_TOOLS if f"`{name}`" not in section]
    assert not missing, (
        "`docs/mcp.md` §6 enumerates the exposed tools and omits these: " f"{missing}"
    )


def test_the_page_claims_no_tool_the_server_does_not_register() -> None:
    """The other direction, and deliberately narrow: only the two shapes this
    server's tool names actually take are judged — `kanban_*`, and a name
    ending in `_workflow`. The page is full of example code (`run_turn`,
    `run_snippet`), and a rule wide enough to catch those is a rule with a
    suppression in its future."""
    text = _doc()
    claimed = {
        match.group(1)
        for match in re.finditer(r"`(kanban_\w+|\w+_workflow(?:_\w+)?)`", text)
    }
    unknown = sorted(name for name in claimed if name not in EXPOSED_TOOLS)
    assert not unknown, (
        "`docs/mcp.md` presents these as MCP tools and the server registers no such "
        f"tool: {unknown}"
    )


def test_no_section_states_a_tool_count() -> None:
    """The defect this file exists for, stated as a rule rather than as the two
    sentences that carried it. The page's own §2 already forbids this for node
    types; a tool count rots the same way and rotted twice."""
    text = _doc()
    offenders = [
        line.strip()
        for line in text.splitlines()
        if re.search(
            r"\b(five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen)\b"
            r"[^.\n]{0,40}\btools?\b"
            r"|\btools?\b[^.\n]{0,40}"
            r"\b(five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen)\b",
            line,
        )
        and "no total" not in line.lower()
        and "No count here" not in line
    ]
    assert not offenders, (
        "`docs/mcp.md` states a tool count in prose; name the tools instead — a "
        f"count has no way to fail: {offenders}"
    )
