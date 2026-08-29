"""A class has a ceiling and a module has none. This is the module's.

`test_public_surface_ceiling.py` opens with the sentence that made this file
necessary, and it is about a class's *width*:

    This file exists because the count is the part that regrows. Every
    extraction is one commit and one good intention; the attribute added six
    months later to save a parameter is neither, and nothing would have said
    so. **A ceiling nobody measures is a preference.**

It applies word for word to a module's *length*, and until now nothing measured
that. The evidence is `compile/node_runtime.py`. `docs-and-gaps/03` was charted
against it at **1,639** lines; when somebody finally looked, on 2026-08-22, that
ticket's own resolution records the premise as *"stale by 2.5x"* — 4,127 — and
the split it then performed moved 401 lines out, leaving 3,751. A second
extraction (`compile/state.py`) landed after that. On 2026-08-29 the file is
**5,331** physical lines. It grew by more than fifteen hundred lines in the week
after the split that was supposed to shrink it, and nothing reported it, for
exactly the reason the number was 2.5x stale in the first place.

## What this counts, and why it is not physical lines

Physical lines are the cheap measure and the wrong one **here specifically**.
This repository writes long, argued docstrings on purpose — `CLAUDE.md`
requires it, every module above the ceiling opens with one, and half this file
is one. A physical-line ceiling would tax the practice the rules most want and
reward deleting the reasoning, which is the opposite of the whole map this
ticket belongs to.

So a module is measured in **code lines: physical lines carrying at least one
token that is not a comment and not a docstring.** On `node_runtime.py` that is
2,039 against 5,331 physical — 62% of the file is prose and blank space, and
none of it is charged for.

The alternatives were priced and rejected:

- **Statements (AST nodes).** More principled on the Python side and blind on
  the TypeScript one: `AskPanel.tsx`'s 907 code lines are largely JSX, which is
  one expression inside one `return`. A measure that reads zero on the biggest
  file in `src/` is not a measure.
- **Top-level definitions.** Ranks `api/schemas.py` (55 declarations, 425 code
  lines, entirely declarative Pydantic) above `mcp_server.py` (7 definitions,
  654 code lines). It counts the thing that is cheap to add and misses the
  thing that grows.
- **Public names exported.** That is the class census's measure raised a level,
  and it already has a file. A module's problem is not always its surface —
  `node_runtime.py` exports very little and is the file this ticket found.

A multi-line string that is not a docstring — a prompt, a SQL block — does
count, and that is deliberate: it is content someone has to read, and the
recorded-exception mechanism below is where a file argues that its bulk is
declarative rather than complex.

## Ceiling **and** ratchet, because they are one mechanism

The ticket asked which, and the answer the class censuses already worked out is
both, in one table:

- The **ceiling** (500 code lines) decides *which* modules have to be argued
  for. It is not a target and no file is asked to shrink to it.
- The **recorded number is exact**, which makes it a **ratchet**. A file that
  grows fails; a file that shrinks fails too and gets re-recorded lower. That is
  `WorkflowModel`'s pinned 43 doing its job — the number is a tripwire, not a
  goal.

A bare ceiling would be red on day one for ten files, which is how a pin
acquires a `# noqa` and dies. A bare ratchet with no ceiling would put a number
on all 434 modules in this repository, which is a config file nobody reads. The
ceiling picks a set small enough that every member can carry a real argument;
the exact number is what fires on the growth this ticket found.

**The escape hatch is one keystroke and this file does not pretend otherwise.**
Bumping a recorded number is a one-character diff. What stops it being a
formality is the same thing that stops it in the class censuses: the number and
the argument live in the same table, so raising the number lands in review
beside a paragraph that has to still be true afterwards. That is a social gate,
not a technical one. Said plainly here so nobody mistakes it for a stronger
claim.

The TypeScript sibling is `src/moduleSizeCeiling.test.ts`, measuring the same
thing the same way, because a module rule enforced on one side would be a third
description of a rule that already has two.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import pathlib
import tokenize
from functools import lru_cache

import pytest

import openstategraph

#: Five times the median Python module in this package (101 code lines) and nine
#: times the median under `src/` (56). Chosen from the distribution rather than
#: for roundness: at 500 the census names ten modules across both languages,
#: which is the same order as the class censuses' tables and small enough that
#: every entry can carry an argument somebody actually wrote. At 400 it names
#: eighteen, and a table that large is one where the eleventh entry gets filler.
CEILING = 500

PACKAGE_ROOT = pathlib.Path(openstategraph.__path__[0])


def code_lines(source: str) -> int:
    """Physical lines carrying a token that is neither comment nor docstring.

    Blank lines, comment lines and every line of a module, class or function
    docstring are free. Everything else — including a multi-line prompt string —
    is charged for.
    """
    carried: set[int] = set()
    skip = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in skip:
            continue
        carried.update(range(token.start[0], token.end[0] + 1))

    documented: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            documented.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    return len(carried - documented)


@lru_cache(maxsize=1)
def modules_over_the_ceiling() -> dict[str, int]:
    """Every shipped module longer than the ceiling — derived, never listed.

    `examples/` is excluded for the same reason the class census excludes it:
    those are workflow packages that happen to ship inside this distribution,
    written in the adopter's idiom rather than the framework's. Tests are
    excluded because they are not the app — a test module is allowed to be as
    long as the argument it is making, and this one is.

    Nothing is skipped for being unparseable. A census that quietly measures
    less than it claims is the defect this whole file is about.
    """
    found: dict[str, int] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        if relative.startswith("examples/"):
            continue
        measured = code_lines(path.read_text(encoding="utf-8"))
        if measured > CEILING:
            found[relative] = measured
    return found


@dataclasses.dataclass(frozen=True)
class Recorded:
    """A length somebody looked at, with the argument that made it a decision.

    Straight from the class census: a number written down with its reasoning is
    a decision; the same number undocumented is a file nobody has opened.
    """

    lines: int
    reason: str


NODE_RUNTIME = """
The file this ticket found, and the only entry here with a split already
written for it. `docs-and-gaps/03` is open and `partially` resolved, carrying a
recommended order for the remaining seams — `mount_overrides.py`, then
`reporting.py`, then the `compile/nodes/` rewrite last against a test written
first. None of that moves here and this number is not a substitute for it.

What the number is for is the growth. The split of 2026-08-22 moved 401 lines
out; the week that followed put more than fifteen hundred back, with a second
extraction landing in between, and no one knew until somebody ran `wc -l`
against a ticket charted at 1,639. Two thousand and thirty-nine code lines is
what that history costs today, recorded exactly so the next fifteen hundred
arrive as a red test rather than as a discovery.

The module does pass every rule `CLAUDE.md` states in words. It has a
one-sentence description; it has one reason to change (it is the node
builders); `NodeRuntime` the class is at 8 public members and under the class
ceiling by name. That a file can pass all of that at 5,331 physical lines is
the asymmetry this entry exists to make visible, and the argument for having a
length measure at all rather than trusting the ones already written down.
"""

CLI = """
`argparse` is the whole of it. This module's own header states the two rules it
lives under — **no new logic** (every command wraps a seam that already exists:
`load_workflow`, `ValidateWorkflowTool`, `scaffold`, `run_build`,
`PackageKnowledge`, `api.main:app`, `mcp_server.main`) and **argparse only**,
because a project arguing for a four-dependency core cannot then add `click`
and `rich` for colour and a decorator syntax.

Both rules push length here on purpose. Rejecting `click` means every command's
flags are hand-declared `add_argument` calls, which is the single largest block
in the file and is pure declaration; rejecting new logic means the bodies stay
thin but the *count* of commands is the surface a CLI actually has. Forty-nine
top-level definitions across 1,097 code lines is roughly twenty lines per
command including its parser.

The seam that would shorten it is one subcommand module per verb, and it is a
real option rather than a rejected one — it is simply not free: the module is
Tier 2 provisional as an import but the *command line* follows the Tier 1
deprecation policy, so the split is invisible to users and costs a package
where a file is today. Recorded rather than done, and the next person should
start by asking whether `run`, `eval` and `build` want their own modules — they
are the three with real argument surfaces.
"""

WORKFLOW_COMPILER = """
The compile seam itself: `workflow.json` in, a LangGraph `StateGraph` out, one
directional. Its length is the topology vocabulary, and the split that keeps it
from being longer is already made and is load-bearing — this file owns
**topology** and knows nothing about models, prompts or tools, while
`node_runtime.py` owns **behaviour** and knows nothing about edges or entry
points. That is what lets the entire graph structure be tested with no API key.

What is left is genuinely one reason to change: what a canvas edge means. The
file's header carries the table — a `tool` or `skill` link is a *binding* and
produces no graph edge, `text` and `result` are control flow, `feedback` is
part of a conditional — and getting any row of that wrong is not subtle. A tool
link treated as control flow puts the tool in the execution order, so it runs
once on its own before the agent ever calls it and the agent then calls it too.
A feedback link treated as an ordinary edge builds an all-static cycle, which
can never terminate.

Forty-four top-level definitions at 890 code lines is twenty lines each, and
they are edge-kind handlers rather than layers. Nothing here groups into a
collaborator the way `node_runtime.py`'s families do, so the honest recorded
position is that this one is long because the substrate is, and the number is
here to catch it growing for a different reason.
"""

STREAMING = """
SSE framing and the stream fold — itself the product of a split
(reviews-2026-08-14 ticket 72), which is why its docstring is one line while
the file is 858 code lines. It already has four collaborators beside it that
used to be inside it: `burst_recorder.py`, `frame_clock.py`, `audience.py` and
`diagram.py`.

The bulk that remains is the fold: one long walk over LangGraph's event stream
turning astream events into our frames, plus the per-frame branching that
`Audience` requires — the same run is written twice, once for the developer
channel and once for the customer channel, and the difference is per event
type rather than a filter that could be applied at the end.

The one-line docstring is worth calling out as a defect in itself. Every other
entry in this table opens with an argued header explaining what its module owns;
this one says only what the split was, so a reader arriving at the longest
streaming file in the package gets a ticket number and no map. That is the
cheapest available improvement here and it is not a split: give it the header,
then the fold's shape becomes discussable.
"""

PREBUILT_MCP = """
`tool.mcp` — one card, a whole MCP server's tools, and the file is long because
it is the one atom in the repository that breaks two structural assumptions at
once. Every other atom is one node → one tool with a synchronous `func`; an MCP
server is one node → **N** tools and those tools are coroutine-only.

Both are answered structurally rather than worked around, and both answers live
here: `as_langchain_tools()` defaults to `[self.as_langchain_tool()]` on the
base so every existing atom is untouched and the singular case is the plural
case with one element, and each async tool is re-wrapped as a `StructuredTool`
carrying the original `coroutine` *and* a `func`, with both entry points
marshalling onto the one long-lived loop in `mcp_sessions`.

The session cache is the other half and it is the half that earned its length:
`MultiServerMCPClient` is stateless by default, so the adapters' tool body
re-opened the socket and re-ran `initialize` + `notifications/initialized` +
`tools/list` before every single `tools/call` — roughly half of every MCP call
was the handshake. Holding a live session instead is the fix and it brings
lifetime, eviction and failure handling with it. Thirty-five top-level
definitions at 750 code lines; the plausible seam is session management out to
its own module, which is a real extraction and is named here so it is the first
thing considered when this number next moves.
"""

MCP_SERVER = """
The MCP layer: OpenStateGraph's capabilities exposed to somebody else's LLM,
where the customer's model does the composing and we are the ground truth and
the artifact factory. Its length is almost entirely **tool docstrings**, and
that is not a technicality — over MCP a tool's docstring *is* its interface,
the only thing the client's model reads before deciding whether and how to call
it, so prose here is contract rather than commentary.

That makes this the entry where the measure is most obviously the right one and
still charges too much. The docstrings on module, class and function are free
under `code_lines`, but the argument tables and `Literal` unions the tool
schemas are built from are not, and this file is 654 code lines against 1,179
physical.

Structurally it already obeys the rule against god classes: four small
collaborators — vocabulary, artifacts, library, runs — each with one reason to
change, and `EXPOSED_TOOLS` as the enforced trust boundary that keeps publish
and delete off the wire. Splitting by collaborator is therefore the obvious
move and a poor one: the four are assembled into one server object at one call
site, so the reader's view would not change and the wiring would grow, which is
the argument `WorkflowFileClient` is already recorded under in the class census.
"""

ROUTES_WORKFLOWS = """
The workflow catalogue — list, read, save, publish, delete, and what is inside.
This module is itself the result of the split that this whole ceiling is meant
to make routine: nineteen of `api/main.py`'s thirty-two routes were these, which
is why "one module that grew" was never the right description of that file — it
was several modules that had not been separated (reviews-2026-08-14 ticket 15).

Its length is the endpoint surface, and the class census already records the
argument for exactly this shape in `WorkflowFileClient`: *"a flat HTTP adapter
where every member is its own fetch and there is nothing to delegate to. Width
here is the width of the endpoint surface, and the class does not get to be
narrower than the API it adapts."* This is the server end of that same surface
— `WorkflowFileClient`'s eighteen members are these routes seen from the
browser — so the two numbers move together and neither is free to shrink alone.

At 546 code lines it is the smallest entry in this table and the one closest to
the ceiling, which makes it the useful canary: if the catalogue grows a second
concern, this is where it shows up first and this number is what says so.
"""

RUN_SINKS = """
Where a finished run is written down, and who else gets told. **Tier 1 —
semver-public**: `IRunSink` is a contract a third party satisfies from their own
distribution, so it is as irreversible as anything this framework publishes, and
it was designed complete at birth for that reason. That single fact accounts for
most of the length: a Protocol that cannot be widened later is one that ships
with every field it will ever need, plus the argued docstring explaining why
each is there.

The finding it exists because of is that **capture was never the gap**. The
checkpointer already holds every question and answer of every run keyed by
`thread_id`; `api/threads.py` already reads that back as a listing, as one
thread's supersteps, with per-step tokens and tool calls, over CLI and HTTP, as
text and as JSON; `executed_statements` already publishes what a run executed.
What did not exist was the socket — a way for the installer to say where those
rows also go — and the proof it was missing is that we had answered the question
once for exactly one destination with no way to answer it again
(`loader._append_trace`, a hardcoded JSON-lines file behind `trace_file=`).

So the file is the Protocol, the dispatch, and the built-in sinks that prove the
socket takes more than one plug. The built-ins are the extractable part and the
number is here to make that visible when a fourth one lands.
"""

#: Eight modules, derived and then argued for one at a time. Nothing in this
#: table was chosen; the census below produces the keys and this table has to
#: match it exactly, which is the mechanism the class censuses arrived at after
#: hand-picked pins were found to cover only the classes somebody had already
#: worried about.
RECORDED: dict[str, Recorded] = {
    "compile/node_runtime.py": Recorded(2035, NODE_RUNTIME),
    "cli.py": Recorded(1099, CLI),
    "compile/workflow_compiler.py": Recorded(890, WORKFLOW_COMPILER),
    "api/streaming.py": Recorded(858, STREAMING),
    "prebuilt_mcp.py": Recorded(750, PREBUILT_MCP),
    "mcp_server.py": Recorded(654, MCP_SERVER),
    "api/routes/workflows.py": Recorded(546, ROUTES_WORKFLOWS),
    "run_sinks.py": Recorded(524, RUN_SINKS),
}


def test_the_census_matches_the_record() -> None:
    """A module cannot go over the ceiling unnoticed, and none is listed by hand."""
    census = modules_over_the_ceiling()

    unrecorded = sorted(set(census) - set(RECORDED))
    departed = sorted(set(RECORDED) - set(census))

    assert not unrecorded, (
        f"over the module ceiling and not recorded: "
        f"{ {name: census[name] for name in unrecorded} }.\n"
        f"A module over {CEILING} code lines is not automatically a defect, and "
        "this is not a request to delete anything. It is a request to say which "
        "of two things it is.\n"
        "  - It has more than one reason to change: extract the second one into "
        "its own module beside it, the way `compile/state.py` and "
        "`api/burst_recorder.py` came out of the files above.\n"
        "  - It is one thing that is genuinely this long: add it to RECORDED "
        "with the argument that makes the number a decision, naming the seam you "
        "considered and why it does not pay.\n"
        "Raising CEILING is neither of those, and it is the move this file "
        "exists to make somebody argue for in public."
    )
    assert not departed, (
        f"recorded but no longer over the ceiling: {departed}. Good news — "
        "delete the entry, and its reasoning with it."
    )


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_each_recorded_length_is_exact(name: str) -> None:
    """The ratchet. Exact in both directions, which is why it is not a target."""
    census = modules_over_the_ceiling()

    assert census[name] == RECORDED[name].lines, (
        f"{name} is {census[name]} code lines, recorded as "
        f"{RECORDED[name].lines}.\n"
        "Exact, not an upper bound: an exception with room to spare is how a "
        "ceiling becomes a floor, and the growth this pin was written for "
        "(node_runtime.py, +1500 lines in the week after its own split) is "
        "precisely what an upper bound would have let through.\n"
        "If the file grew, the question is whether what you added is the module's "
        "one reason to change. If it shrank, re-record the smaller number and "
        "say what came out."
    )


@pytest.mark.parametrize("reason", sorted({entry.reason for entry in RECORDED.values()}))
def test_every_exception_carries_reasoning(reason: str) -> None:
    # Length is a crude proxy for "somebody actually thought about this", and a
    # crude proxy beats none. Same threshold as both class censuses.
    assert len(reason.strip()) > 400


class TestTheMeasureMeasuresWhatItClaims:
    """A measure nobody checks is as much a preference as a ceiling nobody measures."""

    def test_prose_is_free(self) -> None:
        documented = '"""One.\n\nTwo.\n\nThree.\n"""\n\n# a comment\n\nx = 1\n'
        assert code_lines(documented) == 1

    def test_a_docstring_on_a_function_is_free_too(self) -> None:
        source = 'def f():\n    """Why.\n\n    At length.\n    """\n    return 1\n'
        assert code_lines(source) == 2

    def test_a_string_that_is_not_a_docstring_is_charged_for(self) -> None:
        # The deliberate asymmetry: a prompt is content somebody has to read.
        source = 'PROMPT = """One.\nTwo.\nThree."""\n'
        assert code_lines(source) == 3

    def test_a_line_of_code_costs_one(self) -> None:
        before = (PACKAGE_ROOT / "run_sinks.py").read_text(encoding="utf-8")
        assert code_lines(before + "\nSENTINEL = 1\n") == code_lines(before) + 1
