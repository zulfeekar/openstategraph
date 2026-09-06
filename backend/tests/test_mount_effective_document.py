"""The document one *instance* of a reusable workflow actually runs — ticket 42.

A package is a class; a mount node in a parent is an instance, and its props
are `data.overrides` (`docs/decisions/mount-overrides.md`, accepted and
implemented). The editor needs to show an instance, which means it needs the
child package **with that mount's overrides applied**.

That merge has exactly one owner — `apply_mount_overrides` — and the decision
recorded on ticket 42 was to **serve** the result rather than mirror the merge
in TypeScript. A second implementation of a rule with one owner is duplicated
knowledge buying only a round trip, and this codebase has already paid for one
of those.

So the resolver here does no merging of its own. It walks a chain of mount node
ids, loading each referenced package and handing it to the one function that
knows how. The first test asserts exactly that, by comparing against a direct
call rather than by re-stating the merged values — which is what makes "one
owner" a property under test rather than an intention.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.api.mount_resolution import (
    MountResolutionError,
    resolve_mount_document,
)
from openstategraph.api.workflow_store import WorkflowStore
from openstategraph.compile.node_runtime import apply_mount_overrides


def _document(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 2, "name": "doc", "nodes": nodes, "edges": []}


def _mount(node_id: str, slug: str, overrides: Any = None) -> dict[str, Any]:
    data: dict[str, Any] = {"workflow": slug}
    if overrides is not None:
        data["overrides"] = overrides
    return {"id": node_id, "type": "workflow.subgraph", "position": {"x": 0, "y": 0}, "data": data}


def _agent(node_id: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": "agent.llm", "position": {"x": 0, "y": 0}, "data": data}


@pytest.fixture
def store(tmp_path: Path) -> WorkflowStore:
    """A workflows root holding a parent, a child and a grandchild package."""
    root = tmp_path / "workflows"
    for slug, document in {
        "grandchild": _document([_agent("deep", rules="package deep")]),
        "child": _document(
            [_agent("agent-sql", rules="package rules"), _mount("wf-inner", "grandchild")]
        ),
        "parent": _document(
            [
                _mount("wf-music", "child", {"agent-sql": {"rules": "this mount only"}}),
                _mount("wf-other", "child"),
            ]
        ),
    }.items():
        directory = root / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps({"version": 2, "name": slug, "document": document}, indent=2)
        )
    return WorkflowStore(root=root)


class TestTheMergeHasOneOwner:
    def test_the_effective_document_is_what_apply_mount_overrides_produces(
        self, store: WorkflowStore
    ) -> None:
        """Asserted against the function itself, not against restated values.

        A test that re-listed the merged fields would pass just as happily
        against a second, subtly different merge written inline in a route
        handler — which is the duplication this ticket exists to prevent.
        """
        resolved = resolve_mount_document(store, "parent", ["wf-music"])
        expected, _ = apply_mount_overrides(
            store.load("child"), {"agent-sql": {"rules": "this mount only"}}
        )
        assert resolved.document == expected
        assert resolved.slug == "child"
        assert resolved.mount_path == ["wf-music"]

    def test_a_mount_with_no_overrides_returns_the_package_unchanged(
        self, store: WorkflowStore
    ) -> None:
        resolved = resolve_mount_document(store, "parent", ["wf-other"])
        assert resolved.document == store.load("child")

    def test_the_json_string_form_resolves_identically(self, store: WorkflowStore) -> None:
        """`OVERRIDES_FIELD` is a textarea, so a saved document carries the
        string spelling. `apply_mount_overrides` already accepts both; the
        resolver must not add a second parser beside it."""
        parent = store.load("parent")
        for node in parent["nodes"]:
            if node["id"] == "wf-music":
                node["data"]["overrides"] = json.dumps({"agent-sql": {"rules": "as a string"}})
        store.save("parent", name="parent", document=parent, saved_at="2026-08-13T00:00:00Z")

        resolved = resolve_mount_document(store, "parent", ["wf-music"])
        target = next(n for n in resolved.document["nodes"] if n["id"] == "agent-sql")
        assert target["data"]["rules"] == "as a string"


class TestSiblingInstancesAreIndependent:
    def test_two_mounts_of_one_package_resolve_differently(self, store: WorkflowStore) -> None:
        """The instance property, at the seam that serves it."""
        music = resolve_mount_document(store, "parent", ["wf-music"]).document
        other = resolve_mount_document(store, "parent", ["wf-other"]).document
        assert music != other
        rules = lambda doc: next(n for n in doc["nodes"] if n["id"] == "agent-sql")["data"]["rules"]
        assert rules(music) == "this mount only"
        assert rules(other) == "package rules"


class TestNesting:
    def test_a_grandchild_resolves_through_its_parents_effective_document(
        self, store: WorkflowStore
    ) -> None:
        """Composition order is the substance here.

        `wf-inner` lives in `child`, so a grandchild's overrides must be read
        from `child` **as the parent mount already rewrote it** — not from the
        package on disk. An implementation that re-loaded `child` fresh would
        pass every shallower test and be wrong exactly once someone overrides
        an override, which is the case this pins.
        """
        parent = store.load("parent")
        for node in parent["nodes"]:
            if node["id"] == "wf-music":
                node["data"]["overrides"] = {
                    "wf-inner": {"overrides": {"deep": {"rules": "set by the grandparent"}}}
                }
        store.save("parent", name="parent", document=parent, saved_at="2026-08-13T00:00:00Z")

        resolved = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        deep = next(n for n in resolved.document["nodes"] if n["id"] == "deep")
        assert deep["data"]["rules"] == "set by the grandparent"
        assert resolved.slug == "grandchild"


class TestTheCompileSeamStaysOneDirectional:
    def test_the_package_on_disk_is_never_written(self, store: WorkflowStore) -> None:
        """The merge exists only in the copy handed to the caller. Asserted on
        the bytes, because an in-memory equality check would not catch a write
        that happened to round-trip."""
        path = store.directory_for("child") / "workflow.json"
        before = path.read_bytes()
        resolve_mount_document(store, "parent", ["wf-music"])
        assert path.read_bytes() == before

    def test_resolving_twice_does_not_accumulate(self, store: WorkflowStore) -> None:
        first = resolve_mount_document(store, "parent", ["wf-music"]).document
        second = resolve_mount_document(store, "parent", ["wf-music"]).document
        assert first == second


class TestItRefusesRatherThanGuesses:
    def test_a_path_segment_that_is_not_a_node_names_where_the_walk_stopped(
        self, store: WorkflowStore
    ) -> None:
        with pytest.raises(MountResolutionError) as caught:
            resolve_mount_document(store, "parent", ["wf-nope"])
        assert "wf-nope" in str(caught.value)
        assert "parent" in str(caught.value)

    def test_a_node_that_is_not_a_mount_says_so(self, store: WorkflowStore) -> None:
        """The mistake a hand-typed URL makes. "Not a node" and "not a mount"
        are different errors and must read differently."""
        with pytest.raises(MountResolutionError) as caught:
            resolve_mount_document(store, "parent", ["wf-music", "agent-sql"])
        assert "agent-sql" in str(caught.value)
        assert "not a mount" in str(caught.value).lower()

    def test_a_mount_with_no_workflow_reference_is_refused(self, store: WorkflowStore) -> None:
        parent = store.load("parent")
        parent["nodes"].append(_mount("wf-blank", ""))
        store.save("parent", name="parent", document=parent, saved_at="2026-08-13T00:00:00Z")
        with pytest.raises(MountResolutionError):
            resolve_mount_document(store, "parent", ["wf-blank"])

    def test_an_empty_path_is_refused_rather_than_answering_the_root(
        self, store: WorkflowStore
    ) -> None:
        """`/mounts/` must never quietly mean `GET /api/workflows/{root}` —
        two endpoints answering one question is how they drift."""
        with pytest.raises(MountResolutionError):
            resolve_mount_document(store, "parent", [])

    def test_a_cycle_is_refused_with_the_chain_named(self, tmp_path: Path) -> None:
        """The compiler refuses self-inclusion at build time; the endpoint
        walks the same chain and must refuse the same way. A hang here would
        be a request that never returns."""
        root = tmp_path / "workflows"
        directory = root / "loop"
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "name": "loop",
                    "document": _document([_mount("wf-self", "loop")]),
                }
            )
        )
        with pytest.raises(MountResolutionError) as caught:
            resolve_mount_document(WorkflowStore(root=root), "loop", ["wf-self", "wf-self"])
        assert "loop" in str(caught.value)


class TestWarningsSurvive:
    def test_an_override_naming_an_unknown_child_node_warns_and_runs_the_default(
        self, store: WorkflowStore
    ) -> None:
        """`mount-overrides.md`: validation is loud, not fatal. Without this
        the warning channel has no observable at the seam the editor reads."""
        parent = store.load("parent")
        for node in parent["nodes"]:
            if node["id"] == "wf-music":
                node["data"]["overrides"] = {"typo-id": {"rules": "x"}}
        store.save("parent", name="parent", document=parent, saved_at="2026-08-13T00:00:00Z")

        resolved = resolve_mount_document(store, "parent", ["wf-music"])
        assert resolved.warnings
        assert "typo-id" in resolved.warnings[0]
        assert resolved.document == store.load("child")


def test_the_resolver_does_not_mutate_the_document_it_was_given(store: WorkflowStore) -> None:
    """Belt and braces for the deep-copy contract, at the in-memory level."""
    parent = store.load("parent")
    snapshot = copy.deepcopy(parent)
    resolve_mount_document(store, "parent", ["wf-music"])
    assert store.load("parent") == snapshot


class TestTheInheritedDocument:
    """What this instance would run if it overrode nothing — ticket 42, tranche 5.

    The inspector's job is to show a field's package default beside this
    mount's value, and to put the default back on request. Neither is
    computable in the browser: the override has already *replaced* the
    inherited value in the effective document, so the original is simply not
    there any more.

    A second fetch is the honest answer, and the parameter belongs on this
    endpoint rather than in a new one, because "resolve this chain" is the same
    walk either way — only the last step differs. Doing it client-side would
    mean a second implementation of the merge, which is the thing the whole
    "serve it" decision was about.

    "Skip the last level" is the rule, and what it really means is **skip the
    overrides this address's own edits write to**. At depth one that is the
    root mount's `overrides`. At depth two it is the nested blob inside it —
    and there is no *separate* place a grandparent could have written, because
    a grandchild's override is expressed as an override of the parent's
    `overrides` field. The two are the same storage location by construction,
    which is what makes one flag enough for every depth.
    """

    def test_it_skips_only_this_mounts_overrides(self, store: WorkflowStore) -> None:
        resolved = resolve_mount_document(store, "parent", ["wf-music"], inherited=True)
        target = next(n for n in resolved.document["nodes"] if n["id"] == "agent-sql")
        assert target["data"]["rules"] == "package rules"

    def test_the_effective_document_still_applies_them(self, store: WorkflowStore) -> None:
        """The two calls must differ, or the chip has nothing to compare."""
        effective = resolve_mount_document(store, "parent", ["wf-music"])
        inherited = resolve_mount_document(store, "parent", ["wf-music"], inherited=True)
        assert effective.document != inherited.document

    def test_at_depth_two_it_skips_the_nested_blob_this_address_writes_to(
        self, store: WorkflowStore
    ) -> None:
        """The first draft of this test asserted that a "grandparent's
        override" survives an inherited read, on the assumption that it was
        stored somewhere other than this instance's own overrides. It is not,
        and the test was wrong rather than the code.

        A grandchild's override *is* an override of the parent's `overrides`
        field — `concierge.wf-music.overrides = {"wf-inner": {"overrides": …}}`
        — so it lands in exactly the place an edit made at
        `concierge/wf-music/wf-inner` writes to. There is no second location to
        tell apart, which is precisely why one flag serves every depth.
        """
        parent = store.load("parent")
        for node in parent["nodes"]:
            if node["id"] == "wf-music":
                node["data"]["overrides"] = {
                    "wf-inner": {"overrides": {"deep": {"rules": "written at this address"}}}
                }
        store.save("parent", name="parent", document=parent, saved_at="2026-08-13T00:00:00Z")

        effective = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"])
        inherited = resolve_mount_document(store, "parent", ["wf-music", "wf-inner"], inherited=True)
        value = lambda doc: next(n for n in doc["nodes"] if n["id"] == "deep")["data"]["rules"]
        assert value(effective.document) == "written at this address"
        assert value(inherited.document) == "package deep"

    def test_a_mount_with_no_overrides_reads_the_same_either_way(
        self, store: WorkflowStore
    ) -> None:
        both = [
            resolve_mount_document(store, "parent", ["wf-other"], inherited=flag).document
            for flag in (False, True)
        ]
        assert both[0] == both[1]
