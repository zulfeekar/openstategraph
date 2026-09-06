"""Three doors, one validator, and the library's message unreachable from all of them.

`organisms-first-class/70`, step 4 of the seven in
`docs/decisions/runtime-context.md`. 67 let a document *declare* what its runs
carry and 69 minted the class; this is the first ticket that lets a caller
**fill** it, and the reason it is a ticket of its own is the sentence a caller
who gets it wrong reads.

What it replaces, reproduced before anything was built:

    TypeError: RunContext.__init__() got an unexpected keyword argument 'zzz'
    TypeError: RunContext.__init__() missing 1 required keyword-only argument: 'tenant'

…raised by a `dataclasses`-generated `__init__` naming a class the workflow
author never wrote, from *inside* `graph.invoke`, catchable apart from nothing.
Beside those two, measured the same way: `{"tenant": 123}` against
`tenant: string` was **accepted**, and a run supplying nothing at all was
accepted and failed later at whichever node touched `runtime.context` first.

So the question these tests are written against is *what would still be green
if I built the wrong thing?* A validator tested in isolation would be green
against a door that never calls it, so every refusal below is driven through a
real door — `ask()` for the library, `TestClient` for HTTP, `cli.main` and one
subprocess for the command line — and asserted on the **message** and on the
**exit code**, never on the validator's return value.

The inverses matter as much and are here in the same numbers: a workflow that
declares nothing accepts a run that supplies nothing exactly as it did
yesterday, a correct context arrives at a node unchanged, and the four
`configurable` identity keys are untouched by any of it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph import cli, load_workflow
from openstategraph.api.main import create_app
from openstategraph.compile.run_context import (
    coerce_context_flags,
    validate_run_context,
    workflow_label,
)
from openstategraph.errors import OpenStateGraphError, RunContextError

REPO = Path(__file__).resolve().parents[2]

#: Two required-ish fields and one of every declared type, so one document can
#: exercise every refusal. Deliberately no real-looking identity anywhere.
DECLARATION = [
    {"key": "tenant", "type": "string", "label": "Tenant", "required": True},
    {"key": "maxRefunds", "type": "number", "label": "Refund ceiling", "default": 3},
    {"key": "dryRun", "type": "boolean", "label": "Dry run", "default": False},
]

TENANT = "tenant-placeholder"


def _document(context: Any = None, name: str = "Context demo") -> dict[str, Any]:
    """A document that runs with no model at all — input straight to output."""
    document: dict[str, Any] = {
        "version": 2,
        "name": name,
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 1, "y": 0}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }
    if context is not None:
        document["settings"] = {"context": context}
    return document


def _package(root: Path, context: Any = None, slug: str = "ctx-demo") -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Context demo",
                "savedAt": "",
                "document": _document(context),
                "published": False,
            }
        )
    )
    return directory


def _client() -> TestClient:
    return TestClient(create_app(workflows_root=REPO / "workflows"))


def _post(document: dict[str, Any], **extra: Any) -> Any:
    return _client().post(
        "/api/runs", json={"workflow": document, "question": "hello", **extra}
    )


# --------------------------------------------------------------------------- #
# The thing being removed.
# --------------------------------------------------------------------------- #


class TestTheLibrarysMessageIsWhatThisReplaces:
    def test_the_raw_typeerror_is_still_what_invoke_says(self, tmp_path: Path) -> None:
        """Pinned, not assumed. If LangGraph ever grows its own door this fails
        and the argument for owning one has to be re-made."""
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(TypeError) as raised:
            workflow.graph.invoke(
                {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}},
                {"configurable": {"thread_id": "raw"}},
                context={"tenant": TENANT, "zzz": 1},
            )

        assert "RunContext.__init__()" in str(raised.value)
        assert "unexpected keyword argument 'zzz'" in str(raised.value)

    def test_the_library_still_accepts_a_value_of_the_wrong_type(self, tmp_path: Path) -> None:
        """The half that never raised at all, which is why a *type* check has
        to be ours: an `int` reaches a node declared `string`, silently."""
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        workflow.graph.invoke(
            {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}},
            {"configurable": {"thread_id": "raw-type"}},
            context={"tenant": 123},
        )


class TestTheRawTypeErrorIsUnreachableFromEveryDoor:
    """The point of the ticket, at all three doors, in one class.

    A `TypeError` here would mean the validator was bypassed — which is
    exactly what a test of the validator alone could not tell you.
    """

    def test_the_library_door_raises_ours(self, tmp_path: Path) -> None:
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello", context={"tenant": TENANT, "zzz": 1})

        assert "RunContext.__init__()" not in str(raised.value)
        assert isinstance(raised.value, OpenStateGraphError)

    def test_the_http_door_answers_422_not_502(self) -> None:
        response = _post(_document(DECLARATION), context={"tenant": TENANT, "zzz": 1})

        assert response.status_code == 422, response.text
        assert "RunContext.__init__()" not in response.text

    def test_the_command_line_exits_1_and_says_nothing_about_a_python_class(
        self, tmp_path: Path, capsys
    ) -> None:
        package = _package(tmp_path, DECLARATION)

        code = cli.main(["run", str(package), "hello", "--context", "zzz=1"])

        assert code == cli.EXIT_FAILURE
        assert "RunContext.__init__()" not in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# The four refusals, once per door.
# --------------------------------------------------------------------------- #


class TestAnUndeclaredKey:
    SENTENCE = (
        "Run context key 'zzz' is not declared by workflow 'ctx-demo'. "
        "It asks for: tenant, maxRefunds, dryRun."
    )

    def test_library(self, tmp_path: Path) -> None:
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello", context={"tenant": TENANT, "zzz": 1})

        assert str(raised.value) == self.SENTENCE

    def test_http_names_the_document_when_there_is_no_slug(self) -> None:
        """A posted canvas has no slug, so the refusal falls back to the name a
        person actually typed rather than naming an empty string."""
        response = _post(_document(DECLARATION), context={"tenant": TENANT, "zzz": 1})

        assert response.json()["detail"] == self.SENTENCE.replace("ctx-demo", "Context demo")

    def test_command_line(self, tmp_path: Path, capsys) -> None:
        package = _package(tmp_path, DECLARATION)

        code = cli.main(
            ["run", str(package), "hello", "--context", f"tenant={TENANT}", "--context", "zzz=1"]
        )

        assert code == cli.EXIT_FAILURE
        assert self.SENTENCE in capsys.readouterr().err

    def test_a_workflow_declaring_nothing_says_so_rather_than_listing_nothing(
        self, tmp_path: Path
    ) -> None:
        workflow = load_workflow(str(_package(tmp_path)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello", context={"tenant": TENANT})

        assert str(raised.value) == (
            "Run context key 'tenant' is not declared by workflow 'ctx-demo'. "
            "It asks its callers for no run context."
        )


class TestAMissingRequiredKey:
    SENTENCE = (
        "Run context key 'tenant' is required by workflow 'ctx-demo', "
        "and this run supplied no value for it."
    )

    def test_library(self, tmp_path: Path) -> None:
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello", context={"maxRefunds": 5})

        assert str(raised.value) == self.SENTENCE

    def test_http(self) -> None:
        response = _post(_document(DECLARATION), context={"maxRefunds": 5})

        assert response.status_code == 422
        assert response.json()["detail"] == self.SENTENCE.replace("ctx-demo", "Context demo")

    def test_command_line(self, tmp_path: Path, capsys) -> None:
        package = _package(tmp_path, DECLARATION)

        code = cli.main(["run", str(package), "hello", "--context", "maxRefunds=5"])

        assert code == cli.EXIT_FAILURE
        assert self.SENTENCE in capsys.readouterr().err

    def test_a_field_carrying_a_default_is_not_required_of_a_caller(
        self, tmp_path: Path
    ) -> None:
        """69's decision, held at the door: `required` yields to a default, or
        the default is unreachable."""
        declaration = [{"key": "tenant", "type": "string", "required": True, "default": "acme"}]
        workflow = load_workflow(str(_package(tmp_path, declaration)))

        assert workflow.ask("hello", context={}) is not None


class TestAValueOfTheWrongDeclaredType:
    SENTENCE = (
        "Run context key 'tenant' is declared 'string' by workflow 'ctx-demo', "
        "and this run supplied a number."
    )

    def test_library(self, tmp_path: Path) -> None:
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello", context={"tenant": 123})

        assert str(raised.value) == self.SENTENCE

    def test_http(self) -> None:
        response = _post(_document(DECLARATION), context={"tenant": 123})

        assert response.status_code == 422
        assert response.json()["detail"] == self.SENTENCE.replace("ctx-demo", "Context demo")

    def test_command_line_cannot_reach_this_one_by_accident(self, tmp_path: Path) -> None:
        """A flag carries strings, so a `string` field can never be handed a
        number by this door — which is the whole argument for typing the flag
        from the declaration instead of guessing from the literal."""
        assert coerce_context_flags(_document(DECLARATION), {"tenant": "123"}) == {
            "tenant": "123"
        }

    def test_a_boolean_is_never_a_number(self, tmp_path: Path) -> None:
        """In Python `True` is an `int`. A boolean quietly satisfying a numeric
        field is the accepted-and-wrong this validator exists to prevent."""
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello", context={"tenant": TENANT, "maxRefunds": True})

        assert str(raised.value) == (
            "Run context key 'maxRefunds' is declared 'number' by workflow 'ctx-demo', "
            "and this run supplied a boolean."
        )

    def test_a_non_finite_number_is_refused_where_it_is_written(
        self, tmp_path: Path
    ) -> None:
        """`Infinity` and `NaN` are not representable in JSON, so a value that
        could not survive its own round trip never enters a run."""
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello", context={"tenant": TENANT, "maxRefunds": float("inf")})

        assert str(raised.value) == (
            "Run context key 'maxRefunds' is declared 'number' by workflow 'ctx-demo', and "
            "this run supplied a value that is not a finite number — Infinity and NaN "
            "cannot survive a JSON round trip."
        )


class TestARunThatSuppliedNothingAtAll:
    SENTENCE = "Workflow 'ctx-demo' requires run context that this run supplied none of: tenant."

    def test_library(self, tmp_path: Path) -> None:
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))

        with pytest.raises(RunContextError) as raised:
            workflow.ask("hello")

        assert str(raised.value) == self.SENTENCE

    def test_http(self) -> None:
        response = _post(_document(DECLARATION))

        assert response.status_code == 422
        assert response.json()["detail"] == self.SENTENCE.replace("ctx-demo", "Context demo")

    def test_command_line(self, tmp_path: Path, capsys) -> None:
        package = _package(tmp_path, DECLARATION)

        code = cli.main(["run", str(package), "hello"])

        assert code == cli.EXIT_FAILURE
        assert self.SENTENCE in capsys.readouterr().err

    def test_a_declaration_with_nothing_required_lets_a_run_supply_nothing(
        self, tmp_path: Path
    ) -> None:
        declaration = [{"key": "caseId", "type": "string"}]
        workflow = load_workflow(str(_package(tmp_path, declaration)))

        assert workflow.ask("hello") is not None


# --------------------------------------------------------------------------- #
# `--context k=v` gives strings only.
# --------------------------------------------------------------------------- #


class TestTheFlagIsTypedByTheDeclaration:
    def test_a_number_field_reads_an_integer_as_a_number(self) -> None:
        assert coerce_context_flags(_document(DECLARATION), {"maxRefunds": "5"}) == {
            "maxRefunds": 5
        }

    def test_a_number_field_keeps_a_decimal_a_float(self) -> None:
        assert coerce_context_flags(_document(DECLARATION), {"maxRefunds": "2.5"}) == {
            "maxRefunds": 2.5
        }

    def test_a_string_field_is_left_exactly_as_typed(self) -> None:
        """The whole reason the type comes from the document: guessing would
        make a zero-padded case number an integer for one workflow and a string
        for the next."""
        declaration = [{"key": "caseId", "type": "string"}]
        assert coerce_context_flags(_document(declaration), {"caseId": "00123"}) == {
            "caseId": "00123"
        }

    def test_true_and_false_are_the_only_booleans_accepted(self) -> None:
        document = _document(DECLARATION)
        assert coerce_context_flags(document, {"dryRun": "true"}) == {"dryRun": True}
        assert coerce_context_flags(document, {"dryRun": "FALSE"}) == {"dryRun": False}

    @pytest.mark.parametrize("literal", ["1", "0", "yes", "no", "on", "off", "True!", ""])
    def test_everything_else_is_refused_rather_than_guessed(self, literal: str) -> None:
        """The narrowness is the safety. Under Python truthiness the string
        `"false"` is `True`, and a flag that quietly makes false mean true is
        `CLAUDE.md`'s law broken in the direction nobody checks."""
        with pytest.raises(RunContextError) as raised:
            coerce_context_flags(_document(DECLARATION), {"dryRun": literal})

        assert "write true or false" in str(raised.value)
        assert "1, 0, yes, no, on and off are deliberately not accepted" in str(raised.value)

    def test_a_number_that_is_not_a_number_is_refused_with_an_example(self) -> None:
        with pytest.raises(RunContextError) as raised:
            coerce_context_flags(_document(DECLARATION), {"maxRefunds": "lots"})

        assert str(raised.value) == (
            "--context maxRefunds='lots' is declared 'number' by workflow 'Context demo' "
            "— write a number, such as 3 or 3.5."
        )

    def test_infinity_cannot_be_typed_in_either(self) -> None:
        """`float("inf")` accepts the literal `inf`, so the flag has to refuse
        what the field refuses."""
        with pytest.raises(RunContextError) as raised:
            coerce_context_flags(_document(DECLARATION), {"maxRefunds": "inf"})

        assert "not a finite number" in str(raised.value)

    def test_an_undeclared_key_has_no_type_and_is_left_a_string(self) -> None:
        """One refusal, whichever door the value came in by: the validator
        names it undeclared rather than this function inventing a second
        sentence for the same fact."""
        assert coerce_context_flags(_document(DECLARATION), {"zzz": "1"}) == {"zzz": "1"}

    def test_the_flag_survives_the_declaration_being_malformed(self) -> None:
        """A bad declaration is a `plan.warnings` problem (67) and mints
        nothing (69). It must not become a crash in the flag parser."""
        assert coerce_context_flags(_document([{"key": "x", "type": "nope"}]), {"x": "1"}) == {
            "x": "1"
        }


class TestTheFlagsGrammarIsAUsageError:
    """Exit codes are this CLI's API, so the two failures are told apart.

    A pair with no `=` is a mistyped command line and gets argparse's own code;
    a value the *declaration* refuses is a run that cannot start, and gets 1.
    """

    def test_a_pair_with_no_equals_exits_2(self, tmp_path: Path, capsys) -> None:
        package = _package(tmp_path, DECLARATION)

        code = cli.main(["run", str(package), "hello", "--context", "tenant"])

        assert code == cli.EXIT_USAGE
        assert "--context expects key=value, and got 'tenant'." in capsys.readouterr().err

    def test_a_pair_with_no_key_exits_2(self, tmp_path: Path, capsys) -> None:
        package = _package(tmp_path, DECLARATION)

        code = cli.main(["run", str(package), "hello", "--context", "=acme"])

        assert code == cli.EXIT_USAGE
        assert "with no key before the '='" in capsys.readouterr().err

    def test_a_value_may_contain_an_equals_sign(self) -> None:
        """The split is on the first `=`, so `filter=a=b` is a filter of `a=b`."""
        assert cli.split_context_flags(["filter=a=b"]) == ({"filter": "a=b"}, "")

    def test_a_declaration_refusal_exits_1_and_not_2(self, tmp_path: Path) -> None:
        package = _package(tmp_path, DECLARATION)

        assert cli.main(["run", str(package), "hello", "--context", "dryRun=yes"]) == (
            cli.EXIT_FAILURE
        )


class TestTheCommandLineExitsZeroWhenItIsRight:
    def test_in_process(self, tmp_path: Path, capsys) -> None:
        package = _package(tmp_path, DECLARATION)

        code = cli.main(
            [
                "run",
                str(package),
                "hello",
                "--context",
                f"tenant={TENANT}",
                "--context",
                "maxRefunds=5",
                "--context",
                "dryRun=true",
                "--json",
            ]
        )

        assert code == cli.EXIT_OK
        assert json.loads(capsys.readouterr().out)["answer"]

    def test_as_a_process_from_outside_the_checkout(self, tmp_path: Path) -> None:
        """The one subprocess: an exit code is only an API if the *process*
        returns it."""
        package = _package(tmp_path, DECLARATION)

        finished = subprocess.run(
            [
                sys.executable,
                "-m",
                "openstategraph.cli",
                "run",
                str(package),
                "hello",
                "--context",
                "zzz=1",
            ],
            cwd=str(REPO / "backend"),
            capture_output=True,
            text=True,
        )

        assert finished.returncode == 1, finished.stderr
        assert "is not declared by workflow 'ctx-demo'" in finished.stderr


# --------------------------------------------------------------------------- #
# The inverses — what must not have moved.
# --------------------------------------------------------------------------- #


class TestAWorkflowDeclaringNothingIsUnchanged:
    def test_the_library_door_runs_exactly_as_before(self, tmp_path: Path) -> None:
        workflow = load_workflow(str(_package(tmp_path)))

        assert workflow.ask("hello") is not None

    def test_the_http_door_runs_exactly_as_before(self) -> None:
        response = _post(_document())

        assert response.status_code == 200, response.text

    def test_the_command_line_runs_exactly_as_before(self, tmp_path: Path) -> None:
        assert cli.main(["run", str(_package(tmp_path)), "hello"]) == cli.EXIT_OK

    def test_no_context_argument_is_passed_at_all(self, tmp_path: Path) -> None:
        """`None` and absent are not guaranteed to be the same thing to a
        library we do not own — 69's instrument note, held here."""
        workflow = load_workflow(str(_package(tmp_path)))
        seen: dict[str, Any] = {}
        original = workflow.graph.ainvoke

        async def recording(*args: Any, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return await original(*args, **kwargs)

        workflow.graph.ainvoke = recording  # type: ignore[method-assign]
        workflow.ask("hello")

        assert "context" not in seen


class TestACorrectContextPassesThroughUnchanged:
    def test_the_values_reach_a_node_that_actually_ran(self, tmp_path: Path) -> None:
        """Read off `graph.invoke`'s own argument rather than off the
        validator: a validator that returned the right dict to nobody would
        pass a test of itself."""
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))
        seen: dict[str, Any] = {}
        original = workflow.graph.ainvoke

        async def recording(*args: Any, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return await original(*args, **kwargs)

        workflow.graph.ainvoke = recording  # type: ignore[method-assign]
        workflow.ask("hello", context={"tenant": TENANT, "maxRefunds": 5, "dryRun": True})

        assert seen["context"] == {"tenant": TENANT, "maxRefunds": 5, "dryRun": True}

    def test_defaults_are_not_copied_into_the_mapping(self, tmp_path: Path) -> None:
        """The minted dataclass carries them (69), and that is the one place
        they live. Copying them here would be a second spelling that drifts."""
        assert validate_run_context(_document(DECLARATION), {"tenant": TENANT}) == {
            "tenant": TENANT
        }

    def test_http_returns_200_for_a_context_it_declared(self) -> None:
        response = _post(_document(DECLARATION), context={"tenant": TENANT})

        assert response.status_code == 200, response.text


class TestTheIdentityKeysAreUntouched:
    def test_configurable_still_carries_its_four_and_context_carries_none_of_them(
        self, tmp_path: Path
    ) -> None:
        """`configurable` is who the run is *for*; `context` is what the
        workflow asked its caller for. A run supplying context must not move
        either boundary."""
        workflow = load_workflow(str(_package(tmp_path, DECLARATION)))
        seen: dict[str, Any] = {}
        original = workflow.graph.ainvoke

        async def recording(state: Any, config: Any, **kwargs: Any) -> Any:
            seen["config"] = config
            seen.update(kwargs)
            return await original(state, config, **kwargs)

        workflow.graph.ainvoke = recording  # type: ignore[method-assign]
        workflow.ask("hello", context={"tenant": TENANT}, session_id="s", user_email="u")

        configurable = seen["config"]["configurable"]
        assert set(configurable) == {"thread_id", "user_email", "session_id", "workflow_slug"}
        assert set(seen["context"]) == {"tenant"}

    def test_a_declaration_naming_one_of_them_was_already_refused(self, tmp_path: Path) -> None:
        """67's rule, unchanged by a supply route existing."""
        workflow = load_workflow(str(_package(tmp_path, [{"key": "threadId", "type": "string"}])))

        assert any("reserved run identity key" in w for w in workflow.warnings)


class TestTheRequestStaysAdditive:
    def test_extra_is_still_forbidden(self) -> None:
        response = _post(_document(), notAField=1)

        assert response.status_code == 422

    def test_a_request_that_names_no_context_is_the_same_request_it_was(self) -> None:
        from openstategraph.api.schemas import RunRequest

        assert RunRequest(workflow=_document(), question="hi").context is None

    def test_a_nested_value_is_refused_by_the_model_itself(self) -> None:
        """Three scalar types and no more — the same enum the declaration uses,
        so a shape that could not be typed on a flag cannot arrive over HTTP
        either."""
        response = _post(_document(DECLARATION), context={"tenant": {"nested": 1}})

        assert response.status_code == 422


class TestWhatARefusalCallsTheWorkflow:
    def test_the_slug_wins(self) -> None:
        assert workflow_label(_document(), "ctx-demo") == "ctx-demo"

    def test_the_name_stands_in_for_a_canvas_that_has_no_slug(self) -> None:
        assert workflow_label(_document()) == "Context demo"

    def test_a_document_with_neither_says_this_workflow(self) -> None:
        assert workflow_label({"name": "  "}) == "this workflow"


class TestTheStreamingDoorIsTheSameDoor:
    """`/api/runs/stream` is what both shipped UIs actually use, so a refusal
    that only reached `/api/runs` would be a refusal most callers never see."""

    def test_it_refuses_before_a_single_frame(self) -> None:
        response = _client().post(
            "/api/runs/stream",
            json={"workflow": _document(DECLARATION), "question": "hello", "context": {"zzz": 1}},
        )

        assert response.status_code == 422, response.text
        assert "RunContext.__init__()" not in response.text

    def test_it_streams_as_before_for_a_workflow_declaring_nothing(self) -> None:
        response = _client().post(
            "/api/runs/stream", json={"workflow": _document(), "question": "hello"}
        )

        assert response.status_code == 200, response.text
