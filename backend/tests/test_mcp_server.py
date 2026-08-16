"""The MCP layer — the only surface a customer's own LLM ever touches.

The scenario these tests pin: OpenStateGraph runs on a server, exposes MCP and
nothing else, and a company's MCP client (Claude, Cursor, …) *generates*
StateGraphs against it. So the properties under test are the guardrails, not
the plumbing — the stateless compile loop writes nothing, an invalid document
yields findings instead of artifacts, a save is drafts-only and refuses an
invalid document, and the vocabulary a client must fetch first actually
carries what composing requires.

Model-free by construction: every test here except the run test exercises the
deterministic path, which is the point of the design.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.api.services import WorkflowServices
from openstategraph.mcp_server import (
    EXPOSED_TOOLS,
    NodeVocabulary,
    WorkflowArtifacts,
    WorkflowLibrary,
    WorkflowRuns,
    build_mcp_server,
)


def _linear_document() -> dict[str, Any]:
    """The smallest honest workflow: a question in, the same text out.

    Deliberately model-free — it exercises the whole compile path without a
    provider key, which is exactly what the stateless MCP loop promises.
    """
    def n(i: str, t: str, **d: Any) -> dict[str, Any]:
        return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}

    return {
        "version": 2,
        "name": "linear",
        "nodes": [n("in1", "input.text"), n("out1", "output.formatted")],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }


@pytest.fixture()
def services(tmp_path: Path) -> WorkflowServices:
    """A jailed workflows root — no test ever touches the real `workflows/`."""
    root = tmp_path / "workflows"
    root.mkdir()
    return WorkflowServices(workflows_root=root)


class TestExposedSurface:
    """What a connected client can see is a closed, reviewed list."""

    def test_the_server_registers_exactly_the_declared_tools(
        self, services: WorkflowServices
    ) -> None:
        server = build_mcp_server(services)

        names = sorted(tool.name for tool in asyncio.run(server.list_tools()))

        assert names == sorted(EXPOSED_TOOLS)

    def test_it_exposes_no_publish_no_delete_and_no_credential_tool(self) -> None:
        """The trust boundary, asserted rather than documented.

        Publishing is a human act in the editor; deletion and credentials are
        not reachable over MCP at all.
        """
        forbidden = ("publish", "delete", "credential", "secret", "key")
        assert not [t for t in EXPOSED_TOOLS if any(word in t for word in forbidden)]

    def test_every_tool_carries_a_description(
        self, services: WorkflowServices
    ) -> None:
        """A client's LLM chooses by description; a blank one is a dead tool."""
        for tool in asyncio.run(build_mcp_server(services).list_tools()):
            assert (tool.description or "").strip(), tool.name


class TestNodeVocabulary:
    """The mandatory first call: a client cannot compose without it."""

    def test_it_describes_agent_llm_ports(self) -> None:
        vocabulary = NodeVocabulary().describe()

        agent = next(n for n in vocabulary["node_types"] if n["type"] == "agent.llm")
        ports = {p["id"]: p for p in agent["ports"]}
        assert set(ports) >= {"prompt", "skill", "tools", "feedback", "result"}
        assert ports["tools"]["type"] == "tool"
        assert ports["tools"]["direction"] == "in"
        assert ports["result"]["direction"] == "out"

    def test_it_carries_the_locked_prompt_contract_for_model_driven_types(self) -> None:
        """Same source as `/api/node-contracts`: the Python ladder classes.

        A composing client must see what the machinery already says, or it
        will duplicate — or contradict — the output contract.
        """
        vocabulary = NodeVocabulary().describe()
        by_type = {n["type"]: n for n in vocabulary["node_types"]}

        router = by_type["route.classifier"]
        assert router["prompt_contract"]["preamble"]
        assert router["prompt_contract"]["contract"]
        # `agent.llm`'s sections are genuinely empty — its prompt is entirely
        # developer-supplied — and the payload says so rather than pretending.
        assert by_type["agent.llm"]["prompt_contract"] is not None
        assert by_type["input.text"]["prompt_contract"] is None

    def test_it_names_which_port_types_are_control_flow_and_which_are_bindings(
        self,
    ) -> None:
        """The single most important thing to get right: a tool link is a
        binding, not a graph edge."""
        semantics = NodeVocabulary().describe()["port_semantics"]

        assert "tool" in semantics["binding"]
        assert "skill" in semantics["binding"]
        assert set(semantics["control"]) == {"text", "result"}

    def test_it_lists_every_node_type_the_runtime_implements(self) -> None:
        from openstategraph.prebuilt_architect import KNOWN_NODE_TYPES

        listed = {n["type"] for n in NodeVocabulary().describe()["node_types"]}

        assert KNOWN_NODE_TYPES <= listed

    def test_the_guide_enumerates_the_same_types_the_payload_carries(self) -> None:
        """`docs/mcp.md` elides the payload and names every type in a comment.

        That comment is load-bearing in a way an elision usually is not,
        because the sentence closing it says so: *"a tool absent from this
        payload is a tool no agent can be wired to."* A reader who trusts that
        and does not find `tool.mcp` in the list concludes that MCP tools
        cannot be bound to an agent — which is the opposite of true, and was
        the state of the page until production-ready ticket 20's fifth sweep.

        Three types were missing (`guard.policy`, `memory.segment`,
        `tool.mcp`, `tool.youtube-transcript`) under a printed total of 28 for
        a registry of 31. The total is gone — a cardinal is the half of this
        that rots silently — and the names are pinned, which is the half that
        matters.
        """
        guide = (
            Path(__file__).resolve().parents[2] / "docs" / "mcp.md"
        ).read_text()
        listed = {n["type"] for n in NodeVocabulary().describe()["node_types"]}

        missing = sorted(t for t in listed if t not in guide)
        assert missing == [], (
            "docs/mcp.md tells a composing client that a type absent from the "
            f"vocabulary payload cannot be used, and never names these: {missing}"
        )


class TestStatelessCompile:
    """The centerpiece. Artifacts out, nothing written, no model involved."""

    def test_an_invalid_document_returns_findings_and_no_artifacts(self) -> None:
        artifacts = WorkflowArtifacts()

        result = artifacts.compile({"version": 2, "nodes": [], "edges": []})

        assert result["validated"] is False
        # Named, not merely non-empty: a finding list is what a client's model
        # reads to repair the document, so "some string came back" is not the
        # property (reviews-2026-08-14 ticket 09).
        assert result["findings"] == ["The document needs a non-empty 'nodes' list."]
        assert result["document"] is None
        assert result["mermaid"] == ""

    def test_an_unknown_node_type_is_reported_as_a_finding(self) -> None:
        document = _linear_document()
        document["nodes"].append(
            {"id": "x1", "type": "agent.imaginary", "data": {}, "position": {"x": 0, "y": 0}}
        )

        result = WorkflowArtifacts().compile(document)

        assert result["validated"] is False
        assert any("agent.imaginary" in f for f in result["findings"])

    def test_a_valid_document_round_trips_with_a_compiled_mermaid_topology(self) -> None:
        result = WorkflowArtifacts().compile(_linear_document(), name="Linear")

        assert result["validated"] is True
        assert result["findings"] == []
        assert result["mermaid"].strip()
        assert result["document"]["document"]["nodes"][0]["id"] == "in1"
        assert result["document"]["name"] == "Linear"
        # One name, not two: the envelope and the document agree.
        assert result["document"]["document"]["name"] == "Linear"

    def test_the_returned_envelope_is_an_unpublished_draft(self) -> None:
        """What a client commits to *their* git is a draft envelope — the
        published flag is never something a machine sets."""
        envelope = WorkflowArtifacts().compile(_linear_document())["document"]

        assert envelope["published"] is False
        assert envelope["version"] == 1
        assert "savedAt" in envelope

    def test_it_ships_a_run_snippet_and_a_package_skeleton(self) -> None:
        result = WorkflowArtifacts().compile(_linear_document())

        assert "workflow.json" in result["run_snippet"]
        # The snippet must hand a client the seam that wires the package's own
        # capabilities. The hand-rolled `NodeRuntime(...)` + `WorkflowCompiler`
        # shape it used to print compiles, runs, and silently drops every tool.
        assert "load_workflow" in result["run_snippet"]
        assert "NodeRuntime" not in result["run_snippet"]
        skeleton = result["package_skeleton"]
        assert "workflow.json" in skeleton
        assert any(p.startswith("tools/") for p in skeleton)
        assert any(p.startswith("knowledge/") for p in skeleton)

    def test_it_accepts_a_json_string_as_well_as_an_object(self) -> None:
        """MCP clients serialize inconsistently; a string document is not a
        client error worth a round trip."""
        result = WorkflowArtifacts().compile(json.dumps(_linear_document()))

        assert result["validated"] is True

    def test_it_unwraps_an_envelope_a_client_hands_back(self) -> None:
        wrapped = {"version": 1, "name": "linear", "document": _linear_document()}

        assert WorkflowArtifacts().compile(wrapped)["validated"] is True

    def test_a_document_mounting_a_child_workflow_warns_loudly_not_silently(
        self,
    ) -> None:
        """The stateless path has no library to resolve `workflow.subgraph`
        against. The topology is still valid, so this is a WARNING, not a
        finding — but it must never be silent: a subgraph that produced
        nothing would otherwise look like a working graph."""
        document = {
            "version": 2,
            "name": "mounts-a-child",
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
                {
                    "id": "sub1",
                    "type": "workflow.subgraph",
                    "data": {"workflow": "somewhere-else"},
                    "position": {"x": 0, "y": 0},
                },
                {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 0, "y": 0}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "sub1", "portId": "prompt"},
                },
                {
                    "source": {"nodeId": "sub1", "portId": "result"},
                    "target": {"nodeId": "out1", "portId": "result"},
                },
            ],
        }

        result = WorkflowArtifacts().compile(document)

        assert result["validated"] is True
        assert any("somewhere-else" in w for w in result["warnings"])

    def test_a_clean_document_warns_about_nothing(self) -> None:
        assert WorkflowArtifacts().compile(_linear_document())["warnings"] == []

    def test_compiling_writes_nothing_to_the_workflows_root(
        self, services: WorkflowServices
    ) -> None:
        """The property the whole stateless story rests on."""
        before = sorted(services.store.root.iterdir())

        WorkflowArtifacts().compile(_linear_document(), name="Linear")

        assert sorted(services.store.root.iterdir()) == before == []


class TestDraftsOnlyWrites:
    """The optional convenience path, and its guardrails."""

    def test_a_save_of_an_invalid_document_refuses_and_returns_findings(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)

        result = library.save_draft("bad-one", "Bad One", {"version": 2, "nodes": []})

        assert result["saved"] is False
        assert result["findings"] == ["The document needs a non-empty 'nodes' list."]
        assert not (services.store.root / "bad-one").exists()

    def test_a_valid_document_is_written_as_an_unpublished_draft(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)

        result = library.save_draft("good-one", "Good One", _linear_document())

        assert result["saved"] is True
        assert result["published"] is False
        payload = json.loads((services.store.root / "good-one" / "workflow.json").read_text())
        assert payload["published"] is False
        assert payload["document"]["nodes"][0]["id"] == "in1"

    def test_omitting_the_slug_mints_one_rather_than_replacing_a_draft(
        self, services: WorkflowServices
    ) -> None:
        """Ticket 20. An agent asked to "save this as My Workflow" that
        invents `my-workflow` is guessing, and a guess landing on somebody's
        existing draft replaces it. `slug=None` asks the store instead."""
        library = WorkflowLibrary(services)

        first = library.save_draft(None, "My Workflow", _linear_document())
        second = library.save_draft(None, "My Workflow", _linear_document())

        assert first["slug"] == "my-workflow"
        assert second["saved"] is True
        assert second["slug"] != first["slug"]
        assert second["slug"].startswith("my-workflow-")
        assert (services.store.root / first["slug"] / "workflow.json").is_file()
        assert (services.store.root / second["slug"] / "workflow.json").is_file()

    def test_it_refuses_to_overwrite_a_published_workflow(
        self, services: WorkflowServices
    ) -> None:
        """A human published it. MCP does not get to change what customers
        are already talking to."""
        library = WorkflowLibrary(services)
        library.save_draft("live-one", "Live One", _linear_document())
        services.store.set_published("live-one", True)

        result = library.save_draft("live-one", "Live One", _linear_document())

        assert result["saved"] is False
        assert any("published" in f for f in result["findings"])

    def test_a_slug_escaping_the_workflows_root_is_refused(
        self, services: WorkflowServices
    ) -> None:
        result = WorkflowLibrary(services).save_draft(
            "../escape", "Escape", _linear_document()
        )

        assert result["saved"] is False
        # The refusal must be about the *slug*, not about the document — which
        # is valid here. A truthy-findings assertion passed either way, so it
        # could not tell a path guard from an unrelated validation error.
        assert any("../escape" in finding for finding in result["findings"])


class TestLibraryReads:
    def test_listing_reports_drafts_with_their_published_flag(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)
        library.save_draft("one", "One", _linear_document())

        rows = library.list_workflows()

        assert [r["slug"] for r in rows] == ["one"]
        assert rows[0]["published"] is False

    def test_the_chat_surface_hides_unpublished_drafts(
        self, services: WorkflowServices
    ) -> None:
        WorkflowLibrary(services).save_draft("one", "One", _linear_document())

        assert WorkflowLibrary(services).list_workflows(surface="chat") == []

    def test_describing_a_workflow_returns_its_document_and_findings(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)
        library.save_draft("one", "One", _linear_document())

        described = library.describe("one")

        assert described["document"]["nodes"][0]["type"] == "input.text"
        assert "findings" in described

    def test_describing_an_unknown_slug_is_an_error_payload_not_a_crash(
        self, services: WorkflowServices
    ) -> None:
        described = WorkflowLibrary(services).describe("nope")

        assert "nope" in described["error"]

    def test_knowledge_returns_the_topic_index_when_no_topic_is_named(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)
        library.save_draft("one", "One", _linear_document())
        knowledge_dir = services.store.root / "one" / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "album.md").write_text("# Album\n\nOne row per album.\n")

        index = library.knowledge("one")

        assert index["topics"] == [{"name": "album", "hint": "Album"}]
        assert index["body"] is None

    def test_knowledge_returns_the_doc_when_a_topic_is_named(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)
        library.save_draft("one", "One", _linear_document())
        knowledge_dir = services.store.root / "one" / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "album.md").write_text("# Album\n\nOne row per album.\n")

        assert "One row per album" in library.knowledge("one", "album")["body"]

    def test_an_unknown_topic_answers_with_the_menu_not_a_bare_miss(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)
        library.save_draft("one", "One", _linear_document())
        knowledge_dir = services.store.root / "one" / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "album.md").write_text("# Album\n")

        result = library.knowledge("one", "nonesuch")

        assert "nonesuch" in result["error"]
        assert result["topics"] == [{"name": "album", "hint": "Album"}]

    def test_plugin_export_reports_the_manifest_and_the_lossy_edges(
        self, services: WorkflowServices
    ) -> None:
        library = WorkflowLibrary(services)
        library.save_draft("one", "One", _linear_document())

        export = library.plugin_export("one")

        assert export["manifest"]["name"] == "one"
        assert "paths" in export and "notes" in export


class TestRuns:
    """The only tool that can touch a model — and a deployment may disable it."""

    def test_it_runs_a_posted_document_with_no_provider_key_configured(
        self, services: WorkflowServices, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No live model is contacted: this document has no model-calling
        node, so `init_chat_model` builds a client nothing ever invokes."""
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(var, raising=False)

        result = WorkflowRuns(services).run(document=_linear_document(), question="hello")

        assert result["answer"] == "hello"
        assert result["mermaid"].strip()

    def test_it_refuses_an_invalid_document_before_reaching_a_model(
        self, services: WorkflowServices, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """*Before reaching a model* was the claim, and nothing tested it.

        Two truthiness assertions passed whether the refusal came from
        validation or from a provider error three layers down — and on a
        machine with no key configured, the second is exactly what a broken
        order of operations would produce (reviews-2026-08-14 ticket 09). So
        the model builder is poisoned: reaching it at all is the failure.
        """
        import openstategraph.chat_model as chat_model

        def never(*_: Any, **__: Any) -> Any:
            raise AssertionError("an invalid document reached the model")

        monkeypatch.setattr(chat_model, "build_chat_model", never)

        result = WorkflowRuns(services).run(document={"version": 2, "nodes": []}, question="hi")

        assert result["error"] == "The document does not compile."
        assert result["findings"] == ["The document needs a non-empty 'nodes' list."]

    def test_it_runs_a_saved_slug(self, services: WorkflowServices) -> None:
        WorkflowLibrary(services).save_draft("one", "One", _linear_document())

        assert WorkflowRuns(services).run(slug="one", question="hi")["answer"] == "hi"

    def test_it_needs_either_a_slug_or_a_document(
        self, services: WorkflowServices
    ) -> None:
        error = WorkflowRuns(services).run(question="hi")["error"]

        # It must say which two things, or it is not an answer to the caller.
        assert "slug" in error and "document" in error

    def test_the_recursion_limit_is_bounded_server_side(
        self, services: WorkflowServices
    ) -> None:
        """`recursion_limit` counts supersteps, not iterations, and an
        unbounded one from an untrusted client is a denial-of-service knob."""
        result = WorkflowRuns(services).run(
            document=_linear_document(), question="hi", recursion_limit=10_000
        )

        assert result["recursion_limit"] <= WorkflowRuns.MAX_RECURSION_LIMIT

    def test_disabling_runs_removes_the_tool_from_the_registry(
        self, services: WorkflowServices
    ) -> None:
        """A deployment with no model key — the core compile loop needs
        none — closes the one tool that would need one."""
        server = build_mcp_server(services, allow_runs=False)

        names = {tool.name for tool in asyncio.run(server.list_tools())}

        assert "run_workflow" not in names
        assert "compile_workflow" in names
