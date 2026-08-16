"""It is an SDK: every collaborator the runtime uses can come from the caller.

The asymmetry this module was written to close: `checkpointer` was injectable
and its sibling — the long-term memory `Store` — was not, because
`WorkflowServices.__init__` called `build_store()` itself and read the
environment. A caller who already runs Postgres for their checkpoints had no
way to say "and put the memories there too"; they got a process-local
`InMemoryStore` that looked like it worked and lost every saved fact on
restart. Capabilities had the same hole in a different shape: a tool or a
function could only arrive by being a file inside the package directory or a
`pip install`-ed plugin, so a caller vendoring somebody else's package could
not substitute one at all.

So `store=`, `tools=`, `functions=` and `middleware=` join `model=`,
`checkpointer=`, `knowledge_dir=` and `trace_file=`. The tests here pin the two
things that cannot be read off the signature: the injected object is the one
the running graph actually uses, and injection outranks every other source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore

from openstategraph import load_workflow
from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult
from openstategraph.api.services import WorkflowServices


LOCAL_TOOL_SOURCE = '''\
from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult


class EchoTool(BaseTool):
    name = "echo"
    description = "Returns a fixed string."
    node_type = "tool.demo-echo"
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="from the package")
'''

LOCAL_FUNCTION_SOURCE = '''\
def shout(text: str) -> str:
    return "from the package"
'''


class RecordingTool(BaseTool):
    """A caller-supplied tool that remembers whether it was the one called."""

    name = "echo"
    description = "Returns a fixed string."
    node_type = "tool.demo-echo"
    Args = NoArgs

    def __init__(self) -> None:
        self.calls = 0

    def _execute(self, args: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(content="from the caller")


class ToolCallingModel(GenericFakeChatModel):
    """Calls one named tool once, then answers.

    The suite's shared `RespondingModel` only ever returns text, and the two
    facts under test here — that the injected tool is the one invoked, and
    that `save_memory` lands in the injected store — are only observable from
    inside a real tool loop.
    """

    tool_name: str = ""
    tool_args: dict = {}
    answer: str = "done"
    fired: bool = False

    def __init__(self, tool_name: str, tool_args: dict, answer: str = "done") -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "tool_name", tool_name)
        object.__setattr__(self, "tool_args", tool_args)
        object.__setattr__(self, "answer", answer)
        object.__setattr__(self, "fired", False)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        from langchain_core.outputs import ChatGeneration, ChatResult

        if self.fired:
            message = AIMessage(content=self.answer)
        else:
            object.__setattr__(self, "fired", True)
            message = AIMessage(
                content="",
                tool_calls=[{"name": self.tool_name, "args": self.tool_args, "id": "call-1"}],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def write_package(
    root: Path,
    slug: str,
    document: dict[str, Any],
    *,
    tool_source: str | None = None,
    function_source: str | None = None,
) -> Path:
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {"version": 1, "name": slug, "savedAt": "", "document": document}
    (directory / "workflow.json").write_text(json.dumps(envelope, indent=2))
    if tool_source is not None:
        (directory / "tools").mkdir(exist_ok=True)
        (directory / "tools" / "echo.py").write_text(tool_source)
    if function_source is not None:
        (directory / "functions").mkdir(exist_ok=True)
        (directory / "functions" / "shout.py").write_text(function_source)
    return directory


def agent_document(tool_type: str | None) -> dict[str, Any]:
    nodes = [
        node("in1", "input.text"),
        node("ag1", "agent.llm", systemPrompt="Answer."),
        node("out1", "output.formatted"),
    ]
    edges = [
        edge("in1", "text", "ag1", "prompt"),
        edge("ag1", "result", "out1", "result"),
    ]
    if tool_type is not None:
        nodes.append(node("t1", tool_type))
        edges.append(edge("t1", "tool", "ag1", "tools"))
    return {"version": 1, "name": "demo", "nodes": nodes, "edges": edges}


def function_document(fn_type: str) -> dict[str, Any]:
    return {
        "version": 1,
        "name": "fn-demo",
        "nodes": [node("in1", "input.text"), node("f1", fn_type), node("out1", "output.formatted")],
        "edges": [
            edge("in1", "text", "f1", "candidate"),
            edge("f1", "report", "out1", "result"),
        ],
    }


class TestTheStoreIsTheCallersToSupply:
    """`checkpointer=` was injectable; its sibling must be too."""

    def test_memory_saved_by_the_tool_lands_in_the_injected_store(self, tmp_path: Path) -> None:
        store = InMemoryStore()
        package = write_package(tmp_path, "demo-pkg", agent_document(None))
        model = ToolCallingModel("save_memory", {"fact": "the invoice run is monthly"})

        # `user_email=` is how a library caller says who the run is for
        # (memory ticket 01 / ship-it 47). Omitting it is not "anonymous" any
        # more — it is no user scope at all.
        load_workflow(package, model=model, store=store).ask(
            "remember that", user_email="ada@example.com"
        )

        saved = [item.value["fact"] for item in store.search(("memories", "ada@example_com"))]
        assert saved == ["the invoice run is monthly"]

    def test_the_injected_object_is_used_as_is_not_copied(self, tmp_path: Path) -> None:
        sentinel = InMemoryStore()

        services = WorkflowServices(tmp_path, memory_store=sentinel)

        assert services.memory_store is sentinel

    def test_omitting_it_keeps_the_environment_driven_default(self, tmp_path: Path) -> None:
        """`None` must mean exactly what it meant before this parameter
        existed — `build_store()`, env-driven — or every existing deployment
        silently loses its store."""
        services = WorkflowServices(tmp_path)

        assert isinstance(services.memory_store, InMemoryStore)


class TestExplicitCapabilitiesOutrankEveryOtherSource:
    """Precedence: built-in < plugin < package-local < **caller**."""

    def test_an_injected_tool_replaces_the_packages_own(self, tmp_path: Path) -> None:
        injected = RecordingTool()
        package = write_package(
            tmp_path,
            "demo-pkg",
            agent_document("tool.demo-echo"),
            tool_source=LOCAL_TOOL_SOURCE,
        )
        model = ToolCallingModel("echo", {})

        load_workflow(
            package, model=model, tools={"tool.demo-echo": injected}
        ).ask("call the tool")

        assert injected.calls == 1

    def test_an_injected_tool_replaces_a_built_in(self, tmp_path: Path) -> None:
        sentinel = RecordingTool()
        built_in = next(iter(sorted(WorkflowServices(tmp_path).capabilities.tools(None))))

        services = WorkflowServices(tmp_path, tools={built_in: sentinel})

        assert services.capabilities.tools(None)[built_in] is sentinel

    def test_a_deliberate_substitution_is_not_reported_as_a_duplicate(
        self, tmp_path: Path
    ) -> None:
        """A collision between the caller's tool and the package's own is the
        caller saying "use mine". Warning about it would train adopters to
        ignore the one list that means "this run lost a capability"."""
        package = write_package(
            tmp_path,
            "demo-pkg",
            agent_document("tool.demo-echo"),
            tool_source=LOCAL_TOOL_SOURCE,
        )
        model = ToolCallingModel("echo", {})

        loaded = load_workflow(package, model=model, tools={"tool.demo-echo": RecordingTool()})

        assert loaded.warnings == []

    def test_an_injected_function_replaces_the_packages_own(self, tmp_path: Path) -> None:
        package = write_package(
            tmp_path,
            "fn-pkg",
            function_document("function.shout"),
            function_source=LOCAL_FUNCTION_SOURCE,
        )

        loaded = load_workflow(
            package, functions={"function.shout": lambda text: "from the caller"}
        )

        assert loaded.ask("hello") == "from the caller"

    def test_an_injected_function_resolves_one_the_package_never_had(
        self, tmp_path: Path
    ) -> None:
        package = write_package(tmp_path, "fn-pkg", function_document("function.shout"))

        loaded = load_workflow(package, functions={"function.shout": lambda text: "supplied"})

        assert loaded.warnings == []
        assert loaded.ask("hello") == "supplied"

    def test_an_injected_middleware_replaces_the_slot_a_package_filled(
        self, tmp_path: Path
    ) -> None:
        sentinel = object()

        services = WorkflowServices(tmp_path, middleware={"summarization": sentinel})

        assert services.capabilities.middleware("demo-pkg")["summarization"] is sentinel


class TestTheAssemblyPointStaysSingular:
    """HTTP, MCP and `load_workflow` share one `WorkflowServices`. A second
    wiring path is how three run endpoints once drifted about capabilities."""

    def test_load_workflow_passes_every_injection_through_workflow_services(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}
        import openstategraph.api.services as services_module

        original = services_module.WorkflowServices

        class Recording(original):  # type: ignore[misc, valid-type]
            def __init__(self, workflows_root: Any = None, **kwargs: Any) -> None:
                seen.update(kwargs)
                super().__init__(workflows_root, **kwargs)

        monkeypatch.setattr(services_module, "WorkflowServices", Recording)
        package = write_package(tmp_path, "demo-pkg", agent_document(None))
        store, tool, fn, mw = InMemoryStore(), RecordingTool(), (lambda t: t), object()

        load_workflow(
            package,
            model=ToolCallingModel("save_memory", {"fact": "x"}),
            store=store,
            tools={"tool.demo-echo": tool},
            functions={"function.shout": fn},
            middleware={"summarization": mw},
        )

        # `checkpointer` joined the set in ticket 05: it used to be built
        # inside `load_workflow` beside the services object, which is exactly
        # the second wiring path this test exists to forbid. None here means
        # "this caller did not pass one" — the services default then applies.
        # `memory_store` is the internal keyword since install-experience
        # ticket 12; `load_workflow(store=)` is the public one and is
        # unchanged. That the two differ is the point of the rename — the
        # attribute `services.store` is the *filesystem* store.
        assert seen == {
            "memory_store": store,
            "checkpointer": None,
            "tools": {"tool.demo-echo": tool},
            "functions": {"function.shout": fn},
            "middleware": {"summarization": mw},
        }
