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
  698 code lines). It counts the thing that is cheap to add and misses the
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
  `WorkflowModel`'s pin in `src/publicSurfaceCeiling.test.ts` doing its job — the number is a tripwire, not a
  goal.

A bare ceiling would be red on day one for ten files, which is how a pin
acquires a `# noqa` and dies. A bare ratchet with no ceiling would put a number
on every module in this repository, which is a config file nobody reads. The
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
The file this ticket found, and the entry whose split is now being executed
against this number rather than beside it. `docs-and-gaps/03` had a recommended
order — `mount_overrides.py`, then `reporting.py`, then the `compile/nodes/`
rewrite last — and every step of it has re-recorded here on the way past:
2,039 code lines, then 1,944, 1,829, 1,750, 1,434, 1,343, 1,194, 1,040, 825 and
now 569, with every node family this build implements living in its own module
under `compile/nodes/`.

**570** (`the-cost-of-one-more` 02). One line: `self._mount_memo`, the dict that
makes a mounted package compile once per instance rather than once per mount
*site* — the difference between eight builds and 255 for eight packages on
disk. It is on the runtime and not in `compile/nodes/mount.py` where the rest of
the mount family lives, and that placement is the reason the key
`(slug, overrides, persistence)` is sufficient: a runtime fixes everything else
a child compile reads — the services it inherits, the ancestry that refuses a
cycle, the settings a context gap is measured against — so two sibling mounts
under one runtime share all of it and two mounts under different runtimes share
none. A memo hung anywhere with a longer life would need the invalidation list
`docs/decisions/per-request-compile-cost.md` declined a cache over. The ratchet
is exact in both directions, so a single line has to be claimed out loud; this
is the claim.

What the number was for is the growth, and it is worth restating now that it is
being used the other way. The split of 2026-08-22 moved 401 lines out; the week
that followed put more than fifteen hundred back, with a second extraction
landing in between, and no one knew until somebody ran `wc -l` against a ticket
charted at 1,639. The ratchet is exact in both directions precisely so that a
shrink has to be claimed out loud, in the same diff as the code that earned it,
instead of being noticed a week later or not at all.

The module still passes every rule `CLAUDE.md` states in words, which is the
asymmetry this entry exists to make visible: it has a one-sentence description;
it has one reason to change (it is the node builders); `NodeRuntime` the class
is at 8 public members and under the class ceiling by name. A file could pass
all of that at 5,331 physical lines, and did.

**What is left here is not a queue of unmoved families.** It is the registry
itself and the resolution every family shares — model resolution, reasoning
effort, the middleware slot table, prompt composition, tool binding, capability
reporting and the `_report_*` diagnostics — plus the families still to move. A
number driven below the shared part by pushing that resolution down into the
families would buy this table a better figure and cost the codebase the
anti-duplication rule, so the honest floor is well above the 500 ceiling and
this entry is expected to keep its argument after the last family leaves.
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

**1099 -> 1102** (`the-boundary-nobody-checked/02`). `threads show` names the
audience it reads a stored run with — through `resolve()`, so a capped
deployment caps the terminal too. Three lines, and no new logic: the door it
already wrapped grew a parameter, and a caller that declines to answer would
have been the silence this ticket is about.

**1102 -> 1123** (`the-cost-of-one-more/08`). Twenty-one lines, and the rule
holds: no new logic. `runs export` now catches the one thing `read_runs` can
refuse — a cadence read this build could not perform — and turns it into a
non-zero exit and a sentence, instead of writing a file with `bursts: []` on
every row and exiting 0. The rest is `_write_runs`, which emits the same array
a record at a time rather than holding a second copy of an unbounded store in
memory before a byte of it reaches the disk. Both are the export command
saying what it did, which is the only thing this module is allowed to do.
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

**964 since `the-cost-of-one-more` 01**, and the +74 is one algorithm rather
than seventy-four lines of drift. `step_budget_floor_for`'s two walks carried
a per-path `seen` set, which enumerates simple paths — 55 seconds for one
grader on a drawable 69-node document, a compile-time hang reachable from any
document a caller can POST. They condense the graph now (`_walk_successors`,
`_nodes_that_reach`, `_components`, `_longest_component_path`), which is
Tarjan plus a dynamic programme over the condensation: four small named
functions where there were two recursive ones, and the growth is Tarjan's
iterative form, written out for the reason `always_taken_cycles` beside it is.
It stays here rather than moving to a `graph_walks.py` because both of this
file's walks are about **what a canvas edge means for the step budget**, which
is the file's one reason to change; a shared walk module would be a home for
two callers and would separate the walk from the edge table it reads.
"""

STREAMING = """
SSE framing and the stream fold — itself the product of a split
(reviews-2026-08-14 ticket 72), which is why its docstring is one line while
the file is 1030 code lines. It already has four collaborators beside it that
used to be inside it: `burst_recorder.py`, `frame_clock.py`, `audience.py` and
`diagram.py`.

**959 → 1026 (`memory-and-replay` 53/55/56), and the growth was spent on the
vocabulary rather than on the fold.** Two frame kinds joined it — `started`,
which opens every stream, and `invoked`, which says an ordinary tool was asked
for — and `usage` joined the three terminal frames. Roughly half of the
addition is the declaration and its argument in `_PAYLOAD_FIELDS`, which is
where a frame's contract is supposed to be written down; the executable half is
`ToolWatcher` (35 lines) and three emitters of a dozen lines each.

Nine of those lines are the opening frame being handed over on the *far side*
of the first pull rather than before it, in three places — the loop, the error
handler and the no-terminal-frame fallback. It reads like ceremony and is not:
everything before an async generator's first `yield` runs in the task that made
the first pull, so suspending earlier moved the turn's token meter into a
different task from `graph.astream` and stopped the run's cost being counted at
all. Caught live, and pinned twice in
`test_a_run_says_when_it_starts.py`.

**1026 -> 1042 (`memory-and-replay` 65), and sixteen lines is what it cost
to stop the stream calling an agent a mounted workflow.** Two of them are
executable — one `is_mount` term in the namespace guard, and `_mount_ids`
asking the compiler what it recorded — and the rest is the argument for why
`None` and `set()` are different answers, written at the field that holds
them. That argument is the fix: the older guard could rule out a namespace
head naming *no* canvas node and had no way to rule out one naming a node that
is not a mount, which is every agent in the product, because `create_agent`
returns a compiled LangGraph and its loop is namespaced under the node that
owns it.

**1042 -> 1030 (`launch-readiness` 196), and every one of the twelve lines
left because something else needed it too.** Three things moved out to core,
where a second reader could reach them: the chunk decode (`stream_parts.py`),
the two message predicates that tell a settled record from a streamed token
(`messages.py`, beside `content_text` which they are always used with), and
`_abandon` (`run_stream.py`, which is where the argument for cancelling
*without* awaiting is now written once). Nothing was deleted and no behaviour
moved — each is aliased back at the name this file's own docstrings and call
sites use. The framework-free run surface needed the same three answers, and a
second copy of *the record is not a token* is a defect this repository has
already paid for once (`every-workflow-green/02`).

**`ToolWatcher` is where a split was available and was taken.** It reads the
same `messages` list `SpawnWatcher` does, and four more lines inside that class
would have been the cheaper edit; they are separate reasons to change — one
owns the four shapes a run makes a child in and closes each of them, the other
owns "a tool was asked for" and closes nothing — so it is a second class rather
than a second responsibility. The audience-gated half went to `audience.py`
(`run_usage`) for the same reason: that module is the seam that owns what a
customer may not see.

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
definitions at 758 code lines; the plausible seam is session management out to
its own module, which is a real extraction and is named here so it is the first
thing considered when this number next moves.

750 → 758 is `McpAuth.credential_source()` and the comment at the one call
site that passes it (`the-boundary-nobody-checked/05`). It belongs here rather
than in `mcp_sessions`: the pool is handed a library `Connection` dict, which
has no room for a fact about a *document*, and only this module knows that a
row names an environment variable rather than carrying a value. That is this
module's one reason to change — "how a document declares an MCP server" — so
the growth is on the right side of the question above.
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
schemas are built from are not, and this file is 698 code lines against 1,293
physical.

Structurally it already obeys the rule against god classes: four small
collaborators — vocabulary, artifacts, library, runs — each with one reason to
change, and `EXPOSED_TOOLS` as the enforced trust boundary that keeps publish
and delete off the wire. Splitting by collaborator is therefore the obvious
move and a poor one: the four are assembled into one server object at one call
site, so the reader's view would not change and the wiring would grow, which is
the argument `WorkflowFileClient` is already recorded under in the class census.

654 -> 698 (`the-boundary-nobody-checked/08`). `run_workflow` was the fourth run
door and the only one that took no audience: it published the capability fence
in `answer` and in every value of `outputs`, and `warnings` — authoring
diagnostics naming node ids and unbound tool types — unconditionally, on the
door this module itself calls "the one a customer's own model calls". Making it
answer to one brought over the seam `/api/runs` already applies in the same
order (`split_suggestion`, `clean_output`, `DeveloperChannel.payload`,
`with_capability_notice`, `redact_failure_markers`), which is where the 44 lines
went. Nothing was reimplemented — every one of those is an import from
`api/audience.py` — but the *comments* explaining why each applies here are new,
and they are the part that stops the next reader restoring the raw payload. The
alternative, a private helper hiding the sequence, would put a fifth spelling of
the boundary in the module the ticket found by reading it.
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

At 559 code lines it is the smallest entry in this table and the one closest to
the ceiling, which makes it the useful canary: if the catalogue grows a second
concern, this is where it shows up first and this number is what says so.

**546 → 551** (`the-boundary-nobody-checked/03`): `build_knowledge` took the
request object and passes `auth.shared_deployment_reason(http)` down to
`resolve_build_model`, so a browser-supplied provider key cannot configure a
shared server through the knowledge door either. Five lines, and the canary is
not firing: this is the *same* concern the three run doors took in the same
commit — every door that accepts a `credentials` body asks the one question —
not a second one arriving in the catalogue. The seam considered and rejected
was a FastAPI dependency (`RefusedBecause = Annotated[str | None, Depends(...)]`)
that would have removed the argument from all four call sites at once; it costs
one line per door and hides *which* doors take a credential behind a type
alias, which is the thing a reader of this ticket most needs to be able to
grep for.

**551 → 559** (`rules-that-can-fail/02`): `get_capabilities` now also reports a
plugin whose `node_type` the open package's own `tools/` takes over — the third
of the tool registry's three claimant pairs, and the only one that was silent.
Eight lines, and the canary is still not firing: `warnings` is a field this
endpoint already assembles from three sources, and this is a fourth entry in
that same list rather than a new concern arriving in the catalogue. The
sentence itself lives in `plugin_capabilities.shadowed_plugin_warnings`, which
is also what `build_tool_registry` calls, so the route holds the call and not
the knowledge. What was rejected here was moving the whole `warnings` assembly
into `plugin_capabilities`: two of its four sources are workflow-local
discovery, which that module deliberately knows nothing about, and pulling
them across would have cost the module its one-sentence description.
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

**524 -> 528** (`the-boundary-nobody-checked/02`). `read_run_bursts` gained the
required `audience` keyword and the two-line clause that honours it, plus the
paragraph saying why the keyword has no default: `RunBurst.audience` was
written *"so a reader can refuse"* and the reader had nothing to refuse with.
Four lines on the reading half of what this module already stores — its one
reason to change — not a new concern.

**528 -> 529** (`the-boundary-nobody-checked/06`). One import line. Its two
read-only opens spelled `sqlite3.connect(f"file:{target}?mode=ro", uri=True)`
by hand, which is the URI form that also lets `ATTACH` and `VACUUM INTO` open
a second file for writing; they now call the one seam,
`readonly_sqlite.readonly_connection`, which denies that at the driver. The
SQL here is module-pinned and no model string reaches it, so this module was
never the way in — it is routed through the seam anyway because the
alternative is an exemption list, and an exemption list is how the seventh
call site inherits the hole in silence.

**529 -> 578** (`the-boundary-nobody-checked/07`). Forty-nine lines, and the
argued docstrings are most of them: `_reconcile` and `_table_columns` are
sixteen lines of code under a docstring that says why reflection beat a
`PRAGMA user_version` ledger and — the part a reader needs — enumerates the
four shapes of schema change it deliberately does not survive. The rest is
`_could_not_write`, which splits the first lost row from the tenth, and a
`names` parameter threaded through the two readers so a store this build is
newer than lists what it holds instead of nothing.

This is the module's one reason to change, arriving late rather than a second
one: a store's schema and how it is read back is what this file *is*, and the
comment being replaced (`_BURST_COLUMNS`, *"this module has no migration
machinery"*) shows the concern was already here, stated as a constraint with
nobody owning it. Nothing extractable was added — `_reconcile` has one caller
and would be a module of two functions and a paragraph.

**578 -> 600** (`the-cost-of-one-more/08`). Twenty-two lines, and they are the
reading half again: two `CREATE INDEX IF NOT EXISTS` statements with the
paragraph naming which listing each answers and why `--thread` deliberately
gets none, `CADENCE_BATCH` and the loop that honours it, and
`RunCadenceUnavailable` — the class that separates *this store has no cadence*
from *this read could not get it*, which had been one `except` and one
`logger.debug` and so lost every burst of a 33,000-run export in silence. An
exception class is not a second concern here: it is how this module says what
it could not answer, which is what `_could_not_write` already does for the
writing half.

**600 -> 618** (`the-cost-of-one-more/11`). Eighteen lines, and seventeen of
them are the argument. `now()` writes local wall clock with a numeric offset
and every reader ordered that column as **text**, which compares the offset as
text — so two rows either side of a DST fall-back came back in the order of
their local clocks. `CHRONOLOGICAL` is the column read as the instant it
names, the four indexes are rebuilt on it, and the `ORDER BY` names it. The
code is a constant and four statements that were four statements before; what
the file actually gained is the paragraph saying why the ordering is
**derived** rather than stored — a new UTC column would be the first backfill
over a store that never sweeps, and re-spelling `now()` would sort the same
instant a day apart in two spellings. That reasoning is the module's, because
the store's growth is what makes it expensive to get wrong, and this file is
where a reader will look for it.

**618 -> 640** (`the-cost-of-one-more/12`). Twenty-two lines that make the
module *smaller in statements and larger in structure*. `_open` used to be one
long sequence — create the tables, create the indexes, then reconcile the
columns — and the order was wrong: `CREATE TABLE IF NOT EXISTS` is a no-op
against an older table, so an index naming a column the file lacked failed the
whole open, latched `_broken`, and dropped every run the process went on to
record. The statements are now three loops over `_tables()` and `_INDEXES`,
which is what makes the order hold: an index is added by naming it in a tuple,
where it cannot be placed before the columns it names exist. The rest is the
split `_broken` needed — `_holds_the_runs_table` asks the file which kind of
failure this is rather than reading sqlite's message, and two named handlers
say what each costs, because *"a column is missing"* at `warning` and *"no run
will be recorded for the rest of this process"* are different facts and had one
line between them.
"""

#: Eight modules, derived and then argued for one at a time. Nothing in this
#: table was chosen; the census below produces the keys and this table has to
#: match it exactly, which is the mechanism the class censuses arrived at after
#: hand-picked pins were found to cover only the classes somebody had already
#: worried about.
RECORDED: dict[str, Recorded] = {
    "compile/node_runtime.py": Recorded(570, NODE_RUNTIME),
    "cli.py": Recorded(1125, CLI),
    "compile/workflow_compiler.py": Recorded(964, WORKFLOW_COMPILER),
    "api/streaming.py": Recorded(1030, STREAMING),
    "prebuilt_mcp.py": Recorded(758, PREBUILT_MCP),
    "mcp_server.py": Recorded(698, MCP_SERVER),
    "api/routes/workflows.py": Recorded(559, ROUTES_WORKFLOWS),
    "run_sinks.py": Recorded(640, RUN_SINKS),
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
