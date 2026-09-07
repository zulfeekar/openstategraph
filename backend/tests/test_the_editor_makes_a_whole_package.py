"""Creating a workflow in the editor makes a *package*, not a lone document.

The owner created a workflow in the editor and found no folder assets. That is
exactly what happened: two doors onto "make me a new workflow" disagreed.

    openstategraph new  ->  workflow.json  AGENTS.md  tools/ functions/
                            middlewares/ skills/ tests/ data/
    POST /api/workflows ->  workflow.json  AGENTS.md

The consequence is not cosmetic. The palette tells a developer *"Python tools
in its `tools/` folder show up here as nodes you can wire in"* — advice that
names a directory the editor never created, so following it means guessing that
you must `mkdir` it first. The conventions are discovered by convention, and a
create that omits them makes them invisible.

`scaffold.WORKFLOW_DIRECTORIES` was already the single declaration of that
list. The editor's store simply never read it.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.api.workflow_store import WorkflowStore
from openstategraph.scaffold import WORKFLOW_DIRECTORIES

DOCUMENT = {
    "version": 3,
    "name": "Probe",
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


class TestBothDoorsMakeTheSamePackage:
    def test_create_lays_out_the_conventional_directories(self, tmp_path: Path) -> None:
        store = WorkflowStore(tmp_path)
        slug = store.create(name="Probe", document=DOCUMENT, saved_at="2026-08-13T00:00:00+00:00")

        for name in WORKFLOW_DIRECTORIES:
            assert (tmp_path / slug / name).is_dir(), f"missing {name}/"

    def test_it_reads_the_one_declaration_rather_than_a_second_list(self) -> None:
        """A copy here is a copy that drifts the day a directory is added.

        Scoped to `create`, not the whole module: elsewhere the store names
        `tools/` and `tests/` for a different reason — the package-contract
        lint that warns about hand-written code with no guard — and that is a
        rule about a *relationship* between two directories, not a second
        declaration of the set.
        """
        import inspect

        from openstategraph.api.workflow_store import WorkflowStore

        source = inspect.getsource(WorkflowStore.create)
        assert "WORKFLOW_DIRECTORIES" in source
        for name in WORKFLOW_DIRECTORIES:
            assert f'"{name}"' not in source, f"{name!r} is spelled out a second time"

    def test_the_document_and_orientation_are_still_written(self, tmp_path: Path) -> None:
        store = WorkflowStore(tmp_path)
        slug = store.create(name="Probe", document=DOCUMENT, saved_at="2026-08-13T00:00:00+00:00")

        assert (tmp_path / slug / "workflow.json").is_file()
        assert (tmp_path / slug / "AGENTS.md").is_file()

    def test_saving_over_an_existing_package_does_not_disturb_it(self, tmp_path: Path) -> None:
        """A save is not a scaffold — it must not resurrect a directory a
        developer deliberately deleted, nor fail because one is missing."""
        store = WorkflowStore(tmp_path)
        slug = store.create(name="Probe", document=DOCUMENT, saved_at="2026-08-13T00:00:00+00:00")
        (tmp_path / slug / "tests").rmdir()

        store.save(slug, name="Probe", document=DOCUMENT, saved_at="2026-08-13T00:00:01+00:00")

        assert (tmp_path / slug / "workflow.json").is_file()
        assert not (tmp_path / slug / "tests").exists()

    def test_an_empty_directory_survives_a_round_trip(self, tmp_path: Path) -> None:
        """The point of the directories is that they are *there* to fill in."""
        store = WorkflowStore(tmp_path)
        slug = store.create(name="Probe", document=DOCUMENT, saved_at="2026-08-13T00:00:00+00:00")

        assert store.load(slug) is not None
        assert (tmp_path / slug / "tools").is_dir()
