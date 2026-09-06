"""The shape a generated module must have, checkable rather than hoped for.

`every-workflow-green` 34, item 2 of its own **Next** list. The door was built
on 2026-08-19: a run that finds no shipped tool for what it was asked shows
*"Nothing here does this — build one for this workflow"*, and pressing it seeds
the chat with a brief naming five shape rules. Item 1 of that list.

Item 2 asked for the missing half: **one contract the skill and a test both
read**, so the ladder and the run seam are checked rather than described. This
file is the test half; `openstategraph.generated_module_contract` is the
contract.

## The gate that matters most is the first one

`test_every_clause_names_something_this_installation_has`.

Until this test existed, the brief instructed every developer who pressed that
button to *"read state, context and memory through ToolRuntime, not around
it"* — and **`ToolRuntime` does not exist anywhere in this platform**. It is a
LangChain construct we do not surface: `grep -rl ToolRuntime` over the whole
checkout matched three files, all of them the brief and its own test and one
decision note recording the mechanism as *"flagged, not decided"*. A tool here
receives its validated `Args` and nothing else; what it can actually reach is
its node's config through `configure(data)`, the run through
`langgraph.config.get_config()`, and memory through `get_store()` — and graph
state not at all.

So the brief's central clause named a seam a developer could not find, in a
product whose own build skill's law is *do not promise which is not possible*.
Seven tests held that wording and every one was green, because they all asked
whether the **words** were present. None asked whether the thing the words name
**exists here**. That asymmetry is the whole argument for the gate: the catch
has to be structural, not attentive.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from openstategraph.generated_module_contract import (
    CLAUSES,
    UNWIRED_SEAMS,
    check_generated_module,
    resolve_seam,
)

ROOT = Path(__file__).resolve().parents[2]


def test_every_clause_names_something_this_installation_has() -> None:
    """Every symbol a clause names resolves **here**, not in some other product.

    A clause is allowed to be demanding. It is not allowed to be fictional.
    """
    unresolved = [
        (clause.id, symbol)
        for clause in CLAUSES
        for symbol in clause.seam
        if resolve_seam(symbol) is None
    ]
    assert unresolved == [], (
        "A clause names a seam this installation does not have: "
        f"{unresolved}. Either wire the seam or change the clause — do not "
        "promise which is not possible."
    )


def test_the_clauses_are_distinct_and_stable() -> None:
    ids = [clause.id for clause in CLAUSES]
    assert len(ids) == len(set(ids))
    assert all(clause.rule and clause.why for clause in CLAUSES)


# --------------------------------------------------------------------------
# The checker, against the one workflow-scoped tool module that ships.


CHINOOK = ROOT / "workflows" / "chinook-assistant" / "tools" / "chinook.py"


@pytest.mark.skipif(not CHINOOK.exists(), reason="example package not checked out")
def test_the_shipped_workflow_tool_passes_its_own_contract() -> None:
    """The contract is calibrated against a real module, not against a fixture.

    If the only thing that satisfies it is something written to satisfy it, the
    contract is a shape rather than a rule.
    """
    assert check_generated_module(CHINOOK) == ()


def _write(tmp_path: Path, body: str, *, name: str = "made.py") -> Path:
    package = tmp_path / "some-package"
    (package / "tools").mkdir(parents=True)
    (package / "workflow.json").write_text("{}")
    path = package / "tools" / name
    path.write_text(body)
    return path


LADDER_OK = """
from pydantic import BaseModel
from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult


class PingTool(BaseTool):
    name = "ping"
    node_type = "tool.ping"
    description = "Ping."
    Args = NoArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        return ToolResult(content="pong")
"""


def test_a_plain_function_is_not_on_the_ladder(tmp_path: Path) -> None:
    path = _write(tmp_path, "def ping():\n    return 'pong'\n")
    assert any(v.clause == "ladder" for v in check_generated_module(path))


def test_a_subclass_that_never_implements_execute_is_not_a_leaf(tmp_path: Path) -> None:
    body = LADDER_OK.replace(
        '    def _execute(self, args: BaseModel) -> ToolResult:\n        return ToolResult(content="pong")\n',
        "",
    )
    path = _write(tmp_path, body)
    assert any(v.clause == "ladder" for v in check_generated_module(path))


def test_a_module_reaching_for_an_unwired_seam_is_refused(tmp_path: Path) -> None:
    """The defect this whole file exists for, as a module rather than as words."""
    body = LADDER_OK.replace(
        "    def _execute(self, args: BaseModel) -> ToolResult:",
        "    def _execute(self, args: BaseModel, runtime: 'ToolRuntime') -> ToolResult:",
    )
    violations = check_generated_module(_write(tmp_path, body))
    assert any(v.clause == "run-seams" for v in violations)
    assert any("ToolRuntime" in v.detail for v in violations)


def test_a_key_the_module_reads_but_never_declares_is_refused(tmp_path: Path) -> None:
    """Gate 7's defect, in a generated module: `data["k"]` reads `""` forever."""
    body = (
        LADDER_OK
        + """
    def configure(self, data):
        return type(self)(channel=data.get("channel"))
"""
    )
    assert any(v.clause == "declared" for v in check_generated_module(_write(tmp_path, body)))


def test_a_declared_key_the_module_reads_is_accepted(tmp_path: Path) -> None:
    body = (
        LADDER_OK.replace(
            "    Args = NoArgs\n",
            '    Args = NoArgs\n    node_fields = (ToolField(key="channel", label="Channel"),)\n',
        ).replace(
            "from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult",
            "from openstategraph.abc.tool import BaseTool, NoArgs, ToolField, ToolResult",
        )
        + """
    def configure(self, data):
        return type(self)(channel=data.get("channel"))
"""
    )
    assert check_generated_module(_write(tmp_path, body)) == ()


def test_a_pasted_credential_is_refused(tmp_path: Path) -> None:
    body = LADDER_OK.replace(
        'description = "Ping."', 'description = "Ping."\n    token = "ghp_aaaabbbbccccdddd"'
    )
    assert any(
        v.clause == "no-credential-value" for v in check_generated_module(_write(tmp_path, body))
    )


def test_a_module_written_into_the_installed_package_is_refused(tmp_path: Path) -> None:
    """The rule that is testable and root-independent, unlike any literal path."""
    import openstategraph

    installed = Path(openstategraph.__file__).resolve().parent
    intruder = installed / "tools" / "made.py"
    violations = check_generated_module(intruder, exists_check=False)
    assert any(v.clause == "package-own-tools" for v in violations)


def test_a_module_outside_any_package_is_refused(tmp_path: Path) -> None:
    stray = tmp_path / "made.py"
    stray.write_text(LADDER_OK)
    assert any(v.clause == "package-own-tools" for v in check_generated_module(stray))


# --------------------------------------------------------------------------
# The brief the developer is handed is the same contract, in the same words.


BRIEF_TS = ROOT / "src" / "view" / "ask" / "moduleBrief.ts"


def _brief_shape_block() -> str:
    """The rendered "Then build it to this shape:" lines of `moduleBrief.ts`.

    A small reader, not a parser, and it **raises** rather than returning `""`
    — an extractor that silently matches nothing would make the assertion
    below vacuous, which is the trap `test_prompt_mirror_contract` names and
    `test_the_extractor_would_notice_a_rename` guards.
    """
    text = BRIEF_TS.read_text()
    marker = "Then build it to this shape:"
    if marker not in text:
        raise AssertionError(f"{BRIEF_TS.name} no longer opens a shape block")
    body = text[text.index(marker) : text.index("].join(")]
    # Drop the concatenation glue between adjacent literals, and the quotes and
    # backticks themselves, so a clause that had to wrap across three lines in
    # TypeScript still reads as one sentence.
    for glue in ("' + '", "' + `", "` + '", "` + `", "'\n      + '", "`\n      + `"):
        body = body.replace(glue, "")
    body = re.sub(r"[`']\s*\+\s*[`']", "", body)
    return _normalise(body.replace("${where}", "{package}"))


def _normalise(text: str) -> str:
    return " ".join(text.replace("\u2019", "'").split())


@pytest.mark.skipif(not BRIEF_TS.exists(), reason="editor sources not checked out")
def test_the_door_hands_over_exactly_these_clauses() -> None:
    """The mirror pin. A contract nothing consumes is a document, not a gate.

    `moduleBrief.ts` is the one surface where these rules reach a human, and it
    is TypeScript because it must render with no server reachable. CLAUDE.md
    allows a hand-mirror of a Python contract *only* where a drift test pins
    it; this is that pin.
    """
    shape = _brief_shape_block()
    missing = [clause.id for clause in CLAUSES if _normalise(clause.rule) not in shape]
    assert missing == [], f"The brief no longer carries: {missing}\n{shape}"


@pytest.mark.skipif(not BRIEF_TS.exists(), reason="editor sources not checked out")
def test_the_brief_no_longer_names_a_seam_that_is_not_here() -> None:
    """The regression this ticket was, stated as the thing it must never be again."""
    body = BRIEF_TS.read_text()
    shipped = body[body.index("export function moduleBrief") :]
    for name in UNWIRED_SEAMS:
        assert name not in shipped, (
            f"The brief hands a developer {name}, which this installation does "
            "not surface. Do not promise which is not possible."
        )


def test_the_shape_extractor_is_not_vacuous() -> None:
    """The positive control. Ticket 47's lesson, applied on the way past."""
    assert len(_brief_shape_block()) > 200


# --------------------------------------------------------------------------
# The skill's half of "one contract the skill and a test both read".


SKILL_PAGE = ROOT / "skills" / "atom-forge" / "references" / "generated-module-contract.md"


def test_the_skill_page_is_the_contract_and_has_not_drifted() -> None:
    """Generated and committed, like `docs/openapi.json` — never hand-written.

    `skills/atom-forge/` is plain markdown and agent-agnostic on purpose, so it
    cannot import the clause list; publishing it is the only way the skill and
    this test read the *same* thing rather than two copies that agree today.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "render_contract", ROOT / "scripts" / "render_generated_module_contract.py"
    )
    assert spec and spec.loader
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)

    assert SKILL_PAGE.read_text() == renderer.render(), (
        "skills/atom-forge/references/generated-module-contract.md is stale. "
        "Run: python3 scripts/render_generated_module_contract.py"
    )


def test_the_skill_names_the_contract_page() -> None:
    """A reference nothing routes to is a file, not a step."""
    skill = (ROOT / "skills" / "atom-forge" / "SKILL.md").read_text()
    assert "generated-module-contract.md" in skill


def test_a_packages_reexport_file_is_not_asked_to_be_a_tool(tmp_path: Path) -> None:
    """Found by pointing the checker at a real `tools/` folder rather than at
    one file. `__init__.py` holds re-exports and no capability, and discovery
    already draws that line for the same reason."""
    path = _write(
        tmp_path, "from .made import PingTool\n\n__all__ = ['PingTool']\n", name="__init__.py"
    )
    assert not any(v.clause == "ladder" for v in check_generated_module(path))
