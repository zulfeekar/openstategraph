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

    **And a method need not be written in the class body.** A function assigned
    in a class body is a method, which is how `NodeRuntime` binds the node
    families it keeps in `compile/nodes/` (`docs-and-gaps/03`). Reading only
    `inspect.getsource(cls)` would stop seeing every attribute those add — the
    census going quiet exactly where the code went, and `last_bound_tools`,
    written by `_agent`, is the live instance of it. So the scan follows each
    bound function to its own source.
    """
    sources = []
    try:
        sources.append(textwrap.dedent(inspect.getsource(cls)))
    except (OSError, TypeError):  # pragma: no cover — no source (C, REPL)
        return set()
    for value in vars(cls).values():
        if not inspect.isfunction(value) or value.__module__ == cls.__module__:
            continue
        try:
            sources.append(textwrap.dedent(inspect.getsource(value)))
        except (OSError, TypeError):  # pragma: no cover — no source
            continue
    source = "\n".join(sources)
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
        # binds (`node_runtime.py:1910`) so a test can assert the wiring
        # produced the tools without a model — a test seam, and a test seam on
        # the public surface is still on the public surface. It is what the old
        # `vars()`-on-a-fresh-instance pin could not see.
        "last_bound_tools",
        # The eighth, and the same kind of thing as `machinery_nodes`: a fact
        # about the graph this compile produced that only the compiler knows.
        # A mount is a closure, so LangGraph's `xray` cannot open it — unless
        # the compiler records which child ran under which node, a composition
        # cannot be drawn at all (`workflow-gallery` 28). Drawing only; no run
        # path reads it.
        "mounted_graphs",
        # The ninth, the same kind again: which of a skill node's two sources
        # this compile actually used — the file on disk, or the copy stored
        # beside it in the document (`launch-readiness` 94). Public because it
        # is a *seam*: `_static_text` and `state._wired_skill` both read it,
        # and while each resolved the fields for itself one of them was
        # reading a stale copy with nothing able to notice.
        "static_sources",
        # The tenth, and the ceiling exactly. The same kind again — a fact
        # about the graph this compile produced — answering the other half of
        # what a `token` frame's text is: `machinery_nodes` says *this is not
        # the reply*, this says *this IS the reply and a grader has still to
        # judge it* (`every-workflow-green` 45). Both clients that render that
        # text are blind to it through a mount, which is where the ticket's own
        # recording puts it.
        #
        # An eleventh needs a recorded exception, and this member is why the
        # sentence is worth reading twice: it was added at nine, which is the
        # last time adding one is free.
        "checked_nodes",
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


#: Five classes, two bases — down from seven when ticket 45 moved the prompt
#: machinery off `AbstractAgentNode`. `BaseAgentNode` (11) and `BaseRouter` (11)
#: declare a family vocabulary once — CLAUDE.md's rule that a shared concern
#: lives on the base — and every leaf inherits it whole. `ReactAgentNode` adds
#: nothing at all, `DeepAgentNode` adds `subagents`, `Router` adds
#: `destinations`. So this is two bases counted five times, which is what "what
#: a consumer can reach" honestly means for a ladder.
#:
#: **`AbstractAgentNode` and `CustomGraphNode` left this table** (ticket 45),
#: and the way they left is the argument for having made the move. Neither was
#: re-numbered downward by a member being deleted: the prompt machinery
#: descended one rung to `BaseAgentNode`, where the tiers that *have* a prompt
#: are, and the two classes that never used it fell under the ceiling as a
#: consequence. `CustomGraphNode`'s docstring had claimed since it was written
#: that "prompt machinery must never be forced onto this class"; it was being
#: forced by inheritance the whole time, and the count is what finally said so.
PROMPT_LADDER = """**Install-experience 19 landed, and this entry is the smaller half that
    remains.** The four families were 19 / 18 / 16 / 13 and every one of them
    was over the ceiling for the same reason: a node held its prompt's
    *ingredients* rather than its prompt. Five loose attributes
    (`default_rules`, `rules`, `skill`, `replace_rules`, `context`), plus a
    `system_prompt()` that rebuilt a fresh `SystemPrompt` from them on every
    call, plus an accessor per family that was `return self.rules.strip()` one
    line under the attribute it read.

    Each family now holds one composed `SystemPrompt` — `self.prompt`, built in
    `__init__` — and declares its locked machinery as one `PROMPT` ClassVar
    instead of `PREAMBLE` / `OUTPUT_CONTRACT` / `DEFAULT_RULES` sitting loose.
    That second move is a grouping the call sites already made rather than one
    invented for a count: `api/routes/system.py` and `mcp_server.py` both read
    preamble and contract *together*, for all four families, and `render()`
    already owned the order they compose in.

    **`BaseGrader` and `BaseOrchestrator` left this table entirely** — nine
    members each, under the ceiling, no argument needed. What keeps the other
    two here is not prompt composition at all, and naming it is the point of
    still writing this down:

    - **The agent base is eleven**, and every member is load-bearing: the
      tier's identity (`name`, `model`, `tools`, `prompt`), the two ClassVar
      declarations (`PROMPT`, `SLOT_ORDER`), the three resolvers, `build_agent`
      and `build`. That base is now `BaseAgentNode` rather than
      `AbstractAgentNode` (ticket 45) — the abstract rung above it keeps only
      what every tier uses, which is why it no longer appears in this table.
      `DeepAgentNode` reaches twelve by one field, `subagents`, which is the
      leaf declaring what makes it that tier.
    - **The router base is eleven** because four of them are the *branch*
      vocabulary, not the prompt: `branch_table`, `branches`, `fallback`,
      `route_key`. Collecting those into a `Branches` collaborator would take
      the base to eight, and it is the obvious next move — but `branches` and
      `fallback` are declared on the `IRouter` Protocol, which is Tier 1, so it
      is a public-contract change and not a tidy-up. Named here so the next
      person starts from it rather than from the count.

    The reduction is measured, not asserted: 19 -> 11, 18 -> 11, 16 -> 9,
    13 -> 9, and five classes off the census."""

#: `launch-readiness/104`: every agent-family node gained one public member,
#: `narrate`, the declared way to silence the base's default narration
#: middleware. Added to the counts above rather than folded into
#: `PROMPT_LADDER`, because it is a different member for a different reason —
#: the ladder is about prompt composition, this is about a run being
#: watchable.
NARRATE_TOGGLE = """`launch-readiness/104`: a silent model-driving step was found to be a defect on
    every agent, not a per-workflow opt-in — the owner watched a 40-second
    model call produce nothing visible and could not tell working from stuck.
    `AbstractAgentNode.resolve_middleware()` now fills a `"narration"` slot by
    default; `self.narrate` (default `True`) is the flag that turns it off
    without deleting the middleware, so "this node stays quiet" is a decision
    on the node rather than code someone removed. One field, on the base
    every tier already shares — `BaseAgentNode`, `ReactAgentNode` and
    `DeepAgentNode` each gain exactly one member over the counts `PROMPT_LADDER`
    argues for.

    `launch-readiness/106`'s retry inventory does **not** add a member here:
    the compiler (`compile/node_runtime.py`) builds the `NarrationMiddleware`
    instance itself — exactly as it already does for `rubric` and
    `summarization` — and keeps its own reference alongside the contribution
    it hands the node. The node never needs a second address for middleware
    it already resolves through the slot table; the retry path reads the
    instance the compiler made, not one fetched back off the agent."""

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

#: `BaseTool` is eight; the leaves carry their own manifest.
MSSQL_QUERY_TOOL = """One more than `SqlQueryTool`, and the difference is the ticket
    (`osg-agent-experience/34`). `MssqlQueryTool` carries `connection` and
    `allowlist` — the two things that differ between reading a file and reading
    a warehouse, which is the whole reason it is a sibling and not a copy — and
    does *not* carry `database`, which is the difference `39` made. Everything
    else on the count is inherited: `BaseTool`'s ten, the four manifest
    constants, `configure`, and `row_cap` — plus, since
    `osg-agent-experience/61`, the rung's `pins`, which is the seventeenth.
    The rung gained two that ticket and a leaf gains one: `description` is
    already assigned on every leaf, because a leaf names its own dialect in
    the sentence an agent reads before it writes SQL.

    **It was seventeen until 2026-09-05, and the seventeenth was a member this
    leaf could not use.** `database` came from `_SqlExplorerBase`, where it
    meant "a .sqlite path inside workflows/", and an ODBC connection has no
    such thing; `_refusal()` came with it and named that path. The count is now
    sixteen because the base was split along the line its own members already
    drew: `_SqlExplorerBase` keeps what no dialect can change — reading is not
    a side effect, the `maxRows` parse, the truncation-aware markdown table —
    and `_SqliteExplorerBase` keeps the file (`database`, the workflows-root
    jail, `_db`, `_refusal`). This leaf sits beside that rung, not under it.

    The family base itself is now **under** the ceiling and has left this
    record, which is the honest reading of the split rather than a member
    hidden behind a collaborator: three of its five members moved down to the
    three tools that use them, and none moved out of sight.
    """


#: The warehouse rung and its third leaf (`osg-agent-experience/40`).
WAREHOUSE_FAMILY = """A recorded exception at two levels, and the second is the
    reason the first is worth having.

    `_WarehouseExplorerBase` is **fourteen**: `BaseTool`'s ten, plus
    `allowlist`, `pins`, `row_cap` and `description`. None is behaviour — the
    first three are the values every warehouse leaf configures, and the first
    and third were already public on `MssqlQueryTool` before this rung existed.
    The rung's own behaviour is
    entirely private (`_pins`, `_scope`, `_described`, `_env_value`,
    `_local_names`, `_execute`, and the two seams a leaf fills in), because
    that is what it is: the wiring between the family and its dialects, not
    surface a consumer reads. Nothing became visible that was not visible
    before; two members moved up one rung and the leaves lost nothing.

    **Twelve until `osg-agent-experience/61`, and both of the two are that
    ticket.** `pins` is the subset of a shared allowlist one binding may read
    — the field that lets fifteen mounted specialists share one hand-curated
    file without sharing its tables. `description` is the same fact on the
    other side of the seam: `BaseTool` declares it as an *annotation* with no
    value, so nothing assigned it and the census never saw it; this rung
    assigns it per instance, because what a binding may read is part of what
    the model is told before it writes SQL. That is a member with a value, not
    a member with behaviour — `_described()` is private and runs once, at bind
    time — but it is genuinely one more thing a consumer can reach, and the
    honest record is the number rather than a cast that hides it.

    `DatabricksQueryTool` is **nineteen** — two more than `MssqlQueryTool`'s
    seventeen — and the two are `http_path` and `token`. `databricks-sql-connector`
    takes `server_hostname`, `http_path` and `access_token` as three separate
    arguments and publishes no connection-string form to fold them into, so
    where the T-SQL leaf names one variable this one names three. Each field
    holds the *name* of an environment variable, so each is a value a document
    carries and a person edits.

    The move that would take this to sixteen is a small object holding the
    three names, and it is refused for the reason `ENGINE_ADAPTERS` above
    refuses the same trade: that is writing code for the measurement rather
    than for the design. There is no "and" here to split — the class does one
    thing, reads one warehouse, and the count is the vendor's API surfacing in
    ours. A fourth dialect that needed a fourth variable would be twenty and
    still one reason to change.

    **What would make this dishonest is a member with behaviour**, and the
    census cannot tell the difference — so the argument is: every one of the
    nineteen is either `BaseTool`'s, a manifest constant, `configure`, or one
    of the six configured values. If a twentieth appears that is none of
    those, it is a second reason to change and this note has stopped being
    true.
    """


PREBUILT_TOOLS = """A recorded exception, with the shape visible in the base they share:
    `BaseTool` is **eight** members, and every tool here clears the ceiling only
    by its own configuration on top of that. `SqlListTablesTool` and
    `SqlGetSchemaTool` are twelve, `SqlQueryTool` thirteen — the tool contract,
    the four manifest constants (`name`, `description`, `node_type`, `Args`)
    and, for the last, `row_cap`. `YouTubeTranscriptTool` is fifteen for the
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
    a real caller; the rest is declaration, not surface.

    **And every count moved by one again on 2026-08-27, for the same reason,
    and this time it brought fifteen more classes with it**
    (`launch-readiness` 121). `BaseTool.side_effecting` is the eighth member of
    the base: whether calling this tool changes something outside the run, so
    the compiler can tell a mail sender from a SELECT before deciding whether a
    node it can run twice is worth a sentence. Declared once on the base, with
    a safe default, so no adopter's tool has to say anything — which is the
    anti-duplication rule and `async-first/04`'s additive rule at once, and
    which is precisely why the census charges it to all sixteen tools.

    Fifteen concrete tools were sitting at exactly ten and crossed on that one
    commit. They are recorded rather than refactored because the alternative is
    the one this paragraph already rejected twice: hiding a declaration behind
    a collaborator makes an atom the palette cannot describe, and there is
    nothing to split — a tool that reads has one reason to change whether it
    declares seven constants or eight. What the ceiling is measuring here is
    the base's declaration surface, counted sixteen times.

    **And once more on 2026-08-28** (`launch-readiness` 151).
    `BaseTool.open_world` is the tenth: whether this tool answers from outside
    the run's own data rather than from records it retrieved, so the compiler
    can say that a graph binding one to the step that writes the answer, with
    no gate between, can emit a number nothing retrieved. Same base, same
    default-on-the-base shape, same reason it is charged to every tool — and
    the count of tools moved from sixteen to twenty-one at the same time
    because `_SqlExplorerBase` crossed on this commit and joins the record.
    (That entry is `_SqliteExplorerBase` since `osg-agent-experience/39` split
    the family base in two; the rung the three file tools share is the one
    carrying `database`, and it is the one over the ceiling.)
    Its default is the *quiet* side rather than the safe one, which is the one
    thing that differs from `side_effecting`, and the argument is on the
    attribute itself.

    **And once more on 2026-08-27, same day, same base, different member**
    (`async-first/04`). `BaseTool.arun` is the ninth: the async twin of `run`,
    the caller's verb on the door `_aexecute` opens. This one is not a
    declaration but a *method*, so it is worth saying why it is on the base and
    not a collaborator. It is the same seam as `run` — validate the `Args`,
    call the body, turn an exception into a `ToolResult` — reached with `await`
    instead of a call. A second class holding it would be two spellings of one
    tool, drifting, with one of them under test; a free function taking a tool
    would be a method with the receiver written out longhand. `_aexecute`
    itself costs nothing here, being underscore-prefixed, and `ITool` was
    deliberately left alone: it is a `runtime_checkable` Protocol, and a member
    added to it un-satisfies every third-party object that satisfies it today.

    Nineteen tools plus `McpTool` moved by one, and this time **none of them
    crossed** — 121 had already taken every tool that was sitting at ten over
    the line, so the census gained no rows. That is the same +1 charged for the
    third time to the same sixteen classes, and the third time the answer is
    the one this paragraph has given twice: the alternative is a shared concern
    re-declared per tool, which is the rule this project does not break to
    flatter a count."""

#: Fourteen: the nine-member base, three manifest constants, a seam and a field.
MCP_TOOL = """A recorded exception, and one of the larger tools in the catalogue
    for a structural reason rather than a sprawling one. Fourteen is the
    nine-member `BaseTool` contract (`side_effecting` on `launch-readiness`
    121, `arun` on `async-first/04`), the three manifest constants every atom
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


MULTI_MATCH_PROMPT = """**Twelve and thirteen, not eleven and twelve, and the extra member is a
    second locked prompt.** `every-workflow-green` 27 gave a classifier a
    `matchMode`: `"best"` names one branch, `"all"` names every branch a
    compound question needs. A parser that accepts several names is useless if
    the prompt demands one — ticket 17 is the record of a prompt and its own
    parser disagreeing — so the mode has to reach the prompt.

    `PROMPT_ALL` is a second `ClassVar` beside `PROMPT` rather than string
    surgery at runtime, for the reason `PROMPT` is public in the first place:
    both are **locked sections** the editor renders read-only beside the one
    editable field, and a contract assembled at runtime from two half-sentences
    is one nobody can read in the source or on the card.

    The mode itself is deliberately **not** on the surface — it is `_match_mode`,
    constructor configuration that only `normalise` reads. This census caught it
    when it was public, which is the census working."""


FINDING_KINDS = """**An enum of seventeen, and the ceiling is asking the wrong question of it.**
    `Finding` has no methods and no state — every member is one *value*, and the
    number of them is the number of ways a compiled graph has been observed to
    come out less capable than it was drawn. There is no "and" to split on: a
    `Finding` with six members and a `SecondFinding` with five is one concept
    filed in two drawers, and `warnings()` would have to walk both.

    The reason to change is genuinely singular and it is the module docstring's:
    *the ways a graph can be incomplete*. That list grows every time a node type
    learns a new way to be silent, and the whole design of `diagnostics.py` is
    that such growth is a table entry rather than another attribute on
    `NodeRuntime` plus another loop in `runtime_warnings` — which is exactly the
    seven-field sprawl this module was extracted to end.

    Recorded rather than argued away: the eleventh member (`STALE_TOOL_DENIAL`,
    production-ready 89) is what took it over, and the honest statement is that
    an enum's member count is not the ceiling's subject. If a future member
    describes something that is not a lost capability, that is the split — by
    meaning, never by count.

    The twelfth (`STATELESS_MOUNT_REDOES`, `organisms-first-class` 65) is a
    live test of that last sentence and does **not** split the enum: what it
    describes is not a lost capability — a stateless mount over a workflow that
    holds an approval pauses, resumes and answers — but the split the paragraph
    above contemplates already exists and is `REPORT_ONLY`, a membership rather
    than a second drawer. Meaning decided the side; the count decided
    nothing.

    The thirteenth (`UNSUPPLIABLE_CONTEXT`, `organisms-first-class` 79) is the
    same paragraph read the other way: it *is* a lost capability — a mount
    whose child requires a run-context key its parent cannot name raises before
    `invoke`, so the composition produces no answer at all — which puts it on
    the failure side with `UNRESOLVED_SUBGRAPH`, whose class it shares. One
    more way for a graph to come out less capable than it was drawn, which is
    precisely what the module docstring says this list is, so it is a table
    entry and not a split.

    The fourteenth (`OVERRIDE_APPLIED`, `launch-readiness` 40) is the mirror
    of the split argued at the twelfth: `OVERRIDE_PROBLEM` already reported
    when a mount override failed to reach its target, and had no counterpart
    for when it succeeded — an override that DID apply and one that silently
    missed looked identical on `validate`/`run`, confirmable only by inferring
    scope from a run's own answer. What it describes is not a lost capability
    either, so it is `REPORT_ONLY` beside `STATELESS_MOUNT_REDOES` rather than
    a new drawer — one more table entry, same reasoning, same enum.

    The fifteenth (`MODEL_SELECTION_DEGRADED`, `launch-readiness` 45/62) is
    the same shape as the fourteenth: a node's own model selection resolved
    to something other than what it named, because this installation lacks a
    key or a provider package. What it describes is not a lost capability —
    the run still answers, on the shared default rather than the node's own
    choice — and blocking `validate`'s exit code on a missing credential
    would fail every shipped package naming a real provider in any
    environment that does not carry that provider's key, which is not what
    this report is for. `REPORT_ONLY`, one more table entry, same enum.

    The sixteenth and seventeenth (`REPEATED_SIDE_EFFECT` and
    `APPROVAL_COMES_TOO_LATE`, `launch-readiness` 121) arrive as a pair and are
    two entries rather than one, because they are two defects with two fixes:
    a node that acts outside the run and can be run twice is fixed by
    `maxRetries` or by the drawing, and an approval below the action is fixed
    by moving the approval. Collapsing them into one member would produce a
    sentence that named neither fix — which is the failure mode `_SENTENCES`'
    own rule ("name the consequence, not the condition") exists to prevent.
    Both are `REPORT_ONLY`, and the reason there is a new one: their condition
    is a conservative default about a tool nobody declared, and a guess may not
    move an exit code. Still the same reason to change — the ways a graph can
    come out other than it was drawn — so still a table entry, not a split.

    The nineteenth, twentieth and twenty-first (`SKILL_SOURCE_DRIFTED`,
    `SKILL_FROM_SNAPSHOT`, `SKILL_FILE_UNUSED`, `launch-readiness` 94) arrive
    as three for the sixteenth-and-seventeenth's reason: three conditions with
    three different fixes — re-save the document, accept that this door has no
    package to read from, or clear the instruction box — and one member would
    name none of them. They are the first entries describing a graph that came
    out *more* capable than the document records rather than less: the file on
    disk wins, so the run is right and the stored copy is stale. That is not a
    new drawer either, because the split by meaning already exists and is
    `REPORT_ONLY`, which is where all three sit. The reason to change is
    unchanged — the ways a compiled graph differs from the drawing.

    The twenty-second is `TIMEOUT_NEEDS_ASYNC_NODE` (2026-09-11,
    `langchain-drift-watch` 01), and it is the same argument again: a
    compiled graph differing from the drawing, here because LangGraph
    refuses a timeout on a synchronous node and the compiler drops it rather
    than handing over a combination that fails the whole build.
"""

#: Every class in the shipped package over the ceiling, with the reasoning that
#: makes each number a decision rather than an oversight. Derived list, hand
#: written arguments — `test_the_census_matches_the_record` holds the two
#: together.
ASYNC_CAPABLE_SAVER = """A recorded exception whose surface is not ours to choose. Every one of the
    twelve members is `BaseCheckpointSaver`'s own contract, implemented in
    full because `StateGraph.compile` `isinstance`-checks what it is handed
    and LangGraph's async loop calls the four `a*` methods while every
    synchronous caller in this process still calls the four sync ones: the
    sync four, their four async twins, `delete_thread` and `adelete_thread`,
    `get_next_version`, and `config_specs`.

    It has exactly one reason to change — *the wrapped saver has no async
    methods* (`SqliteSaver` raises `NotImplementedError` on all four, measured
    on the installed `langgraph-checkpoint-sqlite 3.1.1`) — and it adds no
    member of its own beyond the private `_inner`. Taking it under the ceiling
    would mean implementing part of an interface, which is not a smaller
    design but a broken one.

    Added by `async-first/02`, when the run fold began driving
    `graph.astream()`."""


ASYNC_DOORS = """**One added public member per model-driven verb, and the census is right to
    charge it to every rung** (`async-first/05`). The router, grader and
    orchestrator ladders each grew the awaitable twin of a verb they already
    had — `aclassify`, `agrade`, and `asplit`/`alabel`/`aplan` — so that an
    `async def` node body can await a model call instead of holding the event
    loop for it. That is the whole of this map's one user-visible promise at
    this seam: a thread cannot be interrupted, so only a natively awaited model
    call stops when the run stops.

    **Why it is a method on the base and not a collaborator.** It is the same
    seam as its synchronous twin — build the prompt, call the model, hand the
    answer to the same tolerant `normalise` — reached with `await` instead of a
    call. A second class holding it would be two spellings of one router,
    drifting, with one of them under test; a free function taking a router
    would be a method with the receiver written out longhand. What *is* a
    collaborator is the machinery underneath — `abc/async_doors.py`, module
    functions the three bases call — because that part is shared **across**
    families and CLAUDE.md's boundary rule says a cross-family concern is
    composed, never inherited. A common `AbstractAsyncCapableNode` above the
    three would be the god base class the same rule forbids.

    The private halves cost nothing here: the per-subclass doors
    `install_doors` writes take the *existing* names, and the message builders
    the two doors share are underscore-prefixed.

    The private halves are not the only thing that costs nothing: the agent
    ladder gained no member at all, and its absence from this paragraph is a
    finding rather than an omission. `AbstractAgentNode` makes no model call of
    its own — `build()` returns a Runnable and the caller awaits `ainvoke` on
    it — so there was no door to add, and an `abuild()` would have been surface
    with nothing behind it.

    **The router, first family: `BaseRouter` 12 -> 13, `Router` 13 -> 14.**
    Both by `aclassify`. Collecting the four branch-vocabulary members into a
    collaborator would take the base to nine and is still the obvious next
    move — see the paragraph above this one — and it is still blocked the same
    way: `branches` and `fallback` are declared on `IRouter`, which is Tier
    1.

    **The grader, second family: `BaseGrader` and `Grader` 10 -> 11**, by
    `agrade`, and they arrive in this table on that commit. Both were sitting
    at exactly the ceiling, which is the case this file exists to catch and not
    a reason to refuse the member: the ten are the family vocabulary declared
    once on the base — two locked prompt ClassVars, the composed prompt and its
    renderer, the model, the tolerant `normalise`, the deterministic prelude,
    the rubric, the verdict verb and the revise payload — and every leaf
    inherits them whole. `Grader` itself declares one method. There is no "and"
    to split: this class judges, and the awaitable half of judging is the same
    reason to change as the synchronous half.

    **The orchestrator, third family: `BaseOrchestrator`, `Orchestrator` and
    `PlanningOrchestrator` 9 -> 12**, by `asplit`, `alabel` and `aplan`, and
    all three arrive in this table on that commit. Three verbs rather than one
    is this family's shape rather than an excess: `plan` is built from `split`
    and `label`, so `aplan` can only await a model if both of those are
    awaitable too — a door that satisfied `aplan` and left it calling the
    synchronous `split` would put a model call back on the event loop by the
    longest route available, which is exactly the mistake `async-first/10`
    exists to avoid.

    Nine of the twelve were under the ceiling before this and would be again if
    the three were hidden — which is the move this whole file exists to refuse.
    The candidate collaborator is real and named here so nobody has to
    rediscover it: `split`/`asplit` and `label`/`alabel` are two *strategies*
    that a plan composes, and lifting them into a `Decomposition` and a
    `Labelling` would take the base to six. It is blocked the same way the
    router's branch vocabulary is: `plan` is declared on `IOrchestrator`, which
    is Tier 1, and the two strategies are what an adopter subclasses today —
    `split` is the ladder's only `@abstractmethod`. Worth doing behind a
    deprecation; not worth doing to flatter a count."""


#: `results.RunResult` — 12, and every one of them is a **field of one
#: record**, not a method of one object.
#:
#: This is the answer to "what did that run produce", and it has exactly one
#: reason to change: a run learns to produce something else. There is no
#: behaviour here to split — `total_tokens`, `failed_nodes` and `statements`'
#: neighbours are the run's own report, and a collaborator holding a subset of
#: them (`result.health.warnings`, `result.cost.usage`) would buy a smaller
#: number by making every caller learn which drawer their field is in. The
#: HTTP doors already ship the identical set as one flat object for the same
#: reason (`RunResponse`), and a library door whose shape disagreed with the
#: wire's would be its own defect.
#:
#: What the ceiling is actually protecting against is a class described only
#: with "and" — and this one is described with a list, which is what a record
#: is. The number stays exact rather than becoming a budget: the eleventh
#: member is `statements` (`one-chinook-honest` 30), and a twelfth still owes
#: this paragraph an argument that it is a fact about a finished run rather
#: than a capability bolted onto the object that carries one.
#:
#: The twelfth is `routes` (`launch-readiness/175`), and here is that argument.
#: It is a fact about a finished run in the most literal sense available: the
#: run computed it, named it and stored it in `RunState.routes` — *"router
#: node id -> every branch label it matched"* — and then no door published it,
#: so a router that matched one branch and a router that matched three left
#: identical rows in `decisions`. Not a capability: it answers "what did this
#: run produce" in the same voice `decisions` does, one field along, and it is
#: shipped flat on `RunResponse` for the reason the paragraph above gives.
RUN_RESULT = (
    "A record, not an object with behaviour: twelve fields answering one "
    "question — what did this run produce. One reason to change, which is the "
    "rule the ceiling exists to serve. Splitting them across collaborators "
    "would buy a smaller count by making every caller learn which drawer a "
    "field lives in, and would make the library door's shape disagree with "
    "`RunResponse`, which ships the same set flat over the wire. The eleventh "
    "is `statements` — what the run executed (`one-chinook-honest` 30) — "
    "added because the two correctness diagnoses that needed it ran the "
    "package in-process, where this object is the whole of what survives. "
    "The twelfth is `routes` — every branch a parallel router matched "
    "(`launch-readiness/175`) — a fact the run already computed and stored "
    "and that no door published, so one match and three read the same."
)

WORKFLOW_SERVICES = """A recorded exception rather than a split, for the reason the class's own
    docstring gives: it is "the assembly point every transport already
    shares" — HTTP and MCP alike — so its width is one collaborator per kind
    of shared state (`store`, `events`, `memory_store`, `checkpointer`,
    `principals`, `runtime_for`...), not one class doing several jobs. Ten
    was the count the moment somebody last measured it; eleven is
    `kanban-patrol/07`'s `patrol_events` (the sibling broadcaster for live
    patrol progress) and `patrol_jobs` (the one-slot job registry), both
    landing at once because a background patrol's HTTP route needs both to
    answer "did I start", "what happened", and "tell everyone watching" —
    and both belong here for the same reason `events` already does: this is
    the one place both transports would otherwise have to construct their
    own copy of, which is exactly the bug ticket 15 closed for the run
    seam. Splitting them into a second parameter object was considered and
    set aside: they are two views of one fact (one patrol, for the one
    project this process serves), constructed together, read together by
    the same route, and a second grouping object here would be one more
    name to import for two fields that already live beside their closest
    relative, `events`, which is the same in-process, single-worker,
    per-app-instance shape. The next collaborator that lands here needs
    this exception's number updated honestly, the same discipline
    `CLAUDE.md` already asks of every other entry in this table.

    Twelve is `osg-agent-experience/36`'s `kanban_events` — the watcher
    behind `GET /api/kanban/events`, which tells an open board that an agent
    in another process moved a card. It lands here for the reason `events`
    and `patrol_events` did, plus one this class has not had before: it owns
    a poll task whose lifetime is the set of connected boards, so a
    per-request copy would poll once per open tab rather than once per
    process.

    Thirteen is `osg-agent-experience/69`'s `workflow_events` — the watcher
    behind `GET /api/workflows/{slug}/events`, which tells the other tabs open
    on a package that the CLI, an agent, or one of their siblings rewrote its
    `workflow.json`. It lands here for the twelfth's reason exactly: it owns a
    poll task whose lifetime is the set of connected editors. It is deliberately
    *not* folded into `events`, the catalogue broadcaster: that one publishes
    only for writes through this API, which is three of the four writers of a
    document missing, and it is the same fan-out every open surface subscribes
    to rather than one per package.

    Fourteen is `team-board-and-gap-reports/18`'s `board` — which card store
    this process actually has, and the sentence for why it is not the one that
    was asked for. It lands here rather than as two methods for the reason the
    paragraph above states about width: it is one *kind* of shared state, read
    by three unrelated doors (the health endpoint, the card routes, and the
    watcher that polls the store), and probed exactly once at startup so that
    none of them pays for the question. Two methods would have been the same
    fourteenth member spelled as a fifteenth and a sixteenth; a second
    parameter object would be one more name to import for a fact that already
    lives beside its closest relative, `kanban_events`, which reads it. The
    same discipline applies to the fifteenth."""

DOCUMENT_FINDING_KINDS = """**The eleventh member, and it is `Finding`'s argument at a second door.**
    `FindingClass` has no methods and no state — every member is one *value*,
    and the number of them is the number of ways a document has been observed
    to disagree with what its own node types declare. There is no "and" to
    split on: half of them in a second enum would be one concept in two
    drawers, and `document_findings` would walk both.

    The eleventh (`UNWIRED_BRANCH`, `osg-agent-experience/76`) is what took it
    over, and it took it over by *narrowing* rather than by adding a subject:
    `UNWIRED_FALLBACK` was the same question asked of one port, and this is the
    general case behind it. Both are emitted by one check, which is the sense
    in which the module still has one reason to change — the ways a document
    disagrees with its own types — and the sense the ceiling's second clause
    asks about (`test_a_dispatch_table_does_not_hold_its_targets.py`).

    Kept as two members rather than collapsed into one, for `Finding`'s
    sixteenth-and-seventeenth reason: they carry two sentences with two fixes.
    A `fallback` is where a *check's own failure* goes, and the sentence says
    so; an ordinary branch's ending depends on the family
    (`osg-agent-experience/84`) — a routing node's unwired branch takes the
    declared fallback or stops the run at the node, while every other
    conditional family still falls through to the first wired branch. One
    member would name neither."""


RECORDED: dict[str, Recorded] = {
    "compile.diagnostics.Finding": Recorded(22, FINDING_KINDS),
    "document_checks.FindingClass": Recorded(11, DOCUMENT_FINDING_KINDS),
    "api.services.WorkflowServices": Recorded(14, WORKFLOW_SERVICES),
    "abc.agent.BaseAgentNode": Recorded(12, NARRATE_TOGGLE),
    "abc.agent.ReactAgentNode": Recorded(12, NARRATE_TOGGLE),
    "abc.agent.DeepAgentNode": Recorded(13, NARRATE_TOGGLE),
    "abc.orchestrator.BaseOrchestrator": Recorded(12, ASYNC_DOORS),
    "abc.orchestrator.Orchestrator": Recorded(12, ASYNC_DOORS),
    "abc.orchestrator.PlanningOrchestrator": Recorded(12, ASYNC_DOORS),
    "abc.grader.BaseGrader": Recorded(11, ASYNC_DOORS),
    "abc.grader.Grader": Recorded(11, ASYNC_DOORS),
    "abc.router.BaseRouter": Recorded(13, MULTI_MATCH_PROMPT + "\n\n    " + ASYNC_DOORS),
    "abc.router.Router": Recorded(14, MULTI_MATCH_PROMPT + "\n\n    " + ASYNC_DOORS),
    "knowledge_builders.SqlKnowledgeBuilder": Recorded(11, KNOWLEDGE_BUILDERS),
    "knowledge_builders.AbstractWorkflowPointerBuilder": Recorded(11, KNOWLEDGE_BUILDERS),
    "knowledge_builders.RootKnowledgeBuilder": Recorded(13, KNOWLEDGE_BUILDERS),
    "knowledge_builders.ProjectKnowledgeBuilder": Recorded(13, KNOWLEDGE_BUILDERS),
    "knowledge_explorer.AgenticKnowledgeBuilder": Recorded(14, KNOWLEDGE_BUILDERS),
    "knowledge_explorer.ExplorerKnowledgeBuilder": Recorded(15, KNOWLEDGE_BUILDERS),
    "knowledge_explorer.CodebaseKnowledgeBuilder": Recorded(15, KNOWLEDGE_BUILDERS),
    "knowledge_engines.PostgresEngineAdapter": Recorded(11, ENGINE_ADAPTERS),
    "knowledge_engines.MssqlEngineAdapter": Recorded(11, ENGINE_ADAPTERS),
    "prebuilt_sql._SqliteExplorerBase": Recorded(11, PREBUILT_TOOLS),
    "prebuilt_sql.SqlGetSchemaTool": Recorded(14, PREBUILT_TOOLS),
    "prebuilt_sql.SqlListTablesTool": Recorded(14, PREBUILT_TOOLS),
    "prebuilt_sql.SqlQueryTool": Recorded(15, PREBUILT_TOOLS),
    "prebuilt_warehouse._WarehouseExplorerBase": Recorded(14, WAREHOUSE_FAMILY),
    "prebuilt_mssql.MssqlQueryTool": Recorded(17, MSSQL_QUERY_TOOL),
    "prebuilt_databricks.DatabricksQueryTool": Recorded(19, WAREHOUSE_FAMILY),
    "prebuilt_youtube.YouTubeTranscriptTool": Recorded(17, PREBUILT_TOOLS),
    "prebuilt_mcp.McpTool": Recorded(15, MCP_TOOL),
    "knowledge_explorer.CodeGrepTool": Recorded(13, PREBUILT_TOOLS),
    "knowledge_explorer.CodeLsTool": Recorded(13, PREBUILT_TOOLS),
    "knowledge_explorer.CodeReadTool": Recorded(13, PREBUILT_TOOLS),
    "knowledge_explorer.WriteTopicTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_architect.ValidateWorkflowTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_email.EmailSendTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_knowledge.KnowledgeLookupTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_platform.DescribeWorkflowTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_platform.ListWorkflowsTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_platform.PlatformGrepTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_platform.PlatformLsTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_platform.PlatformReadTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_session.SessionIdentityTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_web.WebFetchTool": Recorded(13, PREBUILT_TOOLS),
    "prebuilt_web.WebSearchTool": Recorded(13, PREBUILT_TOOLS),
    "evaluation.scoring.Scorecard": Recorded(17, SCORECARD),
    "memory._AsyncCapableSaver": Recorded(12, ASYNC_CAPABLE_SAVER),
    "results.RunResult": Recorded(12, RUN_RESULT),
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
