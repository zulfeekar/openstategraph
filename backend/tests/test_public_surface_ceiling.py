"""CLAUDE.md's ceiling, enforced rather than described.

    "A class with many public members is a design failure, not a convenience.
    If it can be described only with 'and', split it. Ceiling: ~10 public
    members, one reason to change."

`NodeRuntime` was at 26 when the system design review measured it
(reviews-2026-08-14 ticket 07) and failed the "and" test outright: builder
registry **and** model resolver **and** tool binder **and** diagnostics
accumulator **and** mount-identity registry. Its docstring defended only the
first.

This file exists because the count is the part that regrows. Every extraction
is one commit and one good intention; the attribute added six months later to
save a parameter is neither, and nothing would have said so. A ceiling nobody
measures is a preference.

**A member here is one a consumer can reach**: a public attribute assigned to
`self` anywhere in the class, or a public method. Collaborators count as one —
`runtime.services` is a member, `runtime.services.tools` is not, which is the
whole point of the grouping and also how `WorkflowController` is described in
CLAUDE.md.

**It measures a class, not an instance, and that took a second attempt.** Until
the 2026-08-15 audit this file called `vars()` on a *fresh* `NodeRuntime`, so it
could not see `last_bound_tools` — assigned inside `build_agent` rather than
`__init__`, and read by eight assertions across four test modules. A runtime
that had built one agent was a member wider than the pin claimed was possible,
and the pin could not fail. Attributes are therefore found by reading the class,
not by inspecting one object that happens not to have been used yet.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pkgutil
import textwrap
from functools import lru_cache

import pytest

import openstategraph

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.compile.node_runtime import NodeRuntime

#: The ceiling, from CLAUDE.md. "~10", read strictly — a rule with a soft edge
#: is a rule that is always nearly kept.
CEILING = 10


def assigned_to_self(cls: type) -> set[str]:
    """Public attributes the class gives itself, wherever it does it.

    `__init__` is the usual place and not the only one, which is exactly the
    defect this replaced: an attribute a method adds is as reachable as one the
    constructor adds, and considerably easier to add without noticing.
    """
    try:
        source = textwrap.dedent(inspect.getsource(cls))
    except (OSError, TypeError):  # pragma: no cover — no source (C, REPL)
        return set()
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and not target.attr.startswith("_")
            ):
                found.add(target.attr)
    return found


def _root_package(subject: type) -> str:
    return getattr(subject, "__module__", "").partition(".")[0]


def public_members(subject: type) -> set[str]:
    """What a consumer of this class can reach.

    Two exclusions, both deliberate, and one counting rule for every class this
    file measures:

    **Members inherited from a third party are not counted.** A Pydantic model
    reaches `model_dump`, `model_validate` and a dozen more; those are the
    vendor's contract, we cannot split them, and counting them would flag every
    model in the package for a design decision that is not ours to make. Only
    bases from the subject's own top-level package contribute.

    **A record's fields are not counted.** `ProviderSpec` and `Scorecard` are
    frozen dataclasses; their fields are the data they are, and "one reason to
    change" is a question about behaviour. So the numbers below are the audit's
    *behaviour* column rather than its raw one — which is also what makes
    `Scorecard`'s 17 a finding: that is 17 without its seven fields.
    """
    home = _root_package(subject)
    names: set[str] = set()
    for base in subject.__mro__:
        if _root_package(base) != home:
            continue
        names |= {name for name in vars(base) if not name.startswith("_")}
        names |= assigned_to_self(base)
    if dataclasses.is_dataclass(subject):
        names -= {field.name for field in dataclasses.fields(subject)}
    fields = getattr(subject, "model_fields", None)
    if isinstance(fields, dict):
        names -= set(fields)
    return names


@pytest.mark.parametrize(
    "subject",
    [
        pytest.param(NodeRuntime, id="NodeRuntime"),
        pytest.param(CompileDiagnostics, id="CompileDiagnostics"),
    ],
)
def test_it_stays_under_the_ceiling(subject: type) -> None:
    members = public_members(subject)

    assert len(members) <= CEILING, (
        f"{subject.__name__} has {len(members)} public members, "
        f"ceiling is {CEILING}: {sorted(members)}. Add a collaborator, not a member "
        "— or record the exception the way CLAUDE.md records WorkflowModel's."
    )


def test_an_attribute_a_method_adds_is_counted() -> None:
    """The pin's own failure mode, held open.

    `NodeRuntime.last_bound_tools` is the real instance of this and is asserted
    by name below; a fixture is what keeps the *counting* honest if that
    attribute ever moves into `__init__` and the class stops being the example.
    """

    class Sneaks:
        def __init__(self) -> None:
            self.declared = 1

        def later(self) -> None:
            self.added = 2

    assert public_members(Sneaks) == {"declared", "added", "later"}


def test_the_runtimes_members_are_each_nameable_without_and() -> None:
    """The count is the symptom; "described only with and" is the rule.

    Pinned by name rather than by number alone, so that swapping one concern
    for another silently — the refactor that keeps the count and loses the
    design — shows up as a diff here.
    """
    assert public_members(NodeRuntime) == {
        # What it is for: turning a node in a document into a graph node.
        "factory",
        "builder_for",
        # Who it collaborates with, as one named object each.
        "services",
        "diagnostics",
        "names",
        # What compiling this document established about the graph's own
        # names — see `machinery_nodes`' docstring for why it is not in
        # `names`.
        "machinery_nodes",
        # The seventh, named rather than hidden. Written by `_agent` after it
        # binds (`node_runtime.py:1459`) so a test can assert the wiring
        # produced the tools without a model — a test seam, and a test seam on
        # the public surface is still on the public surface. It is what the old
        # `vars()`-on-a-fresh-instance pin could not see.
        "last_bound_tools",
    }


# ---------------------------------------------------------------------------
# The census: every class over the ceiling, not the two somebody remembered.
# ---------------------------------------------------------------------------
#
# Until the 2026-08-15 audit this file pinned two classes and
# `src/publicSurfaceCeiling.test.ts` pinned three, against **nineteen** over the
# ceiling. Pins chosen by hand measure the classes somebody already worried
# about, which are the ones least likely to drift. So the list is not written
# here — it is *derived*, and the table below has to match it exactly. A class
# that grows past ten fails until somebody records why, and a class that shrinks
# fails until somebody records the smaller number.


def _census_key(subject: type) -> str:
    return f"{subject.__module__.removeprefix('openstategraph.')}.{subject.__qualname__}"


@lru_cache(maxsize=1)
def classes_over_the_ceiling() -> dict[str, int]:
    """Every class the shipped package defines whose surface clears the ceiling.

    `examples/` is excluded for the same reason mypy excludes it: those are
    *workflow packages* that happen to ship inside this distribution, written in
    the adopter's idiom rather than the framework's.

    An unimportable module raises rather than being skipped. A census that
    quietly measures less than it claims is the defect this whole file is about.
    """
    found: dict[str, int] = {}
    for module in pkgutil.walk_packages(openstategraph.__path__, "openstategraph."):
        if module.name.startswith("openstategraph.examples"):
            continue
        for value in vars(importlib.import_module(module.name)).values():
            if not inspect.isclass(value):
                continue
            origin = getattr(value, "__module__", "")
            if not origin.startswith("openstategraph.") or origin.startswith(
                "openstategraph.examples"
            ):
                continue
            count = len(public_members(value))
            if count > CEILING:
                found[_census_key(value)] = count
    return found


@dataclasses.dataclass(frozen=True)
class Recorded:
    """A count somebody looked at, with the argument that made it a decision.

    The review's finding, quoted by the TypeScript sibling: a number written
    down with its reasoning is a decision; the same number undocumented is a
    class nobody has looked at. Counts are **exact**. A class that drops a
    member fails here and gets re-recorded lower — an exception with room to
    spare is how a ceiling becomes a floor.
    """

    members: int
    reason: str


#: Twelve classes, four bases. `AbstractAgentNode` (19), `BaseRouter` (18),
#: `BaseGrader` (16) and `BaseOrchestrator` (13) declare a family vocabulary
#: once — CLAUDE.md's rule that a shared concern lives on the base — and every
#: leaf inherits it whole. `ReactAgentNode` adds nothing at all, `DeepAgentNode`
#: adds `subagents`, `CustomGraphNode` adds `runnable`, `Orchestrator` and
#: `PlanningOrchestrator` add only their own `split`. So this is four wide bases
#: counted twelve times, which is what "what a consumer can reach" honestly
#: means for a ladder.
PROMPT_LADDER = """Pinned at today's count with the reduction ticketed (install-experience 19),
    because the width has one cause and it is not "these classes do many
    things".

    Of `AbstractAgentNode`'s eighteen, seven exist only because the prompt is
    composed here: five ingredients held as loose attributes (`default_rules`,
    `rules`, `skill`, `replace_rules`, `context`) plus `system_prompt()` and
    `resolve_prompt()`, which build a fresh `SystemPrompt` on every call rather
    than the node holding one. `BaseRouter` and `BaseGrader` repeat it and add
    an accessor each — `describe_rules` is `return self.rules.strip()`, one
    line under the attribute it reads.

    Every count here came down by one on install-experience 21, which took the
    members nobody wanted rather than the design: `middleware_preset()` off the
    agent base (returned `{}`, never overridden by any tier), and the router's
    `describe_branches` / grader's `describe_rubric`, public override points
    with no override and one caller each — the `system_prompt()` a screen
    below them.

    `BaseOrchestrator` is the counter-example that turns this from an opinion
    into a measurement: same job, no `describe_*`, no `resolve_system_prompt`,
    thirteen members — and it is the one class here that ticket 21 did not
    move, because it had nothing dead to take. Folding the ingredients into one
    held `prompt: SystemPrompt` collaborator takes Agent to about eleven, Router
    to eleven, Grader to ten and Orchestrator to seven. That is a real refactor
    across a seam six tests read, not a rename, so it is a ticket rather than
    this commit."""

#: `BaseKnowledgeBuilder` is at exactly ten, which is the point.
KNOWLEDGE_BUILDERS = """A recorded exception, and the cheapest kind to defend: the base is at exactly
    the ceiling (`BaseKnowledgeBuilder`, ten), and every concrete builder is
    over it by declaring what kind of source it is. `SqlKnowledgeBuilder` is
    eleven — the base's ten plus `source_kind`. `AgenticKnowledgeBuilder` is
    fourteen because the agentic branch adds a second seam on top of the
    mechanical one (`MISSION`, `study_tools`, `explorer_prompt`, `explore`), and
    its two leaves add a `source_kind` and a `MISSION` string on top of that.

    Nothing here is a class doing two jobs. The whole leaf surface of
    `CodebaseKnowledgeBuilder` is two strings and one method; the behaviour —
    ownership, collision, target path, marker header, write — is declared once
    on the base, which is the shape the Interface/Abstract/Base/Concrete ladder
    is supposed to produce. Taking the family under ten would mean removing a
    member from the base, and the candidates (`marker_header`, `compose_prompt`)
    are single-caller helpers whose only sin is being public. Worth doing when
    the file is next open; not worth a rename across seven classes on its own."""

#: Five of the eleven are SQL string templates.
ENGINE_ADAPTERS = """A recorded exception: this is a data class the counting rule cannot see is
    one. `BaseEngineAdapter` is **five** members, and the two driver-backed
    leaves reach eleven by inheriting five SQL string templates
    (`LIST_TABLES_SQL`, `COLUMNS_SQL`, `FOREIGN_KEYS_SQL`, `DRIVER_MODULES`,
    `DRIVER_HINT`) from the private `_DriverBackedAdapter`, plus their `engine`
    name. They are `ClassVar` strings rather than dataclass fields, so the
    record exemption in `public_members` does not apply to them — but they are
    the same thing: the data that distinguishes Postgres from SQL Server.

    The behaviour each leaf actually declares is one method, `sample`. There is
    no "and" to split here, and moving the templates into a dataclass to satisfy
    the counter would be writing code for the measurement rather than the
    design."""

#: `BaseTool` is six; the leaves carry their own manifest.
PREBUILT_TOOLS = """A recorded exception, with the shape visible in the base they share:
    `BaseTool` is **seven** members, and every tool here clears the ceiling only
    by its own configuration on top of that. `SqlListTablesTool` and
    `SqlGetSchemaTool` are eleven, `SqlQueryTool` twelve — the tool contract,
    the four manifest constants (`name`, `description`, `node_type`, `Args`)
    and, for the last, `row_cap`. `YouTubeTranscriptTool` is fourteen for the
    same reason plus three settings (`language`, `allow_auto_captions`,
    `max_chars`) and one genuinely public method, `resolve`.

    **Every count here moved by one on 2026-08-16, and the +1 is the rule
    working rather than failing.** `as_langchain_tools()` is declared once on
    `BaseTool` — the plural binding seam `tool.mcp` needs, defaulting to
    `[self.as_langchain_tool()]` — so it is inherited by all fourteen tools
    instead of being re-declared on the one that needs it. That is exactly the
    anti-duplication rule CLAUDE.md states, and a census that counts inherited
    members will always charge a shared concern to every member of the family.
    The alternative shapes are worse in ways the ceiling is not measuring: a
    special case in the compiler's binding loop (one atom's knowledge inside
    `core`), or a parallel `IMultiTool` interface every consumer would have to
    check for. Two tools that were sitting exactly *at* ten crossed on the same
    commit for that one reason, which is why they arrive here together.

    Those manifest constants are how a tool declares itself to the editor — they
    are the atom's identity card, and the registry reads them off the class. A
    tool that hid them behind a collaborator would be a tool the node palette
    cannot describe. `resolve` is the one member worth a second look and it has
    a real caller; the rest is declaration, not surface."""

#: Twelve: the seven-member base, three manifest constants, a seam and a field.
MCP_TOOL = """A recorded exception, and one of the larger tools in the catalogue
    for a structural reason rather than a sprawling one. Twelve is the
    seven-member `BaseTool` contract, the three manifest constants every atom
    declares (`name`, `description`, `Args`), `document_state()`, and exactly
    one field of its own: `bindings`, the server rows this node resolved to.

    `document_state()` exists to be *tested*: the map's rule that a document
    may name a server but never carry a credential needs a seam a test can
    read, and a rule with no test is a wish.

    **This entry recorded fourteen and an argument, and mcp-connect ticket 04
    overturned the argument.** The three fields were `definition`, `selected`
    and `problem`, and the note here rejected collecting them into an
    `McpBinding` on the grounds that a collaborator written by one method and
    read by one method splits nothing. That held while a node was one server.
    A node is now N server rows, and each row resolves, fails and filters on
    its own — so the collaborator is not a second name for one thing, it is
    the thing there are several of. Three fields became one list, and the
    surface got smaller rather than larger."""

#: Seventeen behaviour members over seven fields.
SCORECARD = """A recorded exception, and the one that most looks like a violation. Fourteen
    of the seventeen are properties derived from the record's own fields —
    `execution_accuracy`, `exact_set_match`, `refusal_accuracy`,
    `latency_p50/p95`, `by_difficulty`, `verdict_counts` and so on — and a
    record deriving from itself is not a second reason to change: they all move
    when the definition of a correct answer moves, together, which is the test
    CLAUDE.md actually sets.

    The split was considered. `render`, `to_json` and `meets` are the three
    members with a different reason to change (presentation, wire format,
    policy) and they are also the only three anything outside this file calls —
    `cli.py:209` touches exactly those. So the candidate split produces a
    metrics object whose sole consumer is the renderer that would have been
    split from it, and a caller that reaches for `card.metrics.x` to read a
    number the scorecard is named after. That is the `WorkflowModel` argument in
    miniature and it lands the same way. Recorded, not deferred."""

#: Every class in the shipped package over the ceiling, with the reasoning that
#: makes each number a decision rather than an oversight. Derived list, hand
#: written arguments — `test_the_census_matches_the_record` holds the two
#: together.
RECORDED: dict[str, Recorded] = {
    "abc.agent.AbstractAgentNode": Recorded(18, PROMPT_LADDER),
    "abc.agent.BaseAgentNode": Recorded(18, PROMPT_LADDER),
    "abc.agent.ReactAgentNode": Recorded(18, PROMPT_LADDER),
    "abc.agent.DeepAgentNode": Recorded(19, PROMPT_LADDER),
    "abc.agent.CustomGraphNode": Recorded(19, PROMPT_LADDER),
    "abc.router.BaseRouter": Recorded(17, PROMPT_LADDER),
    "abc.router.Router": Recorded(18, PROMPT_LADDER),
    "abc.grader.BaseGrader": Recorded(15, PROMPT_LADDER),
    "abc.grader.Grader": Recorded(15, PROMPT_LADDER),
    "abc.orchestrator.BaseOrchestrator": Recorded(13, PROMPT_LADDER),
    "abc.orchestrator.Orchestrator": Recorded(13, PROMPT_LADDER),
    "abc.orchestrator.PlanningOrchestrator": Recorded(13, PROMPT_LADDER),
    "knowledge_builders.SqlKnowledgeBuilder": Recorded(11, KNOWLEDGE_BUILDERS),
    "knowledge_builders.AbstractWorkflowPointerBuilder": Recorded(11, KNOWLEDGE_BUILDERS),
    "knowledge_builders.RootKnowledgeBuilder": Recorded(13, KNOWLEDGE_BUILDERS),
    "knowledge_builders.ProjectKnowledgeBuilder": Recorded(13, KNOWLEDGE_BUILDERS),
    "knowledge_explorer.AgenticKnowledgeBuilder": Recorded(14, KNOWLEDGE_BUILDERS),
    "knowledge_explorer.ExplorerKnowledgeBuilder": Recorded(15, KNOWLEDGE_BUILDERS),
    "knowledge_explorer.CodebaseKnowledgeBuilder": Recorded(15, KNOWLEDGE_BUILDERS),
    "knowledge_engines.PostgresEngineAdapter": Recorded(11, ENGINE_ADAPTERS),
    "knowledge_engines.MssqlEngineAdapter": Recorded(11, ENGINE_ADAPTERS),
    "prebuilt_sql.SqlGetSchemaTool": Recorded(11, PREBUILT_TOOLS),
    "prebuilt_sql.SqlListTablesTool": Recorded(11, PREBUILT_TOOLS),
    "prebuilt_sql.SqlQueryTool": Recorded(12, PREBUILT_TOOLS),
    "prebuilt_youtube.YouTubeTranscriptTool": Recorded(14, PREBUILT_TOOLS),
    "prebuilt_mcp.McpTool": Recorded(12, MCP_TOOL),
    "evaluation.scoring.Scorecard": Recorded(17, SCORECARD),
}


def test_the_census_matches_the_record() -> None:
    """The half nobody had: a class cannot go over the ceiling unnoticed.

    Before this, the pins were chosen by hand — which measures the classes
    somebody already worried about, the ones least likely to drift, and left
    fourteen of nineteen unguarded including `WorkflowModel`, the exception
    CLAUDE.md argues at the most length.
    """
    census = classes_over_the_ceiling()

    unrecorded = sorted(set(census) - set(RECORDED))
    departed = sorted(set(RECORDED) - set(census))

    assert not unrecorded, (
        f"over the ceiling and not recorded: "
        f"{ {name: census[name] for name in unrecorded} }. Take it under "
        f"{CEILING} by adding a collaborator, or add it to RECORDED with the "
        "argument that makes the number a decision."
    )
    assert not departed, (
        f"recorded but no longer over the ceiling: {departed}. Good news — "
        "delete the entry, and its reasoning with it."
    )


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_each_recorded_count_is_exact(name: str) -> None:
    census = classes_over_the_ceiling()

    assert census[name] == RECORDED[name].members, (
        f"{name} is {census[name]}, recorded as {RECORDED[name].members}. "
        "Exact, not an upper bound: an exception with room to spare is how a "
        "ceiling becomes a floor."
    )


@pytest.mark.parametrize("reason", sorted({entry.reason for entry in RECORDED.values()}))
def test_every_exception_carries_reasoning(reason: str) -> None:
    # Length is a crude proxy for "somebody actually thought about this", and a
    # crude proxy beats none. Same threshold as the TypeScript sibling.
    assert len(reason.strip()) > 400
