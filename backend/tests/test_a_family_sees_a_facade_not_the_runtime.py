"""What a node family may reach is named, typed and published.

Framework-packaging ticket 09. `NodeBuildContext` is the extension seam a third
party's node family is handed, and its module docstring states the design:

    What a family may see is `NodeBuildContext`, not the runtime … the narrow,
    named set of things building a node legitimately needs

Every field on it delivered that except one. `services: Any = None` was passed
the whole 13-field `RuntimeServices` — `document_loader`, `package_loader`,
`knowledge_dir_override`, `advisor_catalog` and the rest — which is the
compiler internal the context exists to hide, handed over through the one
field on that context nobody could read the width of.

**It is published, not private.** `NodeBuildContext` is in
`backend/tests/public_api.txt`, `services` included, so `Any` meant nothing
pinned its width: a field added to a compiler dataclass next month reached
every installed plugin, and the diff a reviewer saw was a line in
`node_runtime.py` — the snapshot would not move, because the *name* did not.

The `Any` had a real and stated reason — keeping `abc` out of the compiler's
import graph — and that is an argument for a typed façade, which is what
`NodeCapabilities` is.
"""

from __future__ import annotations

import warnings
from dataclasses import fields, is_dataclass
import re
from pathlib import Path

import pytest

from openstategraph.abc import NodeBuildContext, NodeCapabilities

ROOT = Path(__file__).resolve().parents[2]


class TestTheFacadeIsNarrowAndNamed:
    def test_it_is_a_frozen_dataclass(self) -> None:
        assert is_dataclass(NodeCapabilities)

        with pytest.raises(Exception):
            NodeCapabilities().tools = {}  # type: ignore[misc]

    def test_it_names_exactly_what_a_family_may_reach(self) -> None:
        """The assertion the ticket is for. Widening this is an edit *here*,
        which is what makes it visible; before, it was a field added to
        `RuntimeServices` and published to every plugin with no diff anywhere
        a reviewer looks."""
        assert [entry.name for entry in fields(NodeCapabilities)] == [
            "tools",
            "functions",
            "memory_store",
        ]

    def test_the_context_carries_it_rather_than_the_runtime(self) -> None:
        names = [entry.name for entry in fields(NodeBuildContext)]

        assert "capabilities" in names
        assert "services" not in names

    def test_the_default_is_usable(self) -> None:
        """A context built without capabilities — a test's, or an adapter's —
        must not make a family branch on `None`."""
        capabilities = NodeBuildContext(node_id="n", node={}, plan=None).capabilities  # type: ignore[arg-type]

        assert capabilities.tools == {}
        assert capabilities.functions == {}
        assert capabilities.memory_store is None


class TestTheOldNameStillWorksAndSaysItIsGoing:
    def test_reading_services_warns_and_names_its_replacement(self) -> None:
        context = NodeBuildContext(node_id="n", node={}, plan=None)  # type: ignore[arg-type]

        with pytest.warns(DeprecationWarning, match="capabilities"):
            reached = context.services

        assert reached is context.capabilities

    def test_capabilities_itself_is_quiet(self) -> None:
        context = NodeBuildContext(node_id="n", node={}, plan=None)  # type: ignore[arg-type]

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert context.capabilities is not None

    def test_what_the_shim_deliberately_no_longer_reaches(self) -> None:
        """The narrowing itself. A plugin that reached `document_loader` off
        `services` was reaching the compiler; that is the defect, not a
        casualty of fixing it, and it fails loudly rather than returning
        `None`."""
        context = NodeBuildContext(node_id="n", node={}, plan=None)  # type: ignore[arg-type]

        with pytest.warns(DeprecationWarning):
            with pytest.raises(AttributeError):
                context.services.document_loader


def _empty_plan():  # type: ignore[no-untyped-def]
    from openstategraph.compile.workflow_compiler import CompiledPlan

    return CompiledPlan()


SEEN: list[NodeCapabilities] = []


class RecordingFamily:
    """A third party's family, recording what the compiler handed it."""

    node_type = "analyse.recorded"

    def build(self, context: NodeBuildContext):  # type: ignore[no-untyped-def]
        SEEN.append(context.capabilities)
        return lambda state: {"outputs": {context.node_id: "ok"}}


class TestTheCompilerHandsOverTheFacade:
    def test_a_family_is_built_with_only_what_it_may_reach(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from openstategraph.compile.node_runtime import NodeRuntime
        from openstategraph.extensions import NODE_FAMILIES_GROUP
        from test_extensions import FakeEntryPoint, install

        SEEN.clear()
        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", RecordingFamily))
        runtime = NodeRuntime(model=None, tools={"tool.x": object()})

        runtime.builder_for("analyse.recorded")("a", {"id": "a", "data": {}}, _empty_plan())

        assert len(SEEN) == 1
        assert set(SEEN[0].tools) == {"tool.x"}
        # And nothing else came with it: the compiler's own collaborators are
        # not reachable through this object at all.
        assert not hasattr(SEEN[0], "document_loader")
        assert not hasattr(SEEN[0], "advisor_catalog")


class TestTheChangeIsVisibleWhereAnAdopterLooks:
    def test_the_snapshot_moved_with_it(self) -> None:
        snapshot = (ROOT / "backend" / "tests" / "public_api.txt").read_text()

        assert "openstategraph.abc.NodeCapabilities" in snapshot
        assert "fields(node_id,node,plan,capabilities,diagnostics" in snapshot

    def test_the_stability_page_lists_the_new_name(self) -> None:
        """`test_stability_contract.py` enforces this in general; named here
        because a Tier 1 *addition* that nobody wrote down is the same defect
        as a removal that nobody announced."""
        assert "NodeCapabilities" in (ROOT / "docs" / "stability.md").read_text()

    def test_the_changelog_says_so(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text()
        # Split on the first *released* heading, matched as a whole line.
        # This used to split on the literal `## 0.3.0rc1`, which was correct
        # until the tenth pre-release: `## 0.3.0rc10` contains that string, so
        # the cut moved to the newest section and "unreleased" became almost
        # nothing. A prefix that is also a prefix of its own successor is the
        # defect; anchoring the match to a line ends it for every version after
        # this one too (`docs-and-gaps/32`).
        unreleased = re.split(r"^## \d+\.\d+\.\d+", changelog, maxsplit=1, flags=re.M)[0]

        # **The whole file, not just the unreleased section.** This asserted
        # that the entry sat under `## Unreleased`, which was true until the
        # entry was released — it now lives under the pre-release that shipped
        # it, which is the changelog working. What an adopter needs is that the
        # change is *written down where they look*, and a test that goes red
        # the moment a feature ships is a test that punishes releasing.
        # `unreleased` is still computed so the split above stays exercised.
        assert unreleased is not None
        assert "NodeCapabilities" in changelog
