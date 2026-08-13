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

    # FIXED 2026-08-13. Was xfail(strict=True): a root-level grandchild
    # override replaced the child mount's whole `overrides` field, discarding
    # threshold=9 with no warning. `apply_mount_overrides` now merges the
    # `overrides` key — and only that key — per field.
    def test_the_childs_own_grandchild_overrides_survive_a_root_edit(
        self, store: WorkflowStore
    ) -> None:
        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        deep = _node(resolved.document, "deep")
        assert deep["data"]["rules"] == "root says"
        # The child package said threshold=9 for this mount; the root never
        # touched threshold, so 9 must survive.
        assert deep["data"]["threshold"] == 9

    def test_the_merge_is_per_field_and_the_nearer_override_wins(
        self, store: WorkflowStore
    ) -> None:
        """The companion, rewritten when the defect was fixed.

        It used to pin the bug — `threshold == 1`, the child's 9 silently gone,
        `warnings == []`, nobody told. It now pins the *rule* that replaced it,
        which is the thing a future change could get wrong in either direction:
        merging must not become "the child always wins" any more than it was
        "the root always wins". Precedence is per field, outermost first.
        """
        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        deep = _node(resolved.document, "deep")
        # The root spoke about `rules`, so the root wins `rules`.
        assert deep["data"]["rules"] == "root says"
        # The root said nothing about `threshold`, so the child's pin stands —
        # not the package default of 1.
        assert deep["data"]["threshold"] == 9
        assert resolved.warnings == []

    def test_a_plain_field_is_still_replaced_not_merged(
        self, tmp_path: Path
    ) -> None:
        """The boundary of the fix, and the reason it is one key wide.

        `overrides` is merged because this module owns its shape. Every other
        field is opaque node data, and merging it would invent semantics the
        document never promised — which `mount-overrides.md` rejected. A dict
        left in a plain field must therefore be replaced wholesale.
        """
        store = _store(
            tmp_path,
            {
                "grandchild": _document([_agent("deep", rules="package")]),
                "child": _document(
                    [_mount("wf-inner", "grandchild", {"deep": {"shape": {"a": 1, "b": 2}}})]
                ),
                "parent": _document(
                    [_mount("wf-music", "child",
                            {"wf-inner": {"overrides": {"deep": {"shape": {"b": 9}}}}})]
                ),
            },
        )
        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        # `a` is gone: the nearer value replaced the whole object.
        assert _node(resolved.document, "deep")["data"]["shape"] == {"b": 9}


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
        """An override cannot form a cycle any more, because it cannot retarget.

        This used to assert that a `workflow` override pointing back at the
        root was caught by the visited check on the merged document. Reserving
        the key (owner decision, 2026-08-13) removes the attack one step
        earlier: the retarget never happens, so the cycle never forms, and the
        resolve succeeds against the package the mount actually declares.

        The visited check is still the defence for cycles that are genuinely
        drawn — direct self-mount and mutual recursion, both covered by the
        tests above — so nothing was lost by this becoming unreachable.
        """
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
        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        assert resolved.slug == "innocent"
        assert any("workflow" in w for w in resolved.warnings), resolved.warnings

    def test_an_override_can_retarget_a_grandchild_mount_to_any_package(
        self, tmp_path: Path
    ) -> None:
        """Reserved 2026-08-13 (owner decision), and this test reversed with it.

        It used to assert that an override silently swapped which package a
        grandchild mount runs — accepted behaviour, recorded. The decision was
        to **reserve** the key instead: an override narrows a mount, it never
        redirects it. The card would otherwise go on naming the original
        package while the run executed a different one, and `MountEditScope`
        already refuses shape changes in the editor; this closes the same door
        on the data path.

        Loud, not fatal: the mount runs its declared package and the run says
        what it ignored.
        """
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
        assert resolved.slug == "innocent"
        assert _node(resolved.document, "leaf")["data"]["rules"] == "innocent"
        assert any("workflow" in w for w in resolved.warnings), resolved.warnings


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
    # FIXED 2026-08-13. Was xfail(strict=True): `get_mount_document` filtered
    # empty segments out, so `parent//wf-music` resolved happily over HTTP
    # while `parseMountAddress` returned null for the same string — one
    # address grammar with two parsers and two answers.
    def test_empty_segments_are_refused_like_the_frontend_does(
        self, client: TestClient
    ) -> None:
        assert client.get("/api/workflows/parent/mounts/wf-music//").status_code in (404, 422)
        assert client.get("/api/workflows/parent/mounts//wf-music").status_code in (404, 422)

    def test_a_malformed_address_is_422_and_a_stale_one_is_404(
        self, client: TestClient
    ) -> None:
        """The companion, rewritten when the defect was fixed.

        It used to pin the repair (both returned 200). It now pins the
        distinction the fix turns on, which is the thing a future change could
        blur: **422 is "that is not an address", 404 is "that address names
        nothing".** A client renders them differently — one is a bug in the
        link, the other is a link that has gone stale.
        """
        assert client.get("/api/workflows/parent/mounts//wf-music").status_code == 422
        # Well-formed, and names a mount that does not exist.
        assert client.get("/api/workflows/parent/mounts/wf-nope").status_code == 404

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
    def test_a_null_override_is_applied_and_reported(self) -> None:
        """Was `..._silently_replaces_a_real_value_with_no_warning`.

        Still **applied**: `None` may be a legitimate value for a nullable
        field, and this module does not get to decide the author meant
        something else. Now **reported**, because the editor never writes one —
        `MountContext.clearOverride` removes the key instead, precisely so a
        cleared field is not an override of `null` the card keeps counting. A
        null here is therefore always hand-written and ambiguous between "make
        it null" and "I meant to remove this".
        """
        child = _document([_agent("a1", rules="real")])
        merged, warnings = apply_mount_overrides(child, {"a1": {"rules": None}})
        assert _node(merged, "a1")["data"]["rules"] is None
        assert any("null" in w and "a1.rules" in w for w in warnings), warnings

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
        the same node id `inner`.

        Rewritten when the defect was fixed. It used to pin the bug: one flat
        key `inner`, two truths, whichever value it held wrong for the other
        sibling. `mount_slugs` is now keyed by the **mount path**, so the two
        are distinct entries and neither shadows the other.
        """
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
        # The two sibling grandchildren, told apart by their path.
        assert runtime.mount_slugs["m1/inner"] == "grand-x"
        assert runtime.mount_slugs["m2/inner"] == "grand-y"
        # And the bare id is not a key at all any more, so a reader cannot
        # accidentally ask the ambiguous question.
        assert "inner" not in runtime.mount_slugs

    # FIXED 2026-08-13. Was xfail(strict=True): `mount_slugs` was flat by
    # mount node id, so sibling subtrees reusing an id collapsed first-wins and
    # a frame from one was attributed to the other's package. Producer and
    # `RunPathResolver` now key by the mount path.
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
