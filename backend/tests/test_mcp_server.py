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
import re
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
from openstategraph.api.audience import Audience


_GRAMMAR_START = "and the rest. The grammar:"
_GRAMMAR_END = "The list is read from the same registry"


def _enumerated_types() -> set[str]:
    """Every `family.name` the guide's node-type enumeration comment names."""
    guide = (Path(__file__).resolve().parents[2] / "docs" / "mcp.md").read_text()
    if _GRAMMAR_START not in guide or _GRAMMAR_END not in guide:
        return set()
    block = guide.split(_GRAMMAR_START, 1)[1].split(_GRAMMAR_END, 1)[0]
    return set(re.findall(r"\b([a-z]+\.[a-z0-9-]+[a-z0-9])\b", block))


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

    def test_it_publishes_the_data_schema_for_a_tool_node(self) -> None:
        """launch-readiness/18: a client must not have to guess config keys.

        `tool.sql-query` requires `database`; the vocabulary must say so
        directly rather than leave it to the prose description.
        """
        by_type = {n["type"]: n for n in NodeVocabulary().describe()["node_types"]}

        fields = {f["key"]: f for f in by_type["tool.sql-query"]["fields"]}
        assert "database" in fields
        assert fields["database"]["required"] is True
        assert fields["database"]["kind"] == "text"

    def test_every_node_type_publishes_a_fields_list(self) -> None:
        """Pins the fix at the layer that would silently regress: a new node
        type with no `fields` key at all must fail this, not just be missing
        from a hand-picked spot check."""
        for node in NodeVocabulary().describe()["node_types"]:
            assert "fields" in node, node["type"]
            assert isinstance(node["fields"], list)

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

    def test_the_guide_names_no_type_the_payload_does_not_carry(self) -> None:
        """The other direction, which the sentence above the list claims and
        this file did not check (docs-and-gaps/24).

        `docs/mcp.md` said the test "fails if this enumeration and that
        registry disagree in either direction" while exactly one set was
        computed, so a type deleted from the registry stayed in the guide
        forever and a composing client kept being told it could place one.
        A false claim about an instrument is worse than a false claim,
        because it is the reason a sweep skips the list.

        Scoped to the enumeration comment rather than the whole page on
        purpose: §2 teaches by *inventing* `output.text` and watching the
        compiler refuse it, and a gate that fails on a deliberate
        counter-example is a gate somebody deletes.
        """
        enumerated = _enumerated_types()
        listed = {n["type"] for n in NodeVocabulary().describe()["node_types"]}

        invented = sorted(enumerated - listed)
        assert invented == [], (
            "docs/mcp.md enumerates node types the vocabulary payload does "
            f"not carry, so a client cannot place them: {invented}"
        )

    def test_the_guide_quotes_the_prompt_contract_the_server_sends(self) -> None:
        """docs-and-gaps/24, and the worst finding in that sweep.

        `docs/mcp.md`'s sample carried the sentence *"An EMPTY
        preamble/contract means this node type locks nothing: its prompt is
        entirely yours"* — the exact sentence the server retracted, because
        `agent.llm` locks neither and the base prepends 289 characters of
        rules anyway. `test_it_no_longer_says_an_empty_contract_means_nothing_is_locked`
        pinned the server's copy and nothing pinned the guide's, so the
        retracted claim went on being published *to the audience that acts on
        it*: a model composing a document reads this page.

        Quoted verbatim rather than paraphrased, so the two cannot part
        again.
        """
        guide = (
            Path(__file__).resolve().parents[2] / "docs" / "mcp.md"
        ).read_text()
        by_type = {n["type"]: n for n in NodeVocabulary().describe()["node_types"]}
        contract = by_type["agent.llm"]["prompt_contract"]

        assert contract["editable"] in guide, (
            "docs/mcp.md prints a `prompt_contract.editable` the server does "
            "not send; a composing model is being taught the wrong contract"
        )
        assert "default_rules" in guide

    def test_the_enumeration_comment_was_actually_found(self) -> None:
        """Both directions compare against this block. If the comment is
        reworded away, the parse returns nothing and the two assertions above
        start passing on emptiness."""
        assert len(_enumerated_types()) > 30


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

    def test_the_shipped_sql_qa_example_is_not_accused_of_missing_tools(self) -> None:
        """`launch-readiness` 17. `sql-qa`'s three tool nodes
        (`tool.sql-list-tables`, `tool.sql-get-schema`, `tool.sql-query`) are
        `SQL_EXPLORER_TOOLS` — process-wide built-ins, not a package-local
        `tools/` discovery. Resolving them needs no workflow root and no
        slug, so this stateless door can and must bind them exactly as the
        CLI's `validate` does, which reports this same document `VALID` with
        every tool bound. Before the fix, `compile_workflow` bound an empty
        tool registry and reported all three as unimplemented — an
        accusation a client model could never satisfy, since the document
        was correct all along.
        """
        from openstategraph import examples

        document = examples.get("sql-qa").document()

        result = WorkflowArtifacts().compile(document)

        assert result["validated"] is True
        assert not any("No implementation for tool" in w for w in result["warnings"])

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

    def test_the_compile_envelope_can_be_passed_straight_through_as_document(
        self, services: WorkflowServices
    ) -> None:
        """Ticket 22. `compile_workflow` returns
        `{version, name, savedAt, published, document}` — the obvious thing to
        do with that output is hand it straight to `save_workflow_draft` as
        `document`, without re-supplying `name` a second time. That envelope
        already carries the name; the save must read it from there."""
        envelope = WorkflowArtifacts().compile(_linear_document(), name="Linear")["document"]
        library = WorkflowLibrary(services)

        result = library.save_draft("chinook-questions", None, envelope)

        assert result["saved"] is True, result["findings"]
        payload = json.loads(
            (services.store.root / "chinook-questions" / "workflow.json").read_text()
        )
        assert payload["name"] == "Linear"
        assert payload["document"]["nodes"][0]["id"] == "in1"

    def test_an_explicit_name_still_overrides_the_envelopes_own_name(
        self, services: WorkflowServices
    ) -> None:
        envelope = WorkflowArtifacts().compile(_linear_document(), name="Linear")["document"]
        library = WorkflowLibrary(services)

        result = library.save_draft("chinook-questions", "Renamed", envelope)

        assert result["saved"] is True
        payload = json.loads(
            (services.store.root / "chinook-questions" / "workflow.json").read_text()
        )
        assert payload["name"] == "Renamed"

    def test_a_malformed_document_inside_the_envelope_shape_is_still_refused(
        self, services: WorkflowServices
    ) -> None:
        """Tolerant reading is not permission to skip validation: an envelope
        whose inner document is malformed must still be refused, not written
        because it superficially resembles a compile envelope."""
        library = WorkflowLibrary(services)
        fake_envelope = {
            "version": 1,
            "name": "Looks legit",
            "savedAt": "2026-08-24T00:00:00Z",
            "published": False,
            "document": {"version": 2, "nodes": []},
        }

        result = library.save_draft("bad-envelope", None, fake_envelope)

        assert result["saved"] is False
        assert result["findings"] == ["The document needs a non-empty 'nodes' list."]
        assert not (services.store.root / "bad-envelope").exists()

    def test_the_mcp_tool_itself_accepts_the_envelope_with_no_name_argument(
        self, services: WorkflowServices
    ) -> None:
        """The exact shape of the reported bug: calling the actual MCP tool
        (not the library directly) with `slug` and `document` only, the way a
        client composing `compile_workflow` -> `save_workflow_draft` would,
        must not raise a pydantic 'name Field required' error."""
        server = build_mcp_server(services)
        envelope = WorkflowArtifacts().compile(_linear_document(), name="Linear")["document"]

        result = asyncio.run(
            server.call_tool(
                "save_workflow_draft", {"slug": "chinook-questions", "document": envelope}
            )
        )

        content = result[1] if isinstance(result, tuple) else result
        assert content.get("saved") if isinstance(content, dict) else True

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

        result = WorkflowRuns(services).run(
            document=_linear_document(), question="hello", audience=Audience.CUSTOMER
        )

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

        result = WorkflowRuns(services).run(
            document={"version": 2, "nodes": []}, question="hi", audience=Audience.CUSTOMER
        )

        assert result["error"] == "The document does not compile."
        assert result["findings"] == ["The document needs a non-empty 'nodes' list."]

    def test_it_runs_a_saved_slug(self, services: WorkflowServices) -> None:
        WorkflowLibrary(services).save_draft("one", "One", _linear_document())

        answer = WorkflowRuns(services).run(
            slug="one", question="hi", audience=Audience.CUSTOMER
        )["answer"]
        assert answer == "hi"

    def test_it_needs_either_a_slug_or_a_document(
        self, services: WorkflowServices
    ) -> None:
        error = WorkflowRuns(services).run(question="hi", audience=Audience.CUSTOMER)["error"]

        # It must say which two things, or it is not an answer to the caller.
        assert "slug" in error and "document" in error

    def test_the_recursion_limit_is_bounded_server_side(
        self, services: WorkflowServices
    ) -> None:
        """`recursion_limit` counts supersteps, not iterations, and an
        unbounded one from an untrusted client is a denial-of-service knob."""
        result = WorkflowRuns(services).run(
            document=_linear_document(),
            question="hi",
            recursion_limit=10_000,
            audience=Audience.CUSTOMER,
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

    def test_an_unrouted_revise_reaches_this_doors_warnings_too(
        self, services: WorkflowServices, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`workflow-gallery` 31's run-time channel, and the door it missed.

        `/api/runs`, `/api/runs/stream` and the library door
        (`load_workflow`) all assemble their `warnings` through
        `run_health_from_state`, so a grader whose `revise` verdict reached no
        wired edge is reported on every one of them (`unrouted_decision_
        warnings`, folded into `RunHealth.silent`). This tool — the one door
        a customer's own LLM actually calls to run a workflow — builds its
        `warnings` from `plan.warnings + runtime_warnings(runtime)` alone and
        never reads `final` at all, so the same silent verdict that is
        reported everywhere else ships wordlessly here.
        """
        import openstategraph.compile.workflow_compiler as wc

        real_build = wc.WorkflowCompiler.build

        def _fake_build(self: Any, *args: Any, **kwargs: Any) -> Any:
            graph = real_build(self, *args, **kwargs)

            async def _invoke(*_a: Any, **_k: Any) -> dict[str, Any]:
                # What a real run produces when a grader's `revise` verdict
                # reaches no wired edge: the fallback still ships `pass`, and
                # `unrouted` is the record that it did (workflow-gallery 31).
                return {
                    "answer": "a draft the grader rejected",
                    "decisions": {"grader1": "revise"},
                    "outputs": {},
                    "unrouted": {"grader1": "revise"},
                }

            graph.ainvoke = _invoke  # type: ignore[method-assign]
            return graph

        monkeypatch.setattr(wc.WorkflowCompiler, "build", _fake_build)

        evaluator_optimizer = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "openstategraph"
                / "examples"
                / "evaluator-optimizer"
                / "workflow.json"
            ).read_text()
        )["document"]
        # The ticket's own repro: the same document with its `revise` edge
        # removed, so `grader1`'s only wired destination is `pass`.
        evaluator_optimizer["edges"] = [
            e
            for e in evaluator_optimizer["edges"]
            if e["source"] != {"nodeId": "grader1", "portId": "revise"}
        ]

        # A developer audience, deliberately: `warnings` is the authoring
        # channel and this door only carries it for one
        # (`the-boundary-nobody-checked/08`).
        result = WorkflowRuns(services).run(
            document=evaluator_optimizer, question="hi", audience=Audience.DEVELOPER
        )

        assert result["error"] is None, result
        # Deliberately the run-time sentence's own words ("shipped as-is"),
        # not just "grader1" and "revise" — the compile-time UNWIRED_REVISE
        # finding already carries both of those through `runtime_warnings`,
        # so a looser assertion would pass even with `unrouted` never read.
        assert any("shipped as-is" in w for w in result["warnings"]), result["warnings"]

    def test_a_silent_worker_reaches_this_doors_warnings_too(
        self, services: WorkflowServices, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`workflow-gallery` 18/52's fix, on the one door not checked there.

        `run_health_from_state` already folds `silent_node_warnings` into
        `RunHealth.silent`, and since `workflow-gallery` 31 (`87648b5`) this
        tool's `warnings` includes `health.silent` — so the member-level
        sentence a worker's empty answer earns on every other door
        (`/api/runs`, `/api/runs/stream`, `load_workflow`) should already
        reach an MCP client too. Nothing here had actually driven a real
        worker fan-out through this specific door to confirm it.
        """
        import openstategraph.chat_model as chat_model

        from conftest import RespondingModel

        def _member(needle: str):
            return lambda c: "Your role on this team" in c and needle in c

        model = RespondingModel(
            [
                (_member("access on day one"), "Badge, laptop, VPN, repo access."),
                (_member("onboarding agenda"), ""),
            ],
            default="",
        )
        monkeypatch.setattr(chat_model, "build_chat_model", lambda *a, **k: model)

        document = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "openstategraph"
                / "examples"
                / "archetype-orchestrator-report"
                / "workflow.json"
            ).read_text()
        )["document"]

        # Developer: the member-level sentence is an authoring warning, and
        # this door carries `warnings` for one audience only
        # (`the-boundary-nobody-checked/08`).
        result = WorkflowRuns(services).run(
            document=document,
            question=(
                "Research what a new engineer needs access on day one; "
                "write a 30-minute onboarding agenda for them."
            ),
            audience=Audience.DEVELOPER,
        )

        assert result["error"] is None, result
        assert any(
            'Member "task-2" of node "worker-research"' in w
            and "ended the turn without writing anything" in w
            for w in result["warnings"]
        ), result["warnings"]
