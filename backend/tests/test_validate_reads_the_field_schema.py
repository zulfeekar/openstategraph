"""`validate` said VALID to a document that could not do any of what it drew.

`osg-agent-experience/32`. A coding agent built a nineteen-node workflow from
the published wheel and reported *"Compilation: VALID"*, because
`openstategraph validate` did print `VALID`. The document is in
`fixtures/workflows/warehouse-analyst/` — copied from that session with the
engagement's table names replaced by neutral ones, and otherwise byte for byte
what the tool was shown.

What it contains, all of it silent until this ticket:

- a `route.classifier` whose entire configuration is under `systemPrompt`, a
  key that node type does not declare (its own are `rules`, `branches`,
  `fallback`, `matchMode`), so the router was never told anything;
- **no `branches`**, with fifteen edges leaving it, so the concept's core —
  *the question goes to the correct lens* — is not in the document at all;
- those fifteen edges, and fifteen more from the SQL tool, leaving a port
  called `result` that **neither type declares** (a classifier's outputs are
  `branch:<id>`, the tool's is `tool`);
- sixteen `agent.llm` nodes whose `systemPrompt` is a `{"type": ..., "content":
  ...}` dict where the field is a paragraph of text;
- a `tool.sql-query` whose *Database file* — "a .sqlite file inside
  workflows/" — holds the word `mssql`.

Every one of those is knowable from what the catalogue already publishes about
the node type, with no model call and no run. The verdict is a **list of
findings**, not an exception: a caller decides what a finding means, exactly as
`validation.validate_document` already promises.

**`not-an-option` is not in the fixture**, and is checked below against a
hand-built document instead. Said rather than quietly omitted: that session
never set a `select` field at all, so the fixture cannot demonstrate the class,
and a test that pretended otherwise would be testing its own fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.document_checks import FindingClass, document_findings
from openstategraph.validation import validate_document

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "workflows"
EXAMPLES = Path(__file__).parents[1] / "openstategraph" / "examples"


def _haiku_document() -> dict[str, object]:
    payload = json.loads((FIXTURE_ROOT / "warehouse-analyst" / "workflow.json").read_text())
    document = payload["document"]
    assert isinstance(document, dict)
    return document


def _by_class(findings: object) -> dict[FindingClass, list[str]]:
    grouped: dict[FindingClass, list[str]] = {}
    for finding in findings:  # type: ignore[union-attr]
        grouped.setdefault(finding.kind, []).append(finding.subject)
    return grouped


@pytest.fixture(scope="module")
def haiku_findings() -> dict[FindingClass, list[str]]:
    return _by_class(document_findings(_haiku_document(), workflows_root=FIXTURE_ROOT))


class TestTheDocumentThatValidatedClean:
    def test_the_router_is_configured_through_a_key_it_does_not_declare(
        self, haiku_findings: dict[FindingClass, list[str]]
    ) -> None:
        assert "router1.systemPrompt" in haiku_findings[FindingClass.UNKNOWN_FIELD]

    def test_a_paragraph_field_holding_a_dict_is_the_wrong_kind(
        self, haiku_findings: dict[FindingClass, list[str]]
    ) -> None:
        wrong = haiku_findings[FindingClass.WRONG_KIND]
        assert "axis1.systemPrompt" in wrong
        # Every one of the sixteen agents, not the first one found.
        assert len([s for s in wrong if s.endswith(".systemPrompt")]) == 16

    def test_a_database_file_that_names_no_file_is_a_finding(
        self, haiku_findings: dict[FindingClass, list[str]]
    ) -> None:
        assert haiku_findings[FindingClass.MISSING_FILE] == ["sql1.database"]

    def test_a_classifier_with_out_edges_and_no_branches_is_a_finding(
        self, haiku_findings: dict[FindingClass, list[str]]
    ) -> None:
        assert haiku_findings[FindingClass.NO_BRANCHES] == ["router1"]

    def test_every_edge_naming_a_port_the_type_does_not_declare_is_named(
        self, haiku_findings: dict[FindingClass, list[str]]
    ) -> None:
        unknown = haiku_findings[FindingClass.UNKNOWN_PORT]
        # The classifier's fifteen out-edges and the tool's fifteen, each
        # leaving a `result` port neither type has.
        assert "router1.result" in unknown
        assert "sql1.result" in unknown

    def test_the_verdict_is_false_and_carries_the_sentences(self) -> None:
        valid, findings = validate_document(_haiku_document(), workflows_root=FIXTURE_ROOT)
        assert valid is False
        assert any("mssql" in line for line in findings), findings
        assert any("branches" in line for line in findings), findings


class TestASelectValueOutsideItsOwnList:
    """The one class the fixture cannot show — see this module's docstring."""

    def test_a_select_value_the_catalogue_does_not_publish_is_a_finding(self) -> None:
        document = {
            "version": 3,
            "name": "x",
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "out1", "type": "output.formatted", "data": {"format": "yaml"}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "out1", "portId": "result"},
                }
            ],
        }
        grouped = _by_class(document_findings(document))
        assert grouped[FindingClass.NOT_AN_OPTION] == ["out1.format"]

    def test_a_list_the_catalogue_cannot_publish_is_never_refused(self) -> None:
        # The model picker's options depend on which providers hold
        # credentials, so the artifact carries none. An absent list must read
        # as "not knowable here", never as "nothing is permitted" — otherwise
        # every document naming a model is refused.
        document = {
            "version": 3,
            "name": "x",
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "a1", "type": "agent.llm", "data": {"model": "ollama:gpt-oss:120b-cloud"}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "a1", "portId": "prompt"},
                }
            ],
        }
        assert document_findings(document) == []


class TestTheShippedExamplesAreHonestDocuments:
    """Every example this wheel ships passes every check above.

    The other half of a new gate, and the half that decides whether it can be
    trusted: a check that fires on the repository's own worked examples is
    over-strict, and one that fires on none of them may not be firing at all —
    which is why the class above exists beside this one.
    """

    @pytest.mark.parametrize(
        "manifest",
        sorted(EXAMPLES.glob("*/workflow.json")),
        ids=lambda p: p.parent.name,
    )
    def test_the_example_validates_against_its_own_field_schema(self, manifest: Path) -> None:
        payload = json.loads(manifest.read_text())
        document = payload.get("document", payload)
        findings = document_findings(document, workflows_root=EXAMPLES)
        assert findings == [], [f.message for f in findings]
