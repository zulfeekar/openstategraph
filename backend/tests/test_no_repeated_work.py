"""Work done twice is a defect, not a style question — ticket 05, pass 3.

Every test here pins a *count*, because the behaviour these changes preserve
is already covered elsewhere and the only thing a refactor can silently undo
is the count. A "this is faster now" comment rots; an assertion that a listing
of N documents performs N reads does not.
"""

from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture()
def counted_reads(monkeypatch):
    """Every `Path.read_text` performed inside the block, by path."""
    seen: list[str] = []
    real = pathlib.Path.read_text

    def counting(self: pathlib.Path, *args: Any, **kwargs: Any) -> str:
        seen.append(str(self))
        return real(self, *args, **kwargs)

    with patch.object(pathlib.Path, "read_text", counting):
        yield seen


class TestTheCurationListingReadsEachDocOnce:
    """It read every `knowledge/*.md` **twice**: once through
    `PackageKnowledge.topics()` for the index hint, and again through
    `read_topic()` for the marker and claim hashes. Two full reads of every
    document on every open of the curation panel."""

    def _package(self, tmp_path: pathlib.Path, count: int) -> pathlib.Path:
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir(parents=True)
        for index in range(count):
            (knowledge / f"topic-{index:03}.md").write_text(
                f"# Topic {index}\n\nA sentence about topic {index}."
            )
        return tmp_path

    def test_one_read_per_document(self, tmp_path, counted_reads) -> None:
        from openstategraph.api.knowledge_curation import list_topics

        package = self._package(tmp_path, 12)

        statuses = list_topics(package, {"nodes": [], "edges": []}, tmp_path.parent)

        assert len(statuses) == 12
        knowledge_reads = [p for p in counted_reads if p.endswith(".md")]
        assert len(knowledge_reads) == 12
        assert len(set(knowledge_reads)) == 12

    def test_the_hints_and_flags_are_unchanged(self, tmp_path) -> None:
        from openstategraph.api.knowledge_curation import list_topics

        package = self._package(tmp_path, 3)

        statuses = list_topics(package, {"nodes": [], "edges": []}, tmp_path.parent)

        assert [s.name for s in statuses] == ["topic-000", "topic-001", "topic-002"]
        assert [s.hint for s in statuses] == [
            "Topic 0",
            "Topic 1",
            "Topic 2",
        ]
        assert not any(s.generated or s.stale for s in statuses)


class TestSavingDoesNotReReadWhatItJustWrote:
    def test_the_saved_body_is_reused_not_re_read(self, tmp_path, counted_reads) -> None:
        """`save_topic` composed the file body in memory, wrote it, then read
        the same bytes back off disk purely to extract the hint from them."""
        from openstategraph.api.knowledge_curation import save_topic

        package = tmp_path
        knowledge = package / "knowledge"
        knowledge.mkdir(parents=True)
        # Saved once already, so the *previous*-body read below is real and the
        # count distinguishes it from a read-back.
        (knowledge / "orders.md").write_text("# Orders\n\nFirst.")
        counted_reads.clear()

        status = save_topic(
            package,
            "orders",
            "# Orders\n\nHand written.",
            {"nodes": [], "edges": []},
            tmp_path.parent,
        )

        assert status.hint == "Orders"
        # Exactly one: the previous body, genuinely needed to carry a prior
        # claim hash forward. Never a read-back of the bytes we just wrote.
        assert [p for p in counted_reads if p.endswith("orders.md")] == [
            str(knowledge / "orders.md")
        ]


class TestTheEntryPointScanHappensOncePerProcess:
    """Measured before the change: `runtime_for` cost 14.8 ms steady-state on
    this machine, 12.2 ms of which was `importlib.metadata.entry_points()`
    re-walking every installed distribution's metadata. It ran once per
    `build_tool_registry`, which is once per run, per stream, and again per
    subgraph child — 82% of the call spent rediscovering an answer that cannot
    change without restarting the process.
    """

    def test_the_built_in_and_plugin_layers_are_built_once(
        self, tmp_path, monkeypatch
    ) -> None:
        import importlib.metadata

        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        scans = {"n": 0}
        real = importlib.metadata.entry_points

        def counting(**kwargs: Any) -> Any:
            scans["n"] += 1
            return real(**kwargs)

        monkeypatch.setattr(importlib.metadata, "entry_points", counting)
        store = WorkflowStore(root=tmp_path)

        build_tool_registry(store, None)
        after_first = scans["n"]
        build_tool_registry(store, None)
        build_tool_registry(store, None)

        assert after_first >= 1, "the first build must actually scan"
        assert scans["n"] == after_first

    def test_each_caller_gets_its_own_dict_to_mutate(self, tmp_path) -> None:
        """The cached layer is shared, so handing it out directly would let one
        run's injected tools leak into the next one's registry."""
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        store = WorkflowStore(root=tmp_path)
        first = build_tool_registry(store, None)
        first["tool.not-real"] = object()

        assert "tool.not-real" not in build_tool_registry(store, None)
