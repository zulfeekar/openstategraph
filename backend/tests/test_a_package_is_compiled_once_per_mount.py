"""A package mounted twice is compiled once — `the-cost-of-one-more` 02.

`_subgraph` resolved every mount **site**: it loaded the child document,
applied that mount's overrides, built a child `NodeRuntime` and compiled the
child, with nothing remembering that the site next to it had just done the same
work. The mount graph is a DAG rather than a tree, so a package that mounts the
next one twice, seven levels deep, cost `2^(d+1) - 1` compiles — 255 of them
for eight packages on disk, and the wall clock doubled with every package a
user wrote.

**The fix is a memo with no lifetime, and that distinction is the whole
argument.** `docs/decisions/per-request-compile-cost.md` declined a compiled
graph *cache* — 27 ms warm against an invalidation surface of nine items, one
of which is "every mounted child package, transitively" — and recorded that
"the architecture was never the objection. The invalidation surface is." A memo
that lives inside one `build()` and dies with it has no invalidation surface at
all: nothing it holds can go stale, because nothing it holds outlives the
compile that filled it.

**The key is not the slug.** Two mounts of one package are two *instances*
carrying their own `data.overrides` (`CLAUDE.md`), so the key is `(slug,
overrides, persistence)` — and it is sufficient only because the memo hangs off
the **parent runtime**, which fixes everything else `_subgraph` reads: the
services the child inherits, the ancestry that refuses a cycle, and the
document-level settings a context gap is measured against. A memo shared
across parents would not have that invariant and would be wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"


@pytest.fixture()
def counted(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Count `WorkflowCompiler.build` calls, and keep the documents it saw.

    Exact, and therefore not flaky — which is what a timing assertion here
    would be. The documents are kept because the second half of this ticket is
    that collapsing two builds into one must not collapse two *instances*.
    """
    from openstategraph.compile import workflow_compiler as compiler

    seen: dict[str, Any] = {"builds": 0, "documents": []}
    original = compiler.WorkflowCompiler.build

    def counting(self: Any, document: dict[str, Any], *a: Any, **k: Any) -> Any:
        seen["builds"] += 1
        seen["documents"].append(document)
        return original(self, document, *a, **k)

    monkeypatch.setattr(compiler.WorkflowCompiler, "build", counting)
    return seen


def _leaf() -> dict[str, Any]:
    return {
        "version": 3,
        "name": "leaf",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "a1", "type": "agent.llm", "position": {"x": 1, "y": 0},
             "data": {"systemPrompt": "the package's own"}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 2, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "a1", "portId": "prompt"}},
            {"source": {"nodeId": "a1", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


def _parent(child_slug: str, *, overrides: list[Any] | None = None) -> dict[str, Any]:
    """One document mounting `child_slug` twice."""
    def mount(node_id: str, y: int, override: Any) -> dict[str, Any]:
        data: dict[str, Any] = {"workflow": child_slug}
        if override is not None:
            data["overrides"] = override
        return {"id": node_id, "type": "workflow.subgraph",
                "position": {"x": 1, "y": y}, "data": data}

    first, second = (overrides or [None, None])
    return {
        "version": 3,
        "name": "p",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            mount("m1", 0, first),
            mount("m2", 1, second),
            {"id": "j1", "type": "function.format_report",
             "position": {"x": 2, "y": 0}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 3, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "m1", "portId": "task"}},
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "m2", "portId": "task"}},
            {"source": {"nodeId": "m1", "portId": "answer"},
             "target": {"nodeId": "j1", "portId": "in"}},
            {"source": {"nodeId": "m2", "portId": "answer"},
             "target": {"nodeId": "j1", "portId": "in"}},
            {"source": {"nodeId": "j1", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


def _ladder(root: Path, depth: int) -> Path:
    """`p0` mounts `p1` twice, `p1` mounts `p2` twice, down to a plain leaf."""
    (root / f"p{depth}").mkdir(parents=True)
    (root / f"p{depth}" / "workflow.json").write_text(json.dumps(_leaf()))
    for level in range(depth - 1, -1, -1):
        (root / f"p{level}").mkdir()
        (root / f"p{level}" / "workflow.json").write_text(
            json.dumps(_parent(f"p{level + 1}"))
        )
    return root / "p0"


class TestTwoSitesAreOneCompile:
    def test_the_shipped_two_mount_example_is_two_instances_and_stays_two(
        self, counted: dict[str, Any]
    ) -> None:
        """`same-package-twice` is the example that shows the key is not the
        slug, and it is the one that must **not** collapse.

        Its two mounts of `chained-summarizer` carry different
        `systemPrompt` overrides — one asks for twelve words, the other for an
        analogy — so they are two instances, and two instances are two graphs.
        Three builds is the right answer here and was the right answer before;
        a change that made this two would be `launch-readiness/182`'s defect,
        one instance running another's prompts.
        """
        from openstategraph import load_workflow

        with load_workflow(EXAMPLES / "same-package-twice"):
            pass

        assert counted["builds"] == 3

    def test_the_depth_ladder_is_linear_in_packages_rather_than_exponential(
        self, counted: dict[str, Any], tmp_path: Path
    ) -> None:
        """The ticket's own measurement, as an assertion. Seven levels each
        mounting the next twice used to cost 255 builds; one per package is
        the whole of what there is to build."""
        from openstategraph import load_workflow

        with load_workflow(_ladder(tmp_path, 7)):
            pass

        assert counted["builds"] == 8


class TestAnInstanceKeepsItsOwnOverrides:
    def test_two_mounts_differing_only_by_overrides_are_two_compiles(
        self, counted: dict[str, Any], tmp_path: Path
    ) -> None:
        """The failure a slug-keyed memo would cause, asserted from both ends:
        two builds, and the two child documents carry *different* prompts."""
        from openstategraph import load_workflow

        (tmp_path / "child").mkdir()
        (tmp_path / "child" / "workflow.json").write_text(json.dumps(_leaf()))
        (tmp_path / "top").mkdir()
        (tmp_path / "top" / "workflow.json").write_text(json.dumps(_parent(
            "child",
            overrides=[
                {"a1": {"systemPrompt": "AAA"}},
                {"a1": {"systemPrompt": "BBB"}},
            ],
        )))

        with load_workflow(tmp_path / "top"):
            pass

        prompts = [
            node["data"].get("systemPrompt")
            for document in counted["documents"]
            for node in document["nodes"]
            if node["id"] == "a1"
        ]
        assert counted["builds"] == 3
        assert sorted(prompts) == ["AAA", "BBB"]

    def test_two_mounts_with_the_same_overrides_share_one_compile(
        self, counted: dict[str, Any], tmp_path: Path
    ) -> None:
        """…and the other side of the same key: identical instances are one
        instance, because nothing about them differs."""
        from openstategraph import load_workflow

        same = {"a1": {"systemPrompt": "SAME"}}
        (tmp_path / "child").mkdir()
        (tmp_path / "child" / "workflow.json").write_text(json.dumps(_leaf()))
        (tmp_path / "top").mkdir()
        (tmp_path / "top" / "workflow.json").write_text(
            json.dumps(_parent("child", overrides=[same, dict(same)]))
        )

        with load_workflow(tmp_path / "top"):
            pass

        assert counted["builds"] == 2

    def test_two_mounts_differing_only_by_persistence_are_two_compiles(
        self, counted: dict[str, Any], tmp_path: Path
    ) -> None:
        """`persistence` is the other key member: it is what the child is
        compiled *with* (`mount_checkpointer`), so two modes are two graphs."""
        from openstategraph import load_workflow

        (tmp_path / "child").mkdir()
        (tmp_path / "child" / "workflow.json").write_text(json.dumps(_leaf()))
        document = _parent("child")
        document["nodes"][1]["data"]["persistence"] = "per-thread"
        document["nodes"][2]["data"]["persistence"] = "per-invocation"
        (tmp_path / "top").mkdir()
        (tmp_path / "top" / "workflow.json").write_text(json.dumps(document))

        with load_workflow(tmp_path / "top"):
            pass

        assert counted["builds"] == 3


class TestSharingOneGraphDoesNotSharingOneBox:
    """A memo collapses two *objects*. It must not collapse two *cards*."""

    def test_the_diagram_still_opens_both_mounts(self) -> None:
        from openstategraph import load_workflow

        with load_workflow(EXAMPLES / "same-package-twice") as workflow:
            drawn = workflow.mermaid(xray=True)

        assert "subgraph mount_analogy" in drawn
        assert "subgraph mount_terse" in drawn

    def test_the_compiler_still_records_one_mount_per_site(self) -> None:
        from openstategraph import load_workflow

        with load_workflow(EXAMPLES / "same-package-twice") as workflow:
            recorded = dict(workflow._mounts)

        assert sorted(recorded) == ["mount_analogy", "mount_terse"]

    def test_each_instance_is_still_named_in_its_own_sentence(self) -> None:
        """`launch-readiness` 40's confirmation is keyed by the mount's node
        id, so two sibling mounts say two things. A memo that recorded once
        would silently drop one."""
        from openstategraph import load_workflow

        with load_workflow(EXAMPLES / "same-package-twice") as workflow:
            said = " | ".join(workflow.warnings)

        assert '"mount-analogy" -> "chained-summarizer#shorten1.systemPrompt"' in said
        assert '"mount-terse" -> "chained-summarizer#shorten1.systemPrompt"' in said


class TestTheCycleGuardIsUntouched:
    def test_a_package_that_mounts_itself_is_still_refused(
        self, tmp_path: Path
    ) -> None:
        """The memo is consulted *after* the ancestry check and a refusal is
        never remembered, so a cycle cannot be turned into an infinite loop
        nor into a silently satisfied mount."""
        from openstategraph import load_workflow

        (tmp_path / "selfy").mkdir()
        (tmp_path / "selfy" / "workflow.json").write_text(
            json.dumps(_parent("selfy"))
        )

        with pytest.raises(ValueError, match="mounts itself"):
            load_workflow(tmp_path / "selfy")
