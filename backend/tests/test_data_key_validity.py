"""An unrecognised or missing-required `data` key still validated clean.

launch-readiness/24. `18` made a node type's field schema *visible*
(`get_node_vocabulary`); nothing checked a document's `data` against it.
Reproduced directly against `validate_document`: a `tool.sql-query` node
carrying `{"totallyWrongKey": "nope"}` and no `database` at all still came
back `(True, [])`.

Owner decision, 2026-08-24: the two halves are not the same defect.

- A `required` field absent from `data` is a **hard finding** — there is no
  working version of that node, so the document is refused.
- A key `data` carries that no field declares is a **warning** — reported by
  name, document still VALID. Precedent: `Finding.UNWIRED_REVISE` is kept off
  `plan.warnings` on purpose (`workflow-gallery/31`), because that list is
  what `package_testing.assert_document_shape` and `validate_workflow`'s
  PROBLEMS FOUND require empty. Same shape here: the advisory rides a
  separate channel that never becomes a problem.

`tool.*`/`function.*` types minted from a package's Python have no static
field schema at all — skipped, and the skip is not silent (see the
dynamic-type test below and `ValidateWorkflowTool`'s report).
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.validation import validate_document


def _document(t1_data: dict[str, object]) -> dict[str, object]:
    return {
        "version": 2,
        "name": "x",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "t1", "type": "tool.sql-query", "data": t1_data},
            {"id": "a1", "type": "agent.llm", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "out"},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "t1", "portId": "tool"},
                "target": {"nodeId": "a1", "portId": "tools"},
            },
        ],
    }


class TestMissingRequiredKeyIsRefused:
    def test_a_missing_required_key_is_a_hard_finding(self) -> None:
        doc = _document({})  # no "database" — tool.sql-query marks it required
        valid, findings = validate_document(doc)
        assert valid is False
        assert any("database" in f and "t1" in f for f in findings), findings

    def test_the_missing_required_key_lands_on_plan_warnings(self) -> None:
        # `plan.warnings` is the channel `package_testing.assert_document_shape`
        # and `ValidateWorkflowTool`'s PROBLEMS FOUND both read — a hard finding
        # that missed this channel would refuse nowhere real.
        plan = WorkflowCompiler().plan(_document({}))
        assert any("database" in w and "t1" in w for w in plan.warnings), plan.warnings


class TestUnknownKeyIsAWarningOnly:
    def test_an_unknown_key_is_reported_but_stays_valid(self) -> None:
        doc = _document({"database": "chinook.sqlite", "totallyWrongKey": "nope"})
        valid, findings = validate_document(doc)
        assert valid is True
        assert any("totallyWrongKey" in f for f in findings), findings

    def test_an_unknown_key_never_reaches_plan_warnings(self) -> None:
        # Same precedent as `Finding.UNWIRED_REVISE`: a report that must not
        # move VALID/INVALID cannot live on `plan.warnings`.
        plan = WorkflowCompiler().plan(
            _document({"database": "chinook.sqlite", "totallyWrongKey": "nope"})
        )
        assert not any("totallyWrongKey" in w for w in plan.warnings), plan.warnings


class TestACorrectDocumentStillValidatesClean:
    def test_a_document_with_only_declared_keys_and_all_required_ones_is_clean(self) -> None:
        doc = _document({"database": "chinook.sqlite"})
        valid, findings = validate_document(doc)
        assert valid is True
        assert findings == []

        plan = WorkflowCompiler().plan(doc)
        assert plan.warnings == []


class TestDynamicTypesAreSkippedNotSilently:
    def test_a_dynamically_discovered_tool_type_is_not_checked_and_says_so(self) -> None:
        # A `tool.*`/`function.*` type this build's generated catalogue does
        # not carry a field schema for — the dynamically-discovered shape
        # `ValidateWorkflowTool.KNOWN_PREFIXES` already treats as known rather
        # than as an unknown node type. It has no static field schema, so it
        # must not false-positive as an unknown-key avalanche, and the skip
        # must be legible rather than silent (CLAUDE.md: incomplete may ship,
        # silent may not).
        doc = {
            "version": 2,
            "name": "x",
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {
                    "id": "t1",
                    "type": "tool.custom-discovered-thing",
                    "data": {"anything": "goes"},
                },
                {"id": "a1", "type": "agent.llm", "data": {}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "out"},
                    "target": {"nodeId": "a1", "portId": "prompt"},
                },
                {
                    "source": {"nodeId": "t1", "portId": "tool"},
                    "target": {"nodeId": "a1", "portId": "tools"},
                },
            ],
        }
        plan = WorkflowCompiler().plan(doc)
        assert plan.warnings == []
        assert any("tool.custom-discovered-thing" in a for a in plan.advisories), (
            plan.advisories
        )

    def test_a_registered_plugin_family_type_is_not_double_reported(self) -> None:
        # A node type absent from the generated catalogue but *not* prefixed
        # tool./function. is either an unknown type (`ValidateWorkflowTool`
        # already reports that, loudly) or a family a plugin registered
        # through `openstategraph.node_families` — legitimately known to the
        # runtime. Neither needs a second "its data keys were not checked"
        # sentence from this check.
        doc = {
            "version": 2,
            "name": "x",
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "a1", "type": "agent.llm", "data": {}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "out"},
                    "target": {"nodeId": "a1", "portId": "prompt"},
                },
            ],
        }
        plan = WorkflowCompiler().plan(doc)
        assert plan.advisories == []
