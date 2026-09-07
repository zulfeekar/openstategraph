"""The wiring page's central example is executed, not described.

`ship-it/48`. The defect this page exists to fix is that no page answered
"how do I wire this into my app, streamed, with the username carried through".
The defect a *documentation* fix has is that it is true the day it is written
and false a week later — which is why this module does not read the page for
sentences. It extracts the one fenced block the page marks as executable,
`exec`s it verbatim, and drives it against a real compiled graph with a
scripted model.

**No provider is called.** `RespondingModel` is the suite's scripted chat
model, so this proves the *wiring* — that tokens stream, that identity reaches
the graph's config, that the finished state arrives exactly once — and proves
nothing about answer quality. A live model would prove the same wiring more
slowly.

The second half pins the two claims the snippet cannot make about itself: that
the config it builds carries the same four `configurable` keys `ask()` builds,
and that the initial state it seeds is the one `ask()` seeds. Those are
knowledge owned by `loader.py`; a page restating them is a copy, and a copy
with no way to fail is how this repository's own prose has been wrong three
times.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from openstategraph import load_workflow

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "wiring-it-in.md"

#: The page marks its executable block with this comment. A marker rather than
#: "the first python fence", so reordering the page cannot silently point this
#: test at prose.
MARKER = "<!-- executed verbatim by backend/tests/test_wiring_page_streams.py -->"


def _marked_block() -> str:
    text = PAGE.read_text()
    assert MARKER in text, f"{PAGE.name} lost the marker naming this test"
    after = text.split(MARKER, 1)[1]
    match = re.search(r"```python\n(.*?)```", after, re.DOTALL)
    assert match, "no python fence follows the marker"
    return match.group(1)


def _stream_answer() -> Any:
    namespace: dict[str, Any] = {}
    exec(compile(_marked_block(), str(PAGE), "exec"), namespace)  # noqa: S102
    assert "stream_answer" in namespace, "the marked block must define stream_answer"
    return namespace["stream_answer"]


# ----------------------------------------------------------- a real package


def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


DOCUMENT = {
    "version": 2,
    "name": "Wiring Demo",
    "nodes": [
        _node("in1", "input.text"),
        _node("a1", "agent.llm", instruction="Answer briefly."),
        _node("out1", "output.formatted"),
    ],
    "edges": [
        _edge("in1", "text", "a1", "prompt"),
        _edge("a1", "result", "out1", "result"),
    ],
}

ANSWER = "Forty two, briefly."


@pytest.fixture
def workflow(tmp_path: Path) -> Any:
    directory = tmp_path / "wiring-demo"
    directory.mkdir()
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": "wiring-demo", "savedAt": "", "document": DOCUMENT})
    )
    loaded = load_workflow(directory, model=RespondingModel([], default=ANSWER))
    assert not loaded.warnings, loaded.warnings
    yield loaded
    loaded.close()


def _frames(workflow: Any, **identity: Any) -> list[dict[str, Any]]:
    stream_answer = _stream_answer()

    async def collect() -> list[dict[str, Any]]:
        return [
            frame
            async for frame in stream_answer(workflow, "How many?", **identity)
        ]

    return asyncio.run(collect())


class TestTheSnippetRuns:
    def test_it_streams_tokens_and_they_rebuild_the_answer(self, workflow: Any) -> None:
        frames = _frames(workflow, thread_id="t-1")

        tokens = [f["text"] for f in frames if f["type"] == "token"]
        assert tokens, "no token frames — the page promises a stream"
        assert "".join(tokens) == ANSWER

    def test_the_finished_state_arrives_exactly_once(self, workflow: Any) -> None:
        frames = _frames(workflow, thread_id="t-2")

        answers = [f for f in frames if f["type"] == "answer"]
        assert len(answers) == 1, f"expected one answer frame, got {len(answers)}"
        assert answers[0]["answer"] == ANSWER
        # `outputs` is the per-node half the page tells a reader to expect.
        assert answers[0]["outputs"]["a1"] == ANSWER

    def test_node_frames_name_document_nodes_and_nothing_else(self, workflow: Any) -> None:
        frames = _frames(workflow, thread_id="t-3")

        named = {f["node"] for f in frames if f["type"] == "node"}
        assert named == {"in1", "a1", "out1"}, (
            "a node frame named something that is not a node in the document — "
            "the middleware and model steps emit on_chain_start too"
        )


class TestIdentityReachesTheGraph:
    def test_all_four_configurable_keys_are_carried(self, workflow: Any) -> None:
        """The page's §4 table claims four keys; the snippet must build four."""
        seen: dict[str, Any] = {}
        original = workflow.graph.astream_events

        def capture(initial: Any, config: Any, **kwargs: Any) -> Any:
            seen["initial"] = initial
            seen["config"] = config
            return original(initial, config, **kwargs)

        object.__setattr__(workflow, "graph", _Spy(workflow.graph, capture))
        _frames(workflow, thread_id="t-4", user_email="ada@example.com", session_id="tab-7")

        configurable = seen["config"]["configurable"]
        assert configurable["thread_id"] == "t-4"
        assert configurable["user_email"] == "ada@example.com"
        assert configurable["session_id"] == "tab-7"
        # The one key the page says needs no argument.
        assert configurable["workflow_slug"] == "wiring-demo"

    def test_the_workflow_slug_is_not_the_callers_to_pass(self, workflow: Any) -> None:
        frames = _frames(workflow, thread_id="t-5")
        assert [f for f in frames if f["type"] == "answer"], "ran without a slug argument"


class _Spy:
    """`graph`, with `astream_events` replaced. Everything else passes through."""

    def __init__(self, inner: Any, replacement: Any) -> None:
        self._inner = inner
        self.astream_events = replacement

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ------------------------------- the page does not get to restate loader.py


def _ask_source() -> str:
    import inspect

    from openstategraph.loader import CompiledWorkflow

    return inspect.getsource(CompiledWorkflow.ask)


def _dict_literal_keys(source: str, needle: str) -> set[str]:
    """Keys of the first dict literal in `source` containing `needle`."""
    for node in ast.walk(ast.parse(source.strip())):
        if isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == needle for k in node.keys
        ):
            return {k.value for k in node.keys if isinstance(k, ast.Constant)}
    raise AssertionError(f"no dict literal keyed {needle!r} found")


class TestThePageMatchesTheLibrary:
    def test_the_seeded_state_is_the_state_ask_seeds(self) -> None:
        page = _dict_literal_keys(_marked_block(), "question")
        library = _dict_literal_keys(_ask_source(), "question")

        assert page == library, (
            "the page seeds a different initial state than `ask()` does — "
            f"page {sorted(page)}, loader {sorted(library)}"
        )

    def test_the_configurable_keys_are_the_ones_ask_builds(self) -> None:
        page = _dict_literal_keys(_marked_block(), "thread_id")
        library = _dict_literal_keys(_ask_source(), "thread_id")

        assert page == library, (
            "the page's `configurable` has drifted from `ask()`'s — "
            f"page {sorted(page)}, loader {sorted(library)}"
        )


class TestThePageSaysTheThreeThings:
    """The ticket names three things; a missing one must fail, not read as prose."""

    def test_it_names_both_integration_shapes_before_anything_else(self) -> None:
        text = PAGE.read_text()
        shapes = text.index("Which of the two shapes you are in")
        assert shapes < text.index("stream_answer"), "the shapes must come first"
        assert "Host our server" in text and "Embed the library" in text

    def test_the_identity_table_carries_all_four_keys_with_their_namespaces(self) -> None:
        text = PAGE.read_text()
        for key in ("thread_id", "user_email", "session_id", "workflow_slug"):
            assert f"`{key}`" in text, f"the identity table does not mention {key}"
        assert '("memories", <email>)' in text
        assert '("workflow-memory", <slug>)' in text

    def test_episodic_memory_is_named_absent_and_not_pinned_on_the_checkpointer(self) -> None:
        """`memory.py` retracted that label; a page must not restore it."""
        text = PAGE.read_text()
        episodic = re.search(r"\*\*Episodic\*\*.*", text)
        assert episodic, "the page must name episodic memory so its absence is findable"
        assert "absent, deliberately" in episodic.group(0)
        assert "checkpointer" not in episodic.group(0)
