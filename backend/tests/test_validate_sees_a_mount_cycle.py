"""`validate` said VALID for a package that mounts itself (workflow-gallery 27).

The zero-token gate — the command a customer runs *before* a run costs
anything — answered VALID, exit 0, for a document whose mount names its own
slug. `load_workflow` on the same package raises

    Workflow 'selfmount' mounts itself (selfmount -> selfmount);
    a mount cycle can never terminate

so the cheap gate said yes and the expensive one said no. That is the whole
bug: the refusal was never missing, it was only late.

`unresolved_mounts` was already walking the chain — it had to, because a typo
two packages down breaks a run just as completely — and its `_seen` guard hit
a repeated slug and `continue`d. The guard's argument was **termination**, not
silence, and both are available: report the cycle *and* stop descending.

**The compile-time refusal stays the authority.** These assertions pin the
sentence against `node_runtime`'s own, character for character, the way
`src/core/validation/mountCycleRule.ts` already does for the editor. A gate
that refuses by a different rule, or in different words, is a second
implementation of the rule and is worse than no gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph import cli
from openstategraph.validation import unresolved_mounts


def _document(*, mounts: str | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
        {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 9, "y": 0}},
    ]
    edges: list[dict[str, Any]] = []
    if mounts is None:
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        )
    else:
        nodes.insert(
            1,
            {
                "id": "mount1",
                "type": "workflow.subgraph",
                "title": "The mount",
                "data": {"workflow": mounts},
                "position": {"x": 5, "y": 0},
            },
        )
        edges += [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "mount1", "portId": "input"},
            },
            {
                "source": {"nodeId": "mount1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ]
    return {"version": 3, "name": "doc", "nodes": nodes, "edges": edges}


def _package(root: Path, slug: str, *, mounts: str | None = None) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {"version": 1, "name": slug, "savedAt": "", "document": _document(mounts=mounts)}
        )
    )
    return directory


def _compile_time_refusal(slug: str, chain: str) -> str:
    """The sentence `node_runtime._subgraph` raises, built the same way.

    Not a copy of the words: the same f-string, so a change there fails here
    rather than silently letting two surfaces drift apart.
    """
    return f"Workflow {slug!r} mounts itself ({chain}); a mount cycle can never terminate"


class TestTheCommand:
    def test_a_package_that_mounts_itself_is_not_valid(self, tmp_path: Path, capsys: Any) -> None:
        package = _package(tmp_path, "selfmount", mounts="selfmount")

        code = cli.main(["validate", str(package)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_FAILURE
        assert "VALID" not in out.splitlines()[0]
        assert _compile_time_refusal("selfmount", "selfmount -> selfmount") in out

    def test_a_cycle_through_another_package_is_not_valid(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        # The ticket's own example is at depth: the document you validate is
        # innocent, and the cycle closes one level down.
        _package(tmp_path, "mid", mounts="top")
        package = _package(tmp_path, "top", mounts="mid")

        code = cli.main(["validate", str(package)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_FAILURE
        assert _compile_time_refusal("top", "top -> mid -> top") in out

    def test_a_deep_legal_chain_still_validates(self, tmp_path: Path, capsys: Any) -> None:
        # The constraint that makes this fix interesting: packages legitimately
        # mount packages several levels deep, and `_seen` is what stopped the
        # recursion running forever. Acyclic depth must stay clean, and the
        # walk must still terminate.
        _package(tmp_path, "leaf")
        _package(tmp_path, "level3", mounts="leaf")
        _package(tmp_path, "level2", mounts="level3")
        package = _package(tmp_path, "level1", mounts="level2")

        code = cli.main(["validate", str(package)])

        assert code == cli.EXIT_OK
        assert "VALID" in capsys.readouterr().out

    def test_a_diamond_is_not_a_cycle(self, tmp_path: Path, capsys: Any) -> None:
        # One package mounted twice down two different branches repeats a slug
        # without closing a loop. A check keyed on "have I seen this slug
        # anywhere" would refuse it; ancestry is what tells them apart.
        _package(tmp_path, "shared")
        _package(tmp_path, "left", mounts="shared")
        _package(tmp_path, "right", mounts="shared")
        document = _document(mounts="left")
        document["nodes"].append(
            {
                "id": "mount2",
                "type": "workflow.subgraph",
                "data": {"workflow": "right"},
                "position": {"x": 7, "y": 0},
            }
        )
        package = tmp_path / "diamond"
        package.mkdir()
        (package / "workflow.json").write_text(
            json.dumps({"version": 1, "name": "diamond", "savedAt": "", "document": document})
        )

        code = cli.main(["validate", str(package)])

        assert code == cli.EXIT_OK
        assert "VALID" in capsys.readouterr().out


class TestTheCheckItself:
    def test_the_walk_still_terminates(self, tmp_path: Path) -> None:
        # The `_seen` guard's original job, which the report must not cost.
        _package(tmp_path, "a", mounts="b")
        _package(tmp_path, "b", mounts="a")

        findings = unresolved_mounts(_document(mounts="a"), tmp_path, slug="root")

        assert len(findings) == 1
        assert _compile_time_refusal("a", "root -> a -> b -> a") == findings[0]

    def test_an_unnamed_document_still_reports_a_cycle(self, tmp_path: Path) -> None:
        # `slug` is optional — a document validated on its own has no folder.
        # The chain then starts at the first mount, and the cycle is still one
        # a run could never terminate.
        _package(tmp_path, "a", mounts="b")
        _package(tmp_path, "b", mounts="a")

        findings = unresolved_mounts(_document(mounts="a"), tmp_path)

        assert findings == [_compile_time_refusal("a", "a -> b -> a")]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
