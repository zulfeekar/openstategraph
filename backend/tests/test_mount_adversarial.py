"""Adversarial stress tests for mounts-as-class/instance (QA pass, 2026-08-13).

Each test tries to break the mount/override machinery rather than pin an
intended behaviour. Tests that FAIL are findings, deliberately left failing —
production source was not touched to make them pass. Failing tests are marked
with `xfail(strict=True)` and a FINDING comment so the suite stays green while
the defect stays recorded and visible: if the defect is later fixed, the
strict xfail turns into a hard failure and the marker must be removed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.api.mount_resolution import (
    MountResolutionError,
    resolve_mount_document,
)
from openstategraph.api.workflow_store import WorkflowStore
from openstategraph.compile.node_runtime import NodeRuntime, RunState, apply_mount_overrides
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.workflows_root import WORKFLOWS_ROOT_ENV


def _document(nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"version": 2, "name": "doc", "nodes": nodes, "edges": edges or []}


def _mount(node_id: str, slug: str, overrides: Any = None) -> dict[str, Any]:
    data: dict[str, Any] = {"workflow": slug}
    if overrides is not None:
        data["overrides"] = overrides
    return {"id": node_id, "type": "workflow.subgraph", "position": {"x": 0, "y": 0}, "data": data}


def _agent(node_id: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": "agent.llm", "position": {"x": 0, "y": 0}, "data": data}


def _store(tmp_path: Path, packages: dict[str, dict[str, Any]]) -> WorkflowStore:
    root = tmp_path / "workflows"
    for slug, document in packages.items():
        directory = root / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps({"version": 2, "name": slug, "document": document}, indent=2)
        )
    return WorkflowStore(root=root)


def _node(document: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(n for n in document["nodes"] if n["id"] == node_id)


# ---------------------------------------------------------------------------
# 1. Deep chains: a root-level grandchild override vs the child package's own
# ---------------------------------------------------------------------------


class TestGrandchildOverrideClobbering:
    """A parent package legitimately carries its own overrides on its mounts.

    When the *root* then overrides one grandchild field, the root's override
    is expressed as an override of the child mount's whole `overrides` field.
    Shallow replace means the child package's own overrides for that mount are
    silently discarded — not merged. `MountContext.writeOverride` in the
    editor generates exactly this shape, so a single field edit at depth two
    reverts every OTHER override the child package declared for that mount.
    """

    @pytest.fixture
    def store(self, tmp_path: Path) -> WorkflowStore:
        return _store(
            tmp_path,
            {
                "grandchild": _document(
                    [_agent("deep", rules="package deep", threshold=1)]
                ),
                # The child package itself pins the grandchild's threshold.
                "child": _document(
                    [_mount("wf-inner", "grandchild", {"deep": {"threshold": 9}})]
                ),
                # The root overrides ONE OTHER grandchild field, in exactly the
                # nested shape MountContext.writeOverride produces.
                "parent": _document(
                    [
                        _mount(
                            "wf-music",
                            "child",
                            {"wf-inner": {"overrides": {"deep": {"rules": "root says"}}}},
                        )
                    ]
                ),
            },
        )

    # FINDING (CONFIRMED): overriding one grandchild field from the root
    # silently reverts the child package's own overrides for that mount.
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FINDING: a root-level grandchild override replaces the child "
            "mount's whole `overrides` field, discarding the child package's "
            "own overrides for the same mount (threshold=9 lost)"
        ),
    )
    def test_the_childs_own_grandchild_overrides_survive_a_root_edit(
        self, store: WorkflowStore
    ) -> None:
        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        deep = _node(resolved.document, "deep")
        assert deep["data"]["rules"] == "root says"
        # The child package said threshold=9 for this mount; the root never
        # touched threshold, so 9 must survive.
        assert deep["data"]["threshold"] == 9

    def test_what_actually_happens_the_child_override_is_discarded(
        self, store: WorkflowStore
    ) -> None:
        """The companion pin: today the grandchild runs the PACKAGE default
        (threshold=1) with no warning of any kind."""
        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        deep = _node(resolved.document, "deep")
        assert deep["data"]["rules"] == "root says"
        assert deep["data"]["threshold"] == 1  # child's 9 silently gone
        assert resolved.warnings == []  # and nobody was told


# ---------------------------------------------------------------------------
# 2. Four levels: precedence along the chain
# ---------------------------------------------------------------------------


class TestFourLevelChain:
    @pytest.fixture
    def store(self, tmp_path: Path) -> WorkflowStore:
        return _store(
            tmp_path,
            {
                "d": _document([_agent("leaf", rules="package")]),
                "c": _document([_mount("m3", "d", {"leaf": {"rules": "from c"}})]),
                "b": _document(
                    [
                        _mount(
                            "m2",
                            "c",
                            {"m3": {"overrides": {"leaf": {"rules": "from b"}}}},
                        )
                    ]
                ),
                "a": _document(
                    [
                        _mount(
                            "m1",
                            "b",
                            {
                                "m2": {
                                    "overrides": {
                                        "m3": {"overrides": {"leaf": {"rules": "from a"}}}
                                    }
                                }
                            },
                        )
                    ]
                ),
            },
        )

    def test_the_outermost_override_wins_at_four_levels(self, store: WorkflowStore) -> None:
        resolved = resolve_mount_document(store, "a", ["m1", "m2", "m3"])
        assert _node(resolved.document, "leaf")["data"]["rules"] == "from a"
        assert resolved.slug == "d"

    def test_without_the_outermost_the_next_level_wins(self, store: WorkflowStore) -> None:
        resolved = resolve_mount_document(store, "b", ["m2", "m3"])
        assert _node(resolved.document, "leaf")["data"]["rules"] == "from b"

    def test_inherited_at_depth_three_returns_the_leaf_package_default(
        self, store: WorkflowStore
    ) -> None:
        """`inherited=True` skips the LAST mount's (merged) overrides — which
        at depth 3 includes every ancestor's contribution, so the answer is
        the raw package, not "what b and c would give without a"."""
        resolved = resolve_mount_document(store, "a", ["m1", "m2", "m3"], inherited=True)
        assert _node(resolved.document, "leaf")["data"]["rules"] == "package"


# ---------------------------------------------------------------------------
# 3. Cycles: mutual recursion, at resolve time and at compile time
# ---------------------------------------------------------------------------


class TestCycles:
    def test_mutual_recursion_is_refused_at_resolve_time(self, tmp_path: Path) -> None:
        store = _store(
            tmp_path,
            {
                "ping": _document([_mount("to-pong", "pong")]),
                "pong": _document([_mount("to-ping", "ping")]),
            },
        )
        with pytest.raises(MountResolutionError, match="ping"):
            resolve_mount_document(store, "ping", ["to-pong", "to-ping"])

    def test_direct_self_mount_is_refused_at_compile_time(self) -> None:
        doc = _document([_mount("wf-self", "narcissus")])
        docs = {"narcissus": doc}
        runtime = NodeRuntime(document_loader=docs.__getitem__)
        with pytest.raises(ValueError, match="includes itself"):
            WorkflowCompiler().build(doc, RunState, runtime.factory(doc))

    def test_mutual_recursion_is_refused_at_compile_time(self) -> None:
        ping = _document([_mount("to-pong", "pong")])
        pong = _document([_mount("to-ping", "ping")])
        docs = {"ping": ping, "pong": pong}
        runtime = NodeRuntime(document_loader=docs.__getitem__)
        with pytest.raises(ValueError, match="includes itself"):
            WorkflowCompiler().build(ping, RunState, runtime.factory(ping))

    def test_an_override_can_retarget_a_grandchild_mount_into_a_cycle(
        self, tmp_path: Path
    ) -> None:
        """An override may rewrite `workflow` itself — the mount's target —
        because `workflow` is just a data field. Retargeting into a cycle must
        still be refused by the visited check on the MERGED document."""
        store = _store(
            tmp_path,
            {
                "innocent": _document([_agent("leaf")]),
                "child": _document([_mount("wf-inner", "innocent")]),
                "parent": _document(
                    [_mount("wf-music", "child", {"wf-inner": {"workflow": "parent"}})]
                ),
            },
        )
        with pytest.raises(MountResolutionError, match="parent"):
            resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])

    def test_an_override_can_retarget_a_grandchild_mount_to_any_package(
        self, tmp_path: Path
    ) -> None:
        """The non-cyclic version is ACCEPTED: an override silently swaps
        which package a grandchild mount runs. The edit scope forbids shape
        changes in the UI, but the data path allows this one wholesale."""
        store = _store(
            tmp_path,
            {
                "innocent": _document([_agent("leaf", rules="innocent")]),
                "evil": _document([_agent("leaf", rules="evil")]),
                "child": _document([_mount("wf-inner", "innocent")]),
                "parent": _document(
                    [_mount("wf-music", "child", {"wf-inner": {"workflow": "evil"}})]
                ),
            },
        )
        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        assert resolved.slug == "evil"
        assert _node(resolved.document, "leaf")["data"]["rules"] == "evil"


# ---------------------------------------------------------------------------
# 4. Stale addresses and malformed input at the HTTP seam
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    root = tmp_path / "workflows"
    packages = {
        "child": _document([_agent("agent-sql", rules="package rules")]),
        "parent": _document(
            [_mount("wf-music", "child", {"agent-sql": {"rules": "mine"}})]
        ),
    }
    for slug, document in packages.items():
        directory = root / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps({"version": 2, "name": slug, "document": document}, indent=2)
        )
    monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(root))
    return TestClient(create_app())


class TestHttpSeam:
    # FINDING (CONFIRMED): the endpoint repairs what the frontend refuses.
    # `MountAddress.parseMountAddress` returns null for `parent//wf-music`
    # ("refuses rather than repairs"), but `get_mount_document` filters empty
    # segments, so the same address over HTTP resolves happily. Two parsers,
    # two answers, for one address grammar.
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FINDING: backend drops empty path segments (repairs), frontend "
            "refuses them — one address grammar with two answers"
        ),
    )
    def test_empty_segments_are_refused_like_the_frontend_does(
        self, client: TestClient
    ) -> None:
        assert client.get("/api/workflows/parent/mounts/wf-music//").status_code in (404, 422)
        assert client.get("/api/workflows/parent/mounts//wf-music").status_code in (404, 422)

    def test_empty_segments_currently_resolve_as_if_absent(self, client: TestClient) -> None:
        """Companion pin of today's behaviour."""
        assert client.get("/api/workflows/parent/mounts/wf-music//").status_code == 200
        assert client.get("/api/workflows/parent/mounts//wf-music").status_code == 200

    def test_uppercase_root_is_refused(self, client: TestClient) -> None:
        assert client.get("/api/workflows/PARENT/mounts/wf-music").status_code in (404, 422)

    def test_unicode_segment_is_a_stale_address_not_a_crash(self, client: TestClient) -> None:
        assert client.get("/api/workflows/parent/mounts/wf-müsic").status_code in (404, 422)

    def test_a_very_long_chain_is_refused_cleanly(self, client: TestClient) -> None:
        path = "/".join(["wf-music"] * 200)
        response = client.get(f"/api/workflows/parent/mounts/{path}")
        assert response.status_code in (404, 422)

    def test_deleting_the_child_package_makes_the_instance_a_404(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        import shutil

        shutil.rmtree(tmp_path / "workflows" / "child")
        response = client.get("/api/workflows/parent/mounts/wf-music")
        assert response.status_code == 404

    def test_overriding_a_mount_whose_child_is_gone_is_still_a_404_not_a_500(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        import shutil

        shutil.rmtree(tmp_path / "workflows" / "child")
        # The override is still sitting on the parent; resolving must not crash.
        response = client.get("/api/workflows/parent/mounts/wf-music?inherited=true")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 5. Hostile override payloads
# ---------------------------------------------------------------------------


class TestHostileOverrides:
    def test_null_silently_replaces_a_real_value_with_no_warning(self) -> None:
        """Pinned: a `null` override is applied over the package's value and
        nothing warns. `MountContext.clearOverride` documents this trap and
        avoids writing null — but a hand-written null is accepted silently."""
        child = _document([_agent("a1", rules="real")])
        merged, warnings = apply_mount_overrides(child, {"a1": {"rules": None}})
        assert _node(merged, "a1")["data"]["rules"] is None
        assert warnings == []

    def test_overriding_top_level_node_keys_only_lands_in_data(self) -> None:
        """`id`/`type` as override keys must not rewrite the node's identity."""
        child = _document([_agent("a1", rules="real")])
        merged, _ = apply_mount_overrides(
            child, {"a1": {"id": "hax", "type": "output.formatted"}}
        )
        node = _node(merged, "a1")
        assert node["id"] == "a1"
        assert node["type"] == "agent.llm"
        # they land in data, harmlessly, per the decision doc
        assert node["data"]["id"] == "hax"

    def test_document_level_nodes_and_edges_cannot_be_overridden(self) -> None:
        """Overrides are keyed by node id; `nodes`/`edges` are not node ids,
        so they warn as unknown children rather than restructure the graph."""
        child = _document([_agent("a1")])
        merged, warnings = apply_mount_overrides(
            child, {"nodes": {"x": 1}, "edges": {"y": 2}}
        )
        assert merged["nodes"] == child["nodes"]
        assert merged["edges"] == child["edges"]
        assert len(warnings) == 2

    def test_a_huge_string_value_survives_the_merge(self) -> None:
        big = "x" * 1_000_000
        child = _document([_agent("a1", rules="real")])
        merged, warnings = apply_mount_overrides(child, {"a1": {"rules": big}})
        assert _node(merged, "a1")["data"]["rules"] == big
        assert warnings == []

    def test_a_list_typed_overrides_field_warns_instead_of_crashing(self) -> None:
        child = _document([_agent("a1")])
        merged, warnings = apply_mount_overrides(child, ["a1"])
        assert merged == child
        assert warnings and "mapping" in warnings[0]

    def test_escaping_characters_round_trip_through_the_string_spelling(self) -> None:
        value = 'she said "hi\\n" — ünïcode 𝔘   </script>'
        child = _document([_agent("a1", rules="real")])
        as_string = json.dumps({"a1": {"rules": value}})
        merged, warnings = apply_mount_overrides(child, as_string)
        assert _node(merged, "a1")["data"]["rules"] == value
        assert warnings == []

    def test_duplicate_child_node_ids_take_the_last_definition(self) -> None:
        """A malformed package with two nodes of one id: the by-id index keeps
        the last, so the override lands on one of them deterministically and
        the other keeps the default. Pinned so a change here is noticed."""
        child = _document([_agent("a1", rules="first"), _agent("a1", rules="second")])
        merged, warnings = apply_mount_overrides(child, {"a1": {"rules": "overridden"}})
        assert warnings == []
        values = [n["data"]["rules"] for n in merged["nodes"]]
        assert values == ["first", "overridden"]


# ---------------------------------------------------------------------------
# 6. Sibling mounts: independence in run state, and mount_slugs attribution
# ---------------------------------------------------------------------------

CHILD_RUNNABLE = {
    "version": 2,
    "name": "child",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}


def _runnable_parent(mounts: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        *mounts,
        {"id": "out1", "type": "output.formatted", "position": {"x": 600, "y": 0}, "data": {}},
    ]
    edges = []
    for mount in mounts:
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": mount["id"], "portId": "candidate"},
            }
        )
        edges.append(
            {
                "source": {"nodeId": mount["id"], "portId": "report"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        )
    return {"version": 2, "name": "parent", "nodes": nodes, "edges": edges}


class TestSiblingMountsAtRunTime:
    def test_two_sibling_mounts_report_independent_outputs(self) -> None:
        """Parent and child share `in1`/`out1` ids; two mounts of one package
        must still land their answers on their own mount ids."""
        parent = _runnable_parent([_mount("m1", "pkg"), _mount("m2", "pkg")])
        docs = {"pkg": CHILD_RUNNABLE}
        runtime = NodeRuntime(document_loader=docs.__getitem__)
        graph = WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
        final = graph.invoke(
            {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}}
        )
        outputs = final.get("outputs") or {}
        assert "m1" in outputs and "m2" in outputs
        # The parent's own out1 is the outermost document's, not the child's.
        assert set(outputs) <= {"in1", "m1", "m2", "out1"}

    def test_mount_slugs_stay_correct_when_sibling_grandchildren_share_an_id(
        self,
    ) -> None:
        """Two different child packages each mount a DIFFERENT grandchild at
        the same node id `inner`. `NodeRuntime.mount_slugs` is flat, keyed by
        mount node id — `setdefault` keeps the first — so the second sibling's
        grandchild frames get attributed to the FIRST sibling's package."""
        grand_x = dict(CHILD_RUNNABLE, name="grand-x")
        grand_y = dict(CHILD_RUNNABLE, name="grand-y")
        child_b = _runnable_parent([_mount("inner", "grand-x")])
        child_d = _runnable_parent([_mount("inner", "grand-y")])
        parent = _runnable_parent([_mount("m1", "child-b"), _mount("m2", "child-d")])
        docs = {
            "grand-x": grand_x,
            "grand-y": grand_y,
            "child-b": child_b,
            "child-d": child_d,
        }
        runtime = NodeRuntime(document_loader=docs.__getitem__)
        WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
        assert runtime.mount_slugs["m1"] == "child-b"
        assert runtime.mount_slugs["m2"] == "child-d"
        # FINDING material: one key, two truths. Whichever value it holds is
        # wrong for the other sibling.
        assert runtime.mount_slugs["inner"] in {"grand-x", "grand-y"}

    # FINDING (CONFIRMED): RunPathResolver attributes the second sibling's
    # grandchild level to the first sibling's package, because mount_slugs is
    # keyed by bare mount node id and ids are unique only within a document.
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FINDING: mount_slugs is flat by mount node id; two sibling "
            "documents mounting different packages at the same id `inner` "
            "collapse to one entry, so path slugs lie for one sibling"
        ),
    )
    def test_path_slugs_distinguish_sibling_grandchildren_with_one_id(self) -> None:
        from openstategraph.api.streaming import RunPathResolver

        grand_x = dict(CHILD_RUNNABLE, name="grand-x")
        grand_y = dict(CHILD_RUNNABLE, name="grand-y")
        child_b = _runnable_parent([_mount("inner", "grand-x")])
        child_d = _runnable_parent([_mount("inner", "grand-y")])
        parent = _runnable_parent([_mount("m1", "child-b"), _mount("m2", "child-d")])
        docs = {
            "grand-x": grand_x,
            "grand-y": grand_y,
            "child-b": child_b,
            "child-d": child_d,
        }
        runtime = NodeRuntime(document_loader=docs.__getitem__)
        WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
        resolver = RunPathResolver(runtime.node_ids_by_name, runtime.mount_slugs, "parent")

        # A frame from grand-y's input node, under m2 -> inner.
        _path, slugs = resolver.resolve("in1", ("m2:task", "inner:task", "in1:task"))
        assert slugs[-1] == "grand-y", (
            f"the frame ran in grand-y but is attributed to {slugs[-1]!r}"
        )


# ---------------------------------------------------------------------------
# 7. The store is never written by resolution
# ---------------------------------------------------------------------------


class TestOneWaySeam:
    def test_a_deep_resolve_writes_nothing_to_disk(self, tmp_path: Path) -> None:
        store = _store(
            tmp_path,
            {
                "grandchild": _document([_agent("deep", rules="package deep")]),
                "child": _document([_mount("wf-inner", "grandchild")]),
                "parent": _document(
                    [
                        _mount(
                            "wf-music",
                            "child",
                            {"wf-inner": {"overrides": {"deep": {"rules": "root"}}}},
                        )
                    ]
                ),
            },
        )
        before = {
            slug: (tmp_path / "workflows" / slug / "workflow.json").read_bytes()
            for slug in ("grandchild", "child", "parent")
        }
        resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        resolve_mount_document(store, "parent", ["wf-music", "wf-inner"], inherited=True)
        after = {
            slug: (tmp_path / "workflows" / slug / "workflow.json").read_bytes()
            for slug in ("grandchild", "child", "parent")
        }
        assert before == after
