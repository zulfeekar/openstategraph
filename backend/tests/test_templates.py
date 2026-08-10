"""The scaffold's template catalogue — scale-and-adopt ticket 04.

A pip-install user starts in an empty folder with nothing to imitate, so the
templates ship *inside* the package as ordinary data files. Two claims are
worth a test suite, and neither is provable by reading the code:

- **Every template compiles.** A template that does not is worse than no
  template at all: the first thing a stranger does with it is run it, and a
  scaffold that fails validation teaches them the product is broken. So each
  one is scaffolded into a temp directory and put through the *real* validator
  — `ValidateWorkflowTool`, the same seam `openstategraph validate` and the
  architect agent use — with zero findings required.
- **The catalogue and the files agree.** `index.json` naming a template whose
  directory is missing, or a directory nobody lists, is a defect that only
  surfaces on someone else's machine.

The wheel-side of the claim ("these files are really in the artifact") is
`scripts/clean_install_proof.sh`, which cannot live here: a green test run in
this checkout proves nothing about package data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph import templates
from openstategraph.prebuilt_architect import ValidateWorkflowTool
from openstategraph.scaffold import ScaffoldError, new_package
from openstategraph.schema import normalize_document

NAMES = list(templates.names())


def scaffolded(root: Path, template: str) -> Path:
    return new_package(root, "my-flow", template=template, name="My Flow")


class TestTheCatalogue:
    def test_it_ships_the_three_shapes_and_nothing_padded(self) -> None:
        assert NAMES == ["minimal", "routed-qa", "team"]

    def test_minimal_is_the_default_so_a_first_run_is_one_model_call(self) -> None:
        assert templates.DEFAULT_TEMPLATE == "minimal"
        assert NAMES[0] == "minimal"

    def test_every_entry_has_a_one_line_summary(self) -> None:
        for template in templates.catalogue():
            assert template.summary
            assert "\n" not in template.summary
            assert len(template.summary) <= 100

    def test_an_unknown_name_names_the_valid_ones(self) -> None:
        with pytest.raises(templates.UnknownTemplateError) as caught:
            templates.get("wishful")

        for name in NAMES:
            assert name in str(caught.value)

    def test_the_index_and_the_directories_agree(self) -> None:
        on_disk = {p.name for p in templates.DATA.iterdir() if p.is_dir() and p.name != "__pycache__"}

        assert on_disk == set(NAMES)

    def test_a_template_is_a_document_a_person_can_read(self) -> None:
        """Data files, not Python builders — the boundary this ticket holds."""
        for template in templates.catalogue():
            assert (template.directory / "workflow.json").is_file()
            assert (template.directory / "AGENTS.md").is_file()


@pytest.mark.parametrize("name", NAMES)
class TestEveryTemplateCompiles:
    def _validate(self, package: Path) -> Any:
        document = normalize_document(json.loads((package / "workflow.json").read_text()))
        return ValidateWorkflowTool().run(document=json.dumps(document))

    def test_the_real_validator_finds_nothing(self, name: str, tmp_path: Path) -> None:
        verdict = self._validate(scaffolded(tmp_path, name))

        assert verdict.ok, verdict.error
        assert verdict.content.splitlines()[0] == "VALID"

    def test_the_real_compiler_builds_a_graph_with_no_warnings(
        self, name: str, tmp_path: Path
    ) -> None:
        """Validation is the *plan*; this is the compile. A document can plan
        cleanly and still fail to assemble — an unbound capability, a missing
        function — and the adopter would meet that on their first run."""
        from openstategraph import load_workflow

        workflow = load_workflow(scaffolded(tmp_path, name))

        assert workflow.warnings == []
        assert workflow.mermaid().startswith("---")

    def test_nothing_is_left_unsubstituted(self, name: str, tmp_path: Path) -> None:
        package = scaffolded(tmp_path, name)

        for file in ("workflow.json", "AGENTS.md"):
            assert "{{" not in (package / file).read_text(), file

    def test_the_document_carries_the_display_name(self, name: str, tmp_path: Path) -> None:
        envelope = json.loads((scaffolded(tmp_path, name) / "workflow.json").read_text())

        assert envelope["name"] == "My Flow"
        assert envelope["document"]["name"] == "My Flow"
        assert envelope["published"] is False

    def test_the_conventional_directories_exist(self, name: str, tmp_path: Path) -> None:
        package = scaffolded(tmp_path, name)

        for directory in templates.get(name).directories:
            assert (package / directory).is_dir()

    def test_agents_md_says_what_was_made_and_what_to_do_next(
        self, name: str, tmp_path: Path
    ) -> None:
        """The file a developer opens first. It has one job beyond describing
        the document: name the obvious next step, in a command they can run."""
        text = (scaffolded(tmp_path, name) / "AGENTS.md").read_text()

        assert text.startswith("# My Flow")
        assert "next step" in text.lower()
        assert "openstategraph " in text
        assert "my-flow" in text, "the slug is what publishing and mounting need"
        assert "tools/" in text


class TestMinimalStaysTheCheapFirstRun:
    """The default must keep costing one model call and have nothing that can
    reject it. A grader or a router quietly appearing here would make a
    stranger's first run cost three calls and be refusable."""

    def test_it_is_input_agent_output_and_nothing_else(self, tmp_path: Path) -> None:
        document = json.loads((scaffolded(tmp_path, "minimal") / "workflow.json").read_text())[
            "document"
        ]

        assert [n["type"] for n in document["nodes"]] == [
            "input.text",
            "agent.llm",
            "output.formatted",
        ]

    def test_it_is_byte_for_byte_what_the_python_builder_used_to_produce(self) -> None:
        """`starter_document` is Tier 2 public API. It now reads the template,
        and this pins that the move changed nothing."""
        from openstategraph.scaffold import starter_document

        assert starter_document("My Flow") == {
            "version": 2,
            "name": "My Flow",
            "settings": {},
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
                {"id": "agent1", "type": "agent.llm", "data": {}, "position": {"x": 380, "y": 180}},
                {
                    "id": "out1",
                    "type": "output.formatted",
                    "data": {},
                    "position": {"x": 720, "y": 200},
                },
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "agent1", "portId": "prompt"},
                },
                {
                    "source": {"nodeId": "agent1", "portId": "result"},
                    "target": {"nodeId": "out1", "portId": "result"},
                },
            ],
        }


class TestRoutedQaTeachesTheVocabulary:
    def test_the_grader_closes_a_loop_back_onto_the_agent(self, tmp_path: Path) -> None:
        document = json.loads((scaffolded(tmp_path, "routed-qa") / "workflow.json").read_text())[
            "document"
        ]
        edges = {
            (e["source"]["nodeId"], e["source"]["portId"], e["target"]["nodeId"], e["target"]["portId"])
            for e in document["edges"]
        }

        assert ("grader1", "revise", "agent1", "feedback") in edges
        assert ("grader1", "pass", "out1", "result") in edges

    def test_the_router_has_more_than_one_destination(self, tmp_path: Path) -> None:
        """A one-branch router is a router in name only."""
        document = json.loads((scaffolded(tmp_path, "routed-qa") / "workflow.json").read_text())[
            "document"
        ]
        router = next(n for n in document["nodes"] if n["type"] == "route.classifier")
        targets = {
            e["target"]["nodeId"]
            for e in document["edges"]
            if e["source"]["nodeId"] == router["id"]
        }

        assert len(router["data"]["branches"]) >= 2
        assert len(targets) >= 2


class TestTheTeamOutcomeIsStillAuthorable:
    def test_the_default_criteria_come_from_the_catalogue(self, tmp_path: Path) -> None:
        package = new_package(tmp_path, "a-team", template="team")
        document = json.loads((package / "workflow.json").read_text())["document"]
        grader = next(n for n in document["nodes"] if n["type"] == "route.grader")

        assert grader["data"]["criteria"] == templates.get("team").defaults["outcome"]

    def test_a_caller_can_override_it(self, tmp_path: Path) -> None:
        package = new_package(tmp_path, "a-team", template="team", outcome="- Must cite a source.")
        document = json.loads((package / "workflow.json").read_text())["document"]
        grader = next(n for n in document["nodes"] if n["type"] == "route.grader")

        assert grader["data"]["criteria"] == "- Must cite a source."


class TestScaffoldingRefuses:
    def test_an_unknown_template(self, tmp_path: Path) -> None:
        with pytest.raises(templates.UnknownTemplateError):
            new_package(tmp_path, "my-flow", template="wishful")

    def test_and_leaves_no_half_made_directory_behind(self, tmp_path: Path) -> None:
        with pytest.raises(templates.UnknownTemplateError):
            new_package(tmp_path, "my-flow", template="wishful")

        assert not (tmp_path / "my-flow").exists()

    def test_a_slug_that_cannot_name_a_package(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError):
            new_package(tmp_path, "My Flow")
