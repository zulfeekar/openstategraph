"""A plugin tool's node type must say which implementation ran — or that none did.

`rules-that-can-fail/02`. Two questions with one answer, which is why they are
one file: a `workflow.json` naming `tool.acme-ping` means one thing on a
machine with `acme-osg-tools` installed and another on a machine without it,
and the channel is only safe if the document's reader is *told* which.

`extensions.py` claims a plugin's node type "collides loudly". Two of three.

The claim is the argument for opening `openstategraph.tools` to strangers at
all. `openstategraph.functions` is deliberately *not* reserved because a
`function.<name>` injected process-wide would change what a package's own node
resolves to with nothing in the document naming the provider; tools are said to
be different because a tool's `node_type` is *"visible in the document and
collides loudly rather than quietly"*.

The registry layers three sources — **built-in < third-party < workflow-local**
— which gives three boundaries where one `node_type` can be claimed twice, plus
the flat case of two distributions claiming it at once. Audited 2026-08-30
(`rules-that-can-fail/02`):

| Two claimants | Who wins | Said out loud? |
| --- | --- | --- |
| two installed distributions | the later one | yes — `_discover_tools` names both |
| a plugin over a built-in | the plugin | yes — `replaces_builtin` and a warning |
| a package's own `tools/` over a plugin | the package | **no — measured silent** |

The third was the whole gap, and it is the worst of the three to lose. The
other two are one person's decision: whoever ran `pip install` chose to replace
a bundled tool, and whoever installed two colliding wheels can uninstall one.
This one is *two* authors who never met — a package author writing
`node_type = "tool.acme-ping"` in their own `tools/` folder, and a distribution
that already claims it in the venv — and the editor makes it worse rather than
better: the two are minted as **different palette cards** (`<slug>/tools.Local`
and `tool.acme-ping`), so a user can place the plugin's card and get the
package's tool. That is exactly the failure `pluginNodes.ts` says the
precedence rule exists to prevent — *"anything else would show one tool on the
canvas and run another"*.

So the sentence was made true rather than corrected. These tests are the three
rows of that table, plus the fourth case that is not a collision at all —
nobody claiming the type, measured in the last class.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.abc import BaseTool, NoArgs, ToolResult
from openstategraph.api.main import create_app
from openstategraph.extensions import DISABLE_PLUGINS_ENV, TOOLS_GROUP

SHARED_TYPE = "tool.acme-ping"


class AcmePingTool(BaseTool):
    """What the installed distribution ships."""

    name = "acme_ping"
    description = "Answers with a pong."
    node_type = SHARED_TYPE
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="pong")


class AcmeWebSearchTool(BaseTool):
    """A plugin claiming a node type the framework already ships."""

    name = "acme_web_search"
    description = "A third party's take on web search."
    node_type = "tool.web-search"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="acme")


class _FakeDist:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeEntryPoint:
    def __init__(self, name: str, group: str, dist: str, result: Any = None) -> None:
        self.name = name
        self.group = group
        self.dist = _FakeDist(dist)
        self._result = result

    def load(self) -> Any:
        return self._result


def install(monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
    """Pretend these entry points are installed — as `test_extensions.py` does."""

    def fake_entry_points(*, group: str = "") -> list[FakeEntryPoint]:
        return [ep for ep in entry_points if ep.group == group]

    monkeypatch.delenv(DISABLE_PLUGINS_ENV, raising=False)
    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)


LOCAL_TOOL = '''
"""A package's own tool, which happens to claim a plugin's node type."""

from typing import Any

from openstategraph.abc import BaseTool, NoArgs, ToolResult


class LocalPingTool(BaseTool):
    name = "local_ping"
    description = "The package's own ping."
    node_type = "tool.acme-ping"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="local")
'''


def _package_claiming_the_type(root: Path, slug: str = "my-flow") -> Path:
    directory = root / slug
    (directory / "tools").mkdir(parents=True)
    (directory / "tools" / "ping.py").write_text(LOCAL_TOOL)
    (directory / "workflow.json").write_text('{"name": "My Flow", "nodes": [], "edges": []}')
    return directory


class _Store:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def directory_for(self, slug: str) -> Path:
        return self._directory


class TestTwoDistributionsClaimingOneType:
    """Row one. Already loud; pinned so it stays that way."""

    def test_both_distributions_are_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(
            monkeypatch,
            FakeEntryPoint("a", TOOLS_GROUP, "osg-acme", [AcmePingTool]),
            FakeEntryPoint("b", TOOLS_GROUP, "osg-other", [AcmePingTool]),
        )
        from openstategraph.extensions import entry_point_tools

        [message] = [w for w in entry_point_tools().warnings if SHARED_TYPE in w]
        assert "osg-acme" in message
        assert "osg-other" in message


class TestAPluginOverABuiltIn:
    """Row two. Already loud, on the surface the editor reads."""

    def test_the_capabilities_response_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        install(monkeypatch, FakeEntryPoint("a", TOOLS_GROUP, "osg-acme", [AcmeWebSearchTool]))
        _package_claiming_the_type(tmp_path, "plain")
        client = TestClient(create_app(workflows_root=tmp_path))

        body = client.get("/api/workflows/plain/capabilities").json()

        [message] = [w for w in body["warnings"] if "tool.web-search" in w]
        assert "osg-acme" in message


class TestAPackagesOwnToolsOverAPlugin:
    """Row three — the one that was silent, on both surfaces."""

    def test_the_run_registry_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The channel that matters: the tool that will actually be bound."""
        install(monkeypatch, FakeEntryPoint("a", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        directory = _package_claiming_the_type(tmp_path)
        from openstategraph.api.registries import build_tool_registry

        warnings: list[str] = []
        registry = build_tool_registry(_Store(directory), "my-flow", warnings=warnings)

        assert type(registry[SHARED_TYPE]).__name__ == "LocalPingTool"
        [message] = [w for w in warnings if SHARED_TYPE in w]
        assert "osg-acme" in message, message
        assert "my-flow" in message, message

    def test_the_capabilities_response_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The editor's channel — this list is what `setCapabilityWarnings` gets."""
        install(monkeypatch, FakeEntryPoint("a", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        _package_claiming_the_type(tmp_path)
        client = TestClient(create_app(workflows_root=tmp_path))

        body = client.get("/api/workflows/my-flow/capabilities").json()

        [message] = [w for w in body["warnings"] if SHARED_TYPE in w]
        assert "osg-acme" in message, message

    def test_it_names_the_card_that_is_now_a_lie(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Both cards are in the palette; the message must say which one loses."""
        install(monkeypatch, FakeEntryPoint("a", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        _package_claiming_the_type(tmp_path)
        client = TestClient(create_app(workflows_root=tmp_path))

        body = client.get("/api/workflows/my-flow/capabilities").json()

        [message] = [w for w in body["warnings"] if SHARED_TYPE in w]
        assert "acme_ping" not in message or "never" in message or "cannot" in message
        assert SHARED_TYPE in message

    def test_a_package_that_claims_nothing_is_quiet(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The narrowness that makes the message worth reading."""
        install(monkeypatch, FakeEntryPoint("a", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        directory = tmp_path / "quiet"
        directory.mkdir()
        (directory / "workflow.json").write_text('{"name": "Q", "nodes": [], "edges": []}')
        from openstategraph.api.registries import build_tool_registry

        warnings: list[str] = []
        build_tool_registry(_Store(directory), "quiet", warnings=warnings)

        assert [w for w in warnings if SHARED_TYPE in w] == []


class TestTheSentenceIsNotAheadOfTheCode:
    """The map's rule: a claim in prose gets a way to fail.

    `extensions.py`'s paragraph is the reason `openstategraph.tools` is open to
    strangers while `openstategraph.functions` is not, so it is load-bearing
    argument rather than commentary.
    """

    def test_the_claim_is_still_made(self) -> None:
        import openstategraph.extensions as extensions

        assert "collides loudly" in (extensions.__doc__ or "")

    def test_every_boundary_the_claim_covers_has_a_test_here(self) -> None:
        """Three claimant pairs, three classes above. A fourth would need one."""
        classes = {
            name
            for name, obj in globals().items()
            if isinstance(obj, type) and name.startswith("Test")
        }
        assert {
            "TestTwoDistributionsClaimingOneType",
            "TestAPluginOverABuiltIn",
            "TestAPackagesOwnToolsOverAPlugin",
        } <= classes


class _DeferredRaise:
    """A model object that is not `chat_model.UnconfiguredProvider`.

    Enough to get past the readiness door `osg-agent-experience/48` installed
    — that door refuses only when the model this run holds is the stand-in for
    an unconfigured installation — and it still raises the moment a node asks
    it for anything, which is what these tests have always let happen.
    """

    def __getattr__(self, name: str):
        raise RuntimeError("this test never intended to call a model")


def _give_it_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from openstategraph import chat_model as chat_model_module

    monkeypatch.setattr(chat_model_module, "build_chat_model", lambda _n: _DeferredRaise())


class TestADocumentNamingAPluginNobodyInstalled:
    """The other half of "which one ran": *none of them*, and it says so.

    `CLAUDE.md` declares the `code → canvas` channel safe on two properties,
    the second being *"the type travels with the package"*. A plugin type does
    not — it lives in a virtualenv — which is what made this channel look like
    a fourth one that fails the test. Measured rather than reasoned about
    (2026-08-30): the property that actually does the work is not travelling,
    it is **being named when absent**, and that already holds. A built-in type
    does not travel with the package either.

    So the run below is the evidence for the verdict recorded in `CLAUDE.md`:
    safe on the same terms as a built-in, conditional on this staying true.
    """

    DOCUMENT = {
        "version": 2,
        "name": "plugin-missing",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "a1",
                "type": "agent.llm",
                "position": {"x": 200, "y": 0},
                "data": {"model": "fake:test"},
            },
            {"id": "t1", "type": SHARED_TYPE, "position": {"x": 200, "y": 200}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "t1", "portId": "tool"},
                "target": {"nodeId": "a1", "portId": "tools"},
            },
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }

    def _run(self, monkeypatch: pytest.MonkeyPatch, audience: str) -> dict:
        install(monkeypatch)  # an environment with no plugins at all
        # This class is about a *tool type*, not about credentials, and since
        # `osg-agent-experience/48` a model-driven graph on an installation
        # with no provider configured is refused at the door before any of it
        # runs. So the run is given a model — one that still raises if a node
        # actually calls it, because nothing here needs it to answer.
        _give_it_a_model(monkeypatch)
        response = TestClient(create_app()).post(
            "/api/runs",
            json={"workflow": self.DOCUMENT, "question": "hi", "audience": audience},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_the_document_is_not_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Degrade loud, never silent — the same policy an unknown type gets."""
        assert self._run(monkeypatch, "developer")["outputs"]["in1"] == "hi"

    def test_the_developer_channel_names_the_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = self._run(monkeypatch, "developer")
        assert [w for w in body["developer"]["warnings"] if SHARED_TYPE in w]

    def test_the_customer_channel_does_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unmarked means developer-only — `the-boundary-nobody-checked/02`."""
        assert self._run(monkeypatch, "customer")["developer"] is None

    def test_validation_says_which_kind_of_type_it_could_not_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It names *plugin-discovered* as a possibility, which is the honest
        answer: this build cannot tell a wheel it never had from a folder it
        cannot see."""
        install(monkeypatch)
        body = (
            TestClient(create_app())
            .post("/api/workflows/validate", json={"workflow": self.DOCUMENT})
            .json()
        )
        [finding] = [f for f in body["findings"] if SHARED_TYPE in f]
        assert "plugin" in finding
