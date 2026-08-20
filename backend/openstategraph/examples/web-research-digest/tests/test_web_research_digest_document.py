"""The one example whose tools leave the machine — wiring, and the failure shape.

Gallery example 18. What is settled here without calling a model:

- **The wiring.** Two web atoms on one agent, a grader downstream, and the
  grader's `revise` edge closing back on the agent's `feedback` port. That last
  edge is a deviation from the catalogue's row and the reason for it is
  mechanical, not stylistic — see `test_the_grader_can_send_it_back`.
- **The failure shape.** The catalogue's expectation for this row is that "a
  network failure must surface as a readable tool error, never a silent stub".
  That is a property of `prebuilt_web`, and it is asserted here against a host
  the SSRF guard refuses — which needs no network, because the guard resolves
  the name and stops before any socket is opened.

Whether the *model* then behaves — reports the failure instead of papering over
it — is what the two recorded smoke runs in `AGENTS.md` are for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.package_testing import (
    assert_document_shape,
    load_document,
)
from openstategraph.prebuilt_web import WEB_TOOLS

PACKAGE = Path(__file__).resolve().parents[1]

#: Loopback. `_blocked_host` refuses it after a local name resolution, so this
#: exercises the real refusal path with no packet leaving the machine.
UNREACHABLE = "https://127.0.0.1/changelog"


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


@pytest.fixture(scope="module")
def web_tools() -> dict:
    return {tool.name: tool for tool in WEB_TOOLS}


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_both_web_atoms_are_on_the_one_agent(doc: dict) -> None:
    """One agent looping over two tools — not two agents owning one each.

    That is the whole distinction from example 20, which spends more calls to
    reach several sources at once.
    """
    plan = WorkflowCompiler().plan(doc)
    assert plan.tool_bindings == {"digest1": ["t-search", "t-fetch"]}
    assert len([n for n in doc["nodes"] if n["type"] == "agent.llm"]) == 1


def test_the_grader_can_send_it_back(doc: dict) -> None:
    """The deviation from catalogue row 18, pinned so it is not undone.

    The row draws the grader as a checkpoint with no `revise` edge. A grader
    wired that way is not a checkpoint — it is a silent one. `_router_for`
    (`compile/workflow_compiler.py`) falls back to the *first declared*
    destination when the recorded decision names no wired branch, so a grader
    with only a `pass` edge routes its own `revise` verdict straight to the
    output and the run reports `decisions {"grader1": "revise"}` beside a
    shipped answer. Gallery ticket 31.

    So this example wires the edge, and the cycle is a research retry: go and
    fetch the source you did not fetch.
    """
    plan = WorkflowCompiler().plan(doc)
    assert plan.conditional["grader1"] == {"revise": "digest1", "pass": "out1"}


def test_a_wired_grader_is_never_warned_about(doc: dict) -> None:
    """The other half of ticket 31's contract, on the example that wires it.

    `support-triage` ships the unwired shape on purpose and now carries
    `Finding.UNWIRED_REVISE`. A warning that also fires on the correct wiring
    is a warning everyone learns to skip, so this pins the quiet side.
    """
    from openstategraph.compile.diagnostics import Finding
    from openstategraph.compile.node_runtime import NodeRuntime, RunState

    runtime = NodeRuntime(model=None)
    WorkflowCompiler().build(doc, RunState, runtime.factory(doc), compile_graph=False)
    assert not runtime.diagnostics.any(Finding.UNWIRED_REVISE)


def test_the_rubric_demands_a_source_and_forgives_a_failure(doc: dict) -> None:
    """Both halves matter, and the second is the unobvious one.

    A rubric that only demands sources teaches the model that failing to reach
    the web is a failing grade — which is precisely the pressure that produces
    an invented digest. So an honest, quoted tool failure is written into the
    criteria as a pass.
    """
    criteria = next(n for n in doc["nodes"] if n["id"] == "grader1")["data"]["criteria"]
    assert "Sources:" in criteria
    assert "tool failure" in criteria


class TestANetworkFailureIsReadable:
    def test_a_refused_host_fails_loudly(self, web_tools: dict) -> None:
        result = web_tools["web_fetch"].run(url=UNREACHABLE)
        assert not result.ok
        assert result.error
        assert "not reachable" in result.error

    def test_it_is_never_an_empty_success(self, web_tools: dict) -> None:
        """The silent stub this example exists to rule out.

        An unreachable page must not come back as `ok` with empty content: an
        empty success is indistinguishable from a page that said nothing, and
        a model handed one has no way to know it should stop.
        """
        result = web_tools["web_fetch"].run(url=UNREACHABLE)
        assert not (result.ok and not (result.content or "").strip())

    def test_the_prompt_tells_the_agent_to_report_it(self, doc: dict) -> None:
        prompt = next(n for n in doc["nodes"] if n["id"] == "digest1")["data"]["systemPrompt"]
        assert "verbatim" in prompt
