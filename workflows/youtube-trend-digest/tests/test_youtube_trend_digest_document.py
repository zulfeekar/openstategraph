"""The flagship — two providers, three tools, one paid call.

Gallery example 16, wired exactly as the ticket-01 research concluded. Four
things are settled here without spending a token:

- **The chain.** Trend finder → transcript reader → synthesis, in that order,
  because `agent.prompt` takes exactly one edge: the reader cannot receive both
  the question and the trend report, so the trend report *is* its question, and
  the reader must carry the trend context forward for the synthesis to see it.
- **The provider split.** `settings.model` stays on Ollama cloud and exactly
  one node overrides it. That override is the only place this gallery spends
  money, so a second one appearing is a change somebody must mean.
- **The spelling trap**, which is the reason this test exists at all: a
  document-level model uses the **colon** `init_chat_model` form and a node's
  own `data.model` uses the **slash** selection form. Both are strings, both
  look plausible, and the wrong one fails at run time in a model call rather
  than at compile time. This document is the first shipped one to set a
  per-node model, so the trap is pinned here.
- **The tool that does not exist as a URL.** `tool.youtube-transcript` is bound
  to the reader, and `tool.web-search` is bound to *both* agents from one node
  — its `tool` port is `maxConnections: null`, so it fans out.

Whether the web actually answers today is what the smoke run records; that is
the one thing a test must not pretend to know.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.package_testing import assert_document_shape, load_document

PACKAGE = Path(__file__).resolve().parents[1]

#: The paid node's model, in the slash form a node's own `data.model` takes.
SYNTHESIS_MODEL = "anthropic/claude-haiku-4-5"


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


@pytest.fixture(scope="module")
def plan(doc: dict):
    return WorkflowCompiler().plan(doc)


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """The *workflow default* is the pin; the paid node's override is asserted
    separately below, and the two spellings are the trap this file exists for.
    `openstategraph.package_testing` owns the reasons for each check."""
    assert_document_shape(doc)


def test_the_chain_is_find_then_read_then_synthesise(plan) -> None:
    assert sorted(plan.edges) == [
        ("in1", "trend1"),
        ("read1", "synth1"),
        ("synth1", "out1"),
        ("trend1", "read1"),
    ]
    assert plan.entry == ["in1"]
    assert plan.exits == ["out1"]


def test_each_agent_holds_the_tools_its_step_needs(plan) -> None:
    """And `t-search` is bound twice from one node — the fan-out that saves a
    second search card (`tool` is `maxConnections: null`)."""
    assert plan.tool_bindings == {
        "trend1": ["t-search", "t-fetch"],
        "read1": ["t-transcript", "t-search"],
    }


def test_the_transcript_atom_is_the_one_built_for_this(doc: dict) -> None:
    """`web_fetch` is GET-only and the only working transcript route is a JSON
    POST to InnerTube followed by a GET of the URL that answer issues. That is
    not expressible as a `url` argument, which is why this atom exists
    (gallery ticket 09)."""
    atom = next(n for n in doc["nodes"] if n["type"] == "tool.youtube-transcript")
    assert atom["data"] == {"language": "en", "allowAutoCaptions": True, "maxChars": 8000}


class TestTheProviderSplit:
    def test_exactly_one_node_overrides_the_model(self, doc: dict) -> None:
        overrides = {
            n["id"]: n["data"]["model"]
            for n in doc["nodes"]
            if str(n.get("data", {}).get("model") or "").strip()
        }
        assert overrides == {"synth1": SYNTHESIS_MODEL}

    def test_the_node_model_uses_the_slash_form(self, doc: dict) -> None:
        """`NodeRuntime._base_model` partitions a node's `data.model` on `/`
        and rebuilds `f"{provider}:{model_id}"`. A colon here would resolve to
        the provider `"anthropic:claude-haiku-4-5"`, which is not a provider."""
        model = next(n for n in doc["nodes"] if n["id"] == "synth1")["data"]["model"]
        provider, slash, model_id = model.partition("/")
        assert slash == "/"
        assert provider == "anthropic"
        assert model_id == "claude-haiku-4-5"

    def test_the_document_names_no_model_at_all(self, doc: dict) -> None:
        """The split is now *one* override against the instance default.

        This asserted the document's own `settings.model` was in **colon**
        form, the other half of the slash/colon trap above. The document has no
        model since install-experience T10: every shipped example dropped its
        pin so a copied example runs on whatever the adopter installed, and
        this repository pins its own runs in `openstategraph.yaml`.

        The trap the pair guarded is unchanged and still guarded, because it
        was never symmetric — the *node* field is the one that partitions on
        `/`, and that assertion is directly above.
        """
        assert not doc["settings"].get("model")

    def test_the_paid_node_holds_no_tools(self, plan) -> None:
        """One call, one price. A tool on the synthesis node makes the paid
        step a loop of unknown length."""
        assert "synth1" not in plan.tool_bindings


class TestTheReaderCarriesTheTrendForward:
    def test_the_synthesis_reads_only_the_reader(self, doc: dict) -> None:
        """`agent.prompt` is `maxConnections: 1`, so `synth1` sees exactly one
        upstream. If the reader stopped restating the trend block, the paid
        call would be handed a transcript with nothing to place it against —
        and would still produce three fluent sentences. That is why the
        reader's prompt names the two blocks and why this is asserted."""
        into_synth = [e for e in doc["edges"] if e["target"]["nodeId"] == "synth1"]
        assert len(into_synth) == 1
        assert into_synth[0]["source"]["nodeId"] == "read1"

    def test_both_blocks_are_named_on_both_sides(self, doc: dict) -> None:
        by_id = {n["id"]: n for n in doc["nodes"]}
        writer = by_id["read1"]["data"]["systemPrompt"]
        reader = by_id["synth1"]["data"]["systemPrompt"]
        for block in ("TREND", "TRANSCRIPT"):
            assert block in writer, block
            assert block in reader, block

    def test_the_reader_is_told_not_to_invent_one(self, doc: dict) -> None:
        prompt = next(n for n in doc["nodes"] if n["id"] == "read1")["data"]["systemPrompt"]
        assert "verbatim" in prompt
        assert "Never write a transcript you were not given." in prompt
