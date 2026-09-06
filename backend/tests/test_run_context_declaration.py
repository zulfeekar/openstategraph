"""`settings.context` — the declaration, and nothing that consumes it.

`organisms-first-class/67`, step 1 of the seven in
`docs/decisions/runtime-context.md`. This ticket ends with a document that can
*say* what its runs carry. Nothing mints a schema (69), nothing supplies values
(70) and nothing reads them (71), so every assertion here is about a document
and about `openstategraph validate`'s one question — is this ready to run here.

The inverses are the load-bearing half. A document without the key must be
byte-identical through a round trip and must mean exactly what it meant before
this shipped; a document with an empty list must survive as an empty list. A
declaration is only worth having if the absence of one costs nothing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from openstategraph.compile.run_context import (
    RUN_CONTEXT_SETTING,
    RUN_CONTEXT_TYPES,
    ContextField,
    context_declaration,
    context_declaration_problems,
)
from openstategraph.compile.workflow_compiler import WorkflowCompiler

THREE_FIELDS: list[dict[str, Any]] = [
    {
        "key": "tenant",
        "type": "string",
        "label": "Tenant",
        "description": "Which customer this run is for.",
        "required": True,
    },
    {"key": "caseId", "type": "string", "label": "Case id", "required": False},
    {"key": "maxRefunds", "type": "number", "label": "Refund ceiling", "default": 3},
    {"key": "dryRun", "type": "boolean", "label": "Dry run", "default": False},
]


def document(context: Any = None, *, omit: bool = False) -> dict[str, Any]:
    """A minimal two-node document, optionally declaring run context."""
    settings: dict[str, Any] = {"purpose": "a fixture"}
    if not omit:
        settings[RUN_CONTEXT_SETTING] = context
    return {
        "version": 3,
        "name": "declares context",
        "settings": settings,
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }


class TestTheDescriptorShape:
    def test_three_types_and_no_more(self) -> None:
        # Not "object" or "array" in v1: a nested value cannot be rendered into
        # a prompt section honestly or typed on a CLI flag without inventing a
        # parser, and every one of those is a portability guardrail asking to
        # be broken.
        assert RUN_CONTEXT_TYPES == ("string", "number", "boolean")

    def test_a_declaration_of_three_types_parses(self) -> None:
        fields = context_declaration(document(THREE_FIELDS))
        assert [f.key for f in fields] == ["tenant", "caseId", "maxRefunds", "dryRun"]
        assert [f.type for f in fields] == ["string", "string", "number", "boolean"]

    def test_order_is_the_rendering_contract(self) -> None:
        reversed_fields = list(reversed(THREE_FIELDS))
        fields = context_declaration(document(reversed_fields))
        assert [f.key for f in fields] == [f["key"] for f in reversed_fields]

    def test_absent_default_means_unset_and_required_defaults_to_false(self) -> None:
        field = ContextField(key="tenant", type="string")
        assert field.default is None
        assert field.required is False
        assert field.label == ""

    def test_a_descriptor_carries_no_python(self) -> None:
        # Guardrail 4: `workflow.json` stores field descriptors, never a type.
        dumped = ContextField(key="tenant", type="string", default="acme").model_dump()
        assert json.loads(json.dumps(dumped)) == dumped


class TestARefusalNamesTheKey:
    @pytest.mark.parametrize(
        "field, fragment",
        [
            ({"key": "tenant", "type": "text"}, "'tenant'"),
            ({"key": "tenant", "type": "object"}, "object"),
        ],
    )
    def test_an_invalid_type_is_refused(self, field: dict[str, Any], fragment: str) -> None:
        problems = context_declaration_problems(document([field]))
        assert problems and fragment in problems[0]

    def test_a_duplicate_key_is_refused(self) -> None:
        problems = context_declaration_problems(
            document([{"key": "tenant", "type": "string"}, {"key": "tenant", "type": "number"}])
        )
        assert problems == [
            "Run context declares 'tenant' more than once — each key may appear only once."
        ]

    @pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
    def test_a_non_finite_default_is_refused(self, value: float) -> None:
        problems = context_declaration_problems(
            document([{"key": "maxRefunds", "type": "number", "default": value}])
        )
        assert problems and "'maxRefunds'" in problems[0]
        assert "finite" in problems[0]

    def test_a_default_of_the_wrong_declared_type_is_refused(self) -> None:
        problems = context_declaration_problems(
            document([{"key": "maxRefunds", "type": "number", "default": "three"}])
        )
        assert problems and "'maxRefunds'" in problems[0]

    def test_a_missing_key_names_its_position(self) -> None:
        problems = context_declaration_problems(document([{"type": "string"}]))
        assert problems and "position 1" in problems[0]

    def test_an_undeclared_property_is_refused(self) -> None:
        problems = context_declaration_problems(
            document([{"key": "tenant", "type": "string", "secret": True}])
        )
        assert problems and "secret" in problems[0]

    def test_a_mapping_is_not_a_declaration(self) -> None:
        problems = context_declaration_problems(document({"tenant": "string"}))
        assert problems and "list" in problems[0]

    def test_context_declaration_raises_where_problems_reports(self) -> None:
        from openstategraph.errors import DocumentError

        with pytest.raises(DocumentError) as excinfo:
            context_declaration(document([{"key": "tenant", "type": "text"}]))
        assert "'tenant'" in str(excinfo.value)


class TestTheReservedKeys:
    """`configurable` is who the run is *for*; `context` is what the workflow
    asked its caller for. Two channels carrying "who is asking" is the
    duplication `CLAUDE.md` forbids, and the one that could be written by a
    caller is the one that hands back what memory ticket 01 took away."""

    def test_the_reserved_list_is_read_from_one_place(self) -> None:
        from openstategraph.compile.run_context import RESERVED_CONTEXT_KEYS
        from openstategraph.run_identity import RUN_IDENTITY_FIELDS

        assert RESERVED_CONTEXT_KEYS == tuple(key for key, _label in RUN_IDENTITY_FIELDS)

    @pytest.mark.parametrize(
        "key",
        [
            "thread_id",
            "threadId",
            "THREAD_ID",
            "Thread-Id",
            "threadid",
            "session_id",
            "sessionId",
            "SESSIONID",
            "user_email",
            "userEmail",
            "User_Email",
            "workflow_slug",
            "workflowSlug",
            "WORKFLOW-SLUG",
        ],
    )
    def test_a_reserved_key_is_refused_in_any_casing(self, key: str) -> None:
        problems = context_declaration_problems(document([{"key": key, "type": "string"}]))
        assert problems, f"{key} was accepted"
        assert f"'{key}'" in problems[0]
        assert "reserved" in problems[0]

    @pytest.mark.parametrize("key", ["threading", "user_email_address", "slug", "thread"])
    def test_a_key_that_merely_resembles_one_is_accepted(self, key: str) -> None:
        assert context_declaration_problems(document([{"key": key, "type": "string"}])) == []


class TestTheChannelAndTheExitCode:
    """A bad declaration is a compiler *problem*, on `plan.warnings` — the one
    channel `validate` turns into PROBLEMS FOUND and a non-zero exit."""

    def test_a_good_declaration_leaves_the_plan_quiet(self) -> None:
        plan = WorkflowCompiler().plan(document(THREE_FIELDS))
        assert plan.warnings == []

    def test_a_bad_declaration_reaches_plan_warnings(self) -> None:
        plan = WorkflowCompiler().plan(document([{"key": "threadId", "type": "string"}]))
        assert any("reserved" in w for w in plan.warnings)

    def test_validate_prints_it_and_exits_one(self, tmp_path: Path) -> None:
        from openstategraph.cli import main

        package = tmp_path / "declares-context"
        package.mkdir()
        (package / "workflow.json").write_text(
            json.dumps({"version": 1, "name": "x", "document": document([{"key": "tenant", "type": "text"}])})
        )
        assert main(["validate", str(package)]) == 1

    def test_validate_stays_zero_for_a_good_declaration(self, tmp_path: Path) -> None:
        from openstategraph.cli import main

        package = tmp_path / "declares-context"
        package.mkdir()
        (package / "workflow.json").write_text(
            json.dumps({"version": 1, "name": "x", "document": document(THREE_FIELDS)})
        )
        assert main(["validate", str(package)]) == 0


class TestTheInverses:
    """The half that says the absence of a declaration costs nothing."""

    def test_a_document_without_the_key_is_byte_identical_through_a_round_trip(
        self, tmp_path: Path
    ) -> None:
        from openstategraph.api.workflow_store import WorkflowStore

        original = document(omit=True)
        before = json.dumps(original, sort_keys=True)
        store = WorkflowStore(root=tmp_path)
        store.save("no-context", name="No context", document=original, saved_at="t")
        assert json.dumps(store.load("no-context"), sort_keys=True) == before

    def test_a_document_without_the_key_declares_nothing_and_is_quiet(self) -> None:
        assert context_declaration(document(omit=True)) == ()
        assert context_declaration_problems(document(omit=True)) == []
        assert WorkflowCompiler().plan(document(omit=True)).warnings == []

    def test_an_empty_list_survives_and_means_the_same_as_absence(self, tmp_path: Path) -> None:
        from openstategraph.api.workflow_store import WorkflowStore

        store = WorkflowStore(root=tmp_path)
        store.save("empty-context", name="Empty", document=document([]), saved_at="t")
        # Preserved as written — the author said "no fields", and a serializer
        # that helpfully dropped the key would rewrite a file nobody edited.
        assert store.load("empty-context")["settings"][RUN_CONTEXT_SETTING] == []
        # And it *means* absence: nothing is declared either way.
        assert context_declaration(document([])) == ()
        assert context_declaration_problems(document([])) == []

    def test_a_declaration_survives_save_and_load_unchanged(self, tmp_path: Path) -> None:
        from openstategraph.api.workflow_store import WorkflowStore

        store = WorkflowStore(root=tmp_path)
        store.save("declares", name="Declares", document=document(THREE_FIELDS), saved_at="t")
        assert store.load("declares")["settings"][RUN_CONTEXT_SETTING] == THREE_FIELDS


class TestStillNothingConsumesIt:
    """67 builds a declaration and no runtime. The workflow behaves as it did."""

    def test_the_declaration_is_not_a_state_key_or_a_node(self) -> None:
        plan = WorkflowCompiler().plan(document(THREE_FIELDS))
        assert plan.nodes == WorkflowCompiler().plan(document(omit=True)).nodes


class TestTheTypeScriptMirrorDoesNotDrift:
    """A hand-mirror without a pin is what the DRY rule forbids.

    `core/` is framework-free TypeScript and cannot import Python, so the
    descriptor's enum and the reserved list exist twice. This is the drift
    test that keeps the second copy honest — the same instrument
    `RuntimeClient.ts` is held to.
    """

    def _contract(self) -> str:
        path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "core"
            / "model"
            / "contracts"
            / "workflow.ts"
        )
        return path.read_text(encoding="utf-8")

    def test_the_type_enum_matches(self) -> None:
        source = self._contract()
        rendered = ", ".join(f"'{t}'" for t in RUN_CONTEXT_TYPES)
        assert f"export const RUN_CONTEXT_TYPES = [{rendered}] as const;" in source

    def test_the_reserved_list_matches(self) -> None:
        from openstategraph.compile.run_context import RESERVED_CONTEXT_KEYS

        source = self._contract()
        rendered = "\n".join(f"  '{key}'," for key in RESERVED_CONTEXT_KEYS)
        assert rendered in source

    def test_the_setting_key_matches(self) -> None:
        assert f"export const RUN_CONTEXT_SETTING = '{RUN_CONTEXT_SETTING}';" in self._contract()
