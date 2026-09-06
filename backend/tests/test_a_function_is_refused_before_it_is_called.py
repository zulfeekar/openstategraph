"""A parameter list decides how a function is called, so validate reads it.

`osg-agent-experience/59`. The delegating wrappers of `58` were first written
the obvious way:

    def honest_findings(*args, **kwargs):
        return _module.honest_findings(*args, **kwargs)

and the run failed at the guard with *"TypeError: honest_findings() takes 1
positional argument but 2 were given"* — reported as the review's last reason,
after the lens had been run and paid for. `guard.check` decides between
`fn(text)` and `fn(text, summary)` by **inspecting the signature**, so a
variadic wrapper reads as accepting two, gets two, and forwards two to a
one-argument implementation.

Two things were wrong and only one of them is the wrapper's fault. The arity
contract was discovered by inspection and documented nowhere a developer meets
it; and the mismatch was a *run-time* failure on a surface — `validate` — that
already imports these modules for nothing but a lookup.

Both are one table now (`function_contracts.CALL_CONVENTIONS`): the check reads
it, and the field hints are asserted against it, so a fifth family cannot
arrive with a convention nobody wrote down.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.function_contracts import CALL_CONVENTIONS
from openstategraph.validation import uncallable_functions

FUNCTIONS = '''
def one(text):
    """A check written the way the contract says."""
    return ""


def variadic(*args, **kwargs):
    """The delegating wrapper that got this wrong."""
    return ""


def takes_nothing():
    """No caller of any of these node types can satisfy this."""
    return ""


def takes_three(a, b, c):
    """Nor this."""
    return ""
'''


def _package(tmp_path: Path, nodes: list[dict]) -> Path:
    package = tmp_path / "workflows" / "lens"
    (package / "functions").mkdir(parents=True)
    (package / "functions" / "checks.py").write_text(FUNCTIONS)
    document = {"nodes": nodes, "edges": []}
    (package / "workflow.json").write_text(json.dumps(document))
    return package


def _guard(check: str) -> dict:
    return {"id": "gate1", "type": "guard.check", "data": {"check": check}}


class TestASignatureNoCallerCanSatisfy:
    def test_a_function_taking_nothing_is_refused_by_name(self, tmp_path: Path) -> None:
        package = _package(tmp_path, [_guard("takes_nothing")])
        findings = uncallable_functions(json.loads((package / "workflow.json").read_text()), package)
        assert findings, "a function no call can reach must not pass validate"
        assert "takes_nothing" in findings[0]
        assert "gate1" in findings[0]

    def test_the_message_names_the_shapes_this_node_type_calls(self, tmp_path: Path) -> None:
        package = _package(tmp_path, [_guard("takes_three")])
        message = uncallable_functions(
            json.loads((package / "workflow.json").read_text()), package
        )[0]
        assert "fn(text)" in message and "fn(text, summary)" in message, message

    def test_a_function_that_fits_is_not_a_finding(self, tmp_path: Path) -> None:
        package = _package(tmp_path, [_guard("one")])
        assert uncallable_functions(json.loads((package / "workflow.json").read_text()), package) == []

    def test_a_name_nothing_resolves_is_left_to_the_finding_that_owns_it(
        self, tmp_path: Path
    ) -> None:
        # `UNRESOLVED_FUNCTION` already reports this, by name, at the same
        # surface. Two sentences about one absence is how a list stops being
        # read.
        package = _package(tmp_path, [_guard("nobody_wrote_this")])
        assert uncallable_functions(json.loads((package / "workflow.json").read_text()), package) == []


class TestTheVariadicWrapper:
    """The shape that got this wrong, and the only one the platform *chooses*."""

    def test_it_is_reported_where_the_platform_picks_by_inspection(
        self, tmp_path: Path
    ) -> None:
        package = _package(tmp_path, [_guard("variadic")])
        findings = uncallable_functions(
            json.loads((package / "workflow.json").read_text()), package
        )
        assert findings, "a signature read as two-argument must be reported before a run"
        assert "variadic" in findings[0]
        assert "two" in findings[0].lower(), findings[0]

    def test_it_is_not_reported_where_only_one_shape_exists(self, tmp_path: Path) -> None:
        # `route.check` calls `fn(text)` and never anything else, so a
        # variadic function there is called with one argument and works.
        package = _package(
            tmp_path,
            [{"id": "fork1", "type": "route.check", "data": {"check": "variadic"}}],
        )
        assert uncallable_functions(json.loads((package / "workflow.json").read_text()), package) == []


class TestTheContractIsWrittenWhereADeveloperMeetsIt:
    @pytest.mark.parametrize(
        "convention", CALL_CONVENTIONS, ids=lambda c: f"{c.node_type}.{c.field}"
    )
    def test_the_field_hint_states_the_signature_it_calls(self, convention) -> None:
        specs = json.loads(
            (Path(__file__).resolve().parents[2] / "backend" / "openstategraph" / "compile"
             / "port_specs.json").read_text(encoding="utf-8")
        )
        entry = next(n for n in specs["node_types"] if n.get("type") == convention.node_type)
        field = next(f for f in entry["fields"] if f["key"] == convention.field)
        hint = str(field.get("hint") or "")
        for shape in convention.spellings:
            assert shape in hint, f"{convention.node_type}'s {convention.field} hint never says {shape}"


class TestTheSurfaceThatReportsIt:
    def test_validate_refuses_the_package_and_prints_the_signature(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from openstategraph import cli

        package = _package(tmp_path, [_guard("variadic")])
        code = cli.main(["validate", str(package)])
        printed = capsys.readouterr().out
        assert code == cli.EXIT_FAILURE
        assert "variadic" in printed
        assert "fn(text)" in printed, printed
