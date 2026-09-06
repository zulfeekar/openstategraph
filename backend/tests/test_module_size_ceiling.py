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
- **Top-level definitions.** Ranks `api/schemas.py` (67 classes, entirely
  declarative Pydantic) above `mcp_server.py` (7 definitions, 698 code lines).
  It counts the thing that is cheap to add and misses the thing that grows.
  (The two code-line figures that stood in this sentence were the ones
  measured the day it was written and had both moved by `stable-beta-public/03`
  — a number in prose with no way to fail, inside the file that argues for
  pinning numbers. The ranking is the point and it survives without them; the
  live figures are in `RECORDED` below, which the census has to match.)
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

**574** (`every-workflow-green` 45). Four lines: one import, `self.checked_nodes`,
and the two that populate it from the plan on the first node built. It is the
same kind of fact as `machinery_nodes` and sits beside it — which streamed text
a grader has still to judge — and the *computation* is not here: reachability
lives in `compile/checked_nodes.py`, a module of its own, because it is a
question about a plan rather than about building a node.

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
**574 -> 578** (`osg-agent-experience/48`). Four lines: one attribute beside
`_holds_a_gate`, its assignment in `_resolve_model`, and a two-line module
function to read it. It is the same *kind* of fact the two beside it already
are — something only the build knows, asked for one level up — and it stays
private for the reason `_holds_a_gate` records: a tenth public member on this
class is a class that has to argue for itself.

**578 -> 581** (`osg-agent-experience/42`). Three lines and they are the shape
this file wants: `route_check` joins the family import, one binding in the
class body, one `registry.register` call. The whole implementation of the new
node type is 69 code lines in `compile/nodes/route_check.py`, none of it
here — which is what `docs-and-gaps/03`'s split was for, and the measurable
difference from the twenty families this module used to hold inline.

**581 -> 583** (`osg-agent-experience/55`). Two lines, the same shape again:
one binding in the class body and one `registry.register` call for
`output.static`. Its implementation is in `compile/nodes/io.py`, beside the
exit it is a sibling of — adjacency there is load-bearing, because the whole
decision is that the two exits differ and a reader has to be able to see how.

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

**1601 -> 1604** (`osg-agent-experience/47`). Three lines, and the rule this
row keeps holds: an import, one entry appended to `startup_facts()`'s list, and
one `print` in `init`'s closing block. The logic is `dotenv.environment_line`,
beside the walk and the parser it reads — this module still only says what the
command did.

**1125 -> 1127** (`launch-readiness/195`). Two lines in `console_main`: an
import and a call. The rule holds for the same reason `.env` loading did — the
logic is `config_file.apply_prepend_sys_path`, beside the `workflows_dir`
resolution that follows the same relative-to-the-file rule, and what lives
here is only the statement that a **process** the user launched may
reconfigure their interpreter from a committed file while a **function** this
suite calls in-process may not. That boundary is this module's, and there is
nowhere else to draw it.

**1127 -> 1129** (`memory-and-replay/71`). Two lines, and they are the export
command answering a question the reader now asks it: `read_runs(with_bursts=…)`
takes an `audience`, and `runs export` says `developer` because it is an
operator reading their own machine's store from that machine's own terminal.
Whose store this is has always been this command's to know; nothing else here
could answer it.

**1129 -> 1137** (`launch-readiness/191`). Eight lines, and no new logic: the
reading is `config_file.gitignore_gaps` and the branch is
`InitResult.gitignore_gaps`, both computed before `cmd_init` is reached. What
grew here is the copy — the case where `init` declined to write an existing
`.gitignore` used to print one line claiming the file "already covers it",
which is exactly the branch where it may not, and printing the missing rules
as lines to paste costs more lines than a claim does. That is the module's own
job: this command says what it did.

**1137 -> 1144** (`install-experience/25`). Seven lines, six of which are a
table and a comment. The brief a coding agent reads now lands in the project
`init` makes, and the table is `_AGENTS_MD_STATE`: four states, because "we
wrote the file", "we added our block to yours", "we replaced a stale block"
and "it was already right" are four different things to have done to a file
the user may own, and this command's one job is to say which. The knowledge —
what the brief says, where it goes, what the markers mean — is
`agent_brief.py`; nothing about it is duplicated here.

**1158 -> 1238** (`install-experience/26`). Eighty lines, and this is
the one entry where the rule was in genuine danger, so the split is worth
stating. `open` is the developer's one verb — point it at a folder and the
editor opens on it — and *everything it decides* is
`openstategraph.opening.plan`: which directory, why that one, what is already
in it, whether to refuse and what to offer instead. None of that is here.

What is here is the three things a decision cannot do for itself and the
declaration of the flags that reach it: `chdir` into the directory (the whole
of what the argument does, so no second precedence chain exists), the `input()`
call, one `mkdir`, and then `cmd_serve(args)` — the same server, not a second
one. Two of the eighty are `startup_facts` gaining the *reason* the
workflows root resolved where it did — the one printer for that directory, so
`open` does not print it a second time. Roughly half the rest is the parser block, which is the pure
declaration this entry's second paragraph already prices at twenty lines a
command.

`expand_bare_path` is the other named piece and it is nine lines: it turns
`openstategraph .` into `openstategraph open .`, resolving the first token
against this parser's own subcommand set before it will read it as a path.
That has to be here — it is a fact about the parser — and it is the only
place this CLI reads an argument tolerantly, which is why it is written to be
strict about what it then trusts.

**1238 -> 1243** (`providers-and-credentials/18`). Five lines, and four of
them are one branch: `openstategraph providers` had three row states and now
has four, because a provider whose credential is present and whose client
still cannot be built is not "needs a key" — saying so sends a reader to
rotate a credential that works. The fourth line prints which variable is
unset, named rather than counted, since a row saying *needs a setting* and not
which one is the shape of the 500 that ticket came from. The fifth widens two
column padding literals so a fourth provider does not shunt the model column
out of line. No knowledge moved here: `ProviderGap` composes the sentence and
this reads it.

**1243 -> 1306** (`kanban-patrol/19`). A new `kanban` subcommand — `attend`,
`stage`, `show` — 63 lines across three thin handlers, a subparser block, and
nothing else. No new logic: every handler wraps `kanban_store.set_stage` /
`read_card`, built as its own module precisely so the claim and stage-order
rules exist exactly once and this file stays three declarations calling one
seam, same shape as every other command here.

**1306 -> 1312** (`kanban-patrol/24`). Six lines printing which skills
`install_bundled_skills` wrote and where — the same "report every artifact by
name" the `AGENTS.md` line above it already does. No new logic: the
installer lives in its own module (`bundled_skills.py`), this only formats
what it returned.

**1312 -> 1315** (`kanban-patrol/25`). Three lines in `kanban show`, printing
`priority` and, when the classifier gave one, `priority_reason` — the same
field `read_card` already carries.

**1315 -> 1345** (`kanban-patrol/07`). A new `patrol` subcommand — one verb,
`run` — 30 lines: a subparser block and one thin handler wrapping
`patrol.run_patrol`. No new logic here either: the read-classify-file loop
and the deterministic classifier both live in `patrol.py`; this only reads
`project_id` off the active config and prints what the loop returned.

**1345 -> 1362** (`kanban-patrol/17`+`21`). `kanban stage` grows three flags —
`--test-id`, `--reason`, `--commit` — and `cmd_kanban_stage` catches
`MissingEvidenceError` beside `StageOrderError` it already caught. No new
logic: `kanban_store.set_stage` owns the evidence gate entirely; this only
threads the three new strings through and reports the same clean non-zero
exit a skipped stage already gets.

**1362 -> 1381** (`kanban-patrol/19`, the explicit Release). A fourth
`kanban` verb, `release` — a subparser block with one new flag
(`--threshold-seconds`, defaulting to the hour this ticket's own locked
decision named) and one nine-line handler. No new logic: `kanban_store
.release_card` owns the "already flagged, then atomic reset" rule entirely;
this only reads the exit code out of `SetStageResult` and prints the same
clean non-zero refusal every other `kanban` verb already does.

**1415 -> 1448** (`kanban-patrol/15`, 2026-09-04). A fifth `kanban` verb,
`answer` — thirty-three lines: a subparser block, one handler catching the
two refusals `kanban_store.answer_card` raises, and three lines in
`kanban show` printing the decision once a card has one. No new logic: the
store owns "written once", "back to Detected and never to Resolved", and
every refusal; this reports them the same clean non-zero way every other
`kanban` verb already does.

**1381 -> 1415** (`kanban-patrol/23`). Thirty-four lines across two doors, and
the rule holds: the logic is `project_identity.adopt_project_id` and
`adopt_for_active_config`, which is where a file this code does not own gets
one appended line. What grew here is a command saying what happened —
`patrol run` printing the identity it just minted instead of refusing, and
`adopted_project_id_note`, a function rather than a block inside `cmd_serve`
for that command's own recorded reason: formatting inside a command is
formatting no test reaches without binding a socket.

**1448 -> 1465** (`kanban-patrol/08`, 2026-09-04). Seventeen lines, and the
rule holds: `run` grows a `--session-id` flag it passes straight through to
`ask()`, and `kanban attend` prints the marker for the card it just claimed.
No new logic here at all — `patrol.card_session_id` owns the spelling and
`patrol.is_patrols_own_work` owns the rule; this module is two doors handing
a value along and one command saying what the actor must now do. A separate
module for one f-string was not considered.


**1465 -> 1467** (`osg-agent-experience/25`, 2026-09-04). Two lines, and they
are a subtraction that reads as an addition: `init`'s skills line summarised
one state per skill, and the installer now reports one state per *file*, so
the set it collapses is built from the report rather than re-derived from
`BUNDLED_SKILLS`. The names still come from the map, because the map is what
the wheel ships; what changed is that a stale reference page beside a current
sheet now shows as `mixed` instead of being invisible.

**1467 -> 1481** (`osg-agent-experience/25`, 2026-09-04). Fourteen lines: a
five-row state table and the loop that prints it. `init` now writes the four
files four coding agents read to find this project's MCP server, and the rule
holds — the knowledge (which file, which key, how a merge preserves somebody
else's servers, what makes a file one we decline to write) is all
`agent_config.py`; what is here is one sentence per state and the loop that
picks one, exactly like `_AGENTS_MD_STATE` above it. The note line is the
reason the loop is not a one-liner: a file we left alone has to say why, and a
state word cannot.

**1547 -> 1571** (`osg-agent-experience/25`, slice 4, 2026-09-04).
`cmd_kanban_triage` plus its parser: one call to `kanban_store.triage` after
filtering `list_cards` by board, and a two-line-per-row print loop — no new
ordering logic, `kanban_store.triage` owns the rule and the sentence, the
same split `cmd_kanban_file` already keeps from `file_idea_card`.

**1571 -> 1573** (`osg-agent-experience/32`, 2026-09-05). Two lines in
`cmd_validate`: an import and one list comprehension. The rule holds — every
check, every sentence and the finding classes are `document_checks.py`, and
what is here is the command folding one more list into the `problems` it
already builds from four.

**1573 -> 1601** (`osg-agent-experience/33`, 2026-09-05). Twenty-eight lines:
`cmd_nodes` and its parser, the vocabulary verb the CLI door did not have —
an MCP client calls `get_node_vocabulary` before composing anything and a
client at a terminal was sent to read the installed `port_specs.json` by eye.
The rule holds and was the reason for the size: the payload is
`NodeVocabulary.describe()` and every line of formatting is `node_report.py`,
so what is here is an argparse declaration, two calls and the one decision
that is genuinely the command's — that an id nothing resolves is a *usage*
error rather than a failure, because nothing ran.
**1604 -> 1608** (`osg-agent-experience/48`). Four lines: an import and a
three-line refusal before the run. The predicate was answered where the model
is (`load_workflow`) and recorded on the workflow, so what is here is the
command saying what it did — which is the only thing this module is allowed
to do.

**1608 -> 1612** (`osg-agent-experience/30`). Four lines: `kanban file` now
prints the blockers no card carries, one line each. The judgement — what
resolves, what is refused, what is only reported — is `kanban_store
.resolve_blocked_by` and `unresolved_blockers`, so this is the command saying
what it did, again the only thing this module does.

**1612 -> 1635** (`osg-agent-experience/28`). Twenty-three lines: `export
toolkit`, the leaf beside `export plugin`, and its four `add_argument`/help
lines. No new logic — it is `plugin_interop.export_toolkit` plus the same two
argument refusals `cmd_export_plugin` already makes, and the bundle's server
entry is rendered from `agent_config.ServerDescriptor` in that seam, not here.


**1635 -> 1648** (`osg-agent-experience/24`, 2026-09-05). Thirteen lines, and
the rule this whole entry keeps holds: no logic. `init` writes four MCP config
files, two skill roots and `AGENTS.md`, all of which a coding agent reads only
at start-up, and it wrote them without saying so — and without saying when the
command those entries name is not installed. Both sentences live where their
facts do (`scaffold.RESTART_SENTENCE` with `agent_surface_changed`,
`agent_config.missing_server_note`); what grew here is the six-line import
block those two names cost, two conditional prints and the comment saying why
they are conditional. This command says what it did, and until now it did not
say the last two things it did.

**1648 -> 1679** (`osg-agent-experience/65`, 2026-09-05). Thirty-one lines:
`cmd_kanban_where`, `_board_state_lines` and the parser rows for a new
subcommand. No new rule — the address and its reason are
`state_dir.resolve_state_dir` via `kanban_store.kanban_store_location`, so
this file resolves nothing and states nothing about where a board lives. What
it does is *print* it, which is the whole ticket: a board written by a source
checkout and read from an installed wheel is two different files, and the only
sentence either door had ever printed about it was `nothing to triage`.
`_board_state_lines` is a function rather than a block inside each command
because two doors now say the same two sentences, and two spellings of "no
board here yet" is the defect one directory away from the one being fixed.

**1679 -> 1684** (`osg-agent-experience/59`, 2026-09-05). Five lines, and all
five are `cmd_validate` calling one more thing and printing what it answered:
`uncallable_functions`, the third question an in-memory plan cannot ask, beside
the two already here. The rule it applies lives in `function_contracts.py` and
the resolution in `validation.py` — this file gained a call and a comment
saying what it costs, which is the shape both of its neighbours already have.

**1684 -> 1683** (`docs-onramp/08`, 2026-09-05). One line out, and it is a
deletion of nothing: eleven `help=` strings carrying internal ticket ids —
`kanban-patrol/19`, `osg-agent-experience/65` and nine more — printed those ids
at a user who cannot resolve them, since a ticket is a file under `.scratch/`
and ships in no wheel. The references moved into comments beside the strings,
which is why the code count fell rather than rose: two of them were
continuation lines that the shorter help text no longer needs.

**1683 -> 1694** (`docs-onramp/10`, 2026-09-05). Eleven lines, and all eleven
are `init` printing one more sentence: which command it wrote into the four
agent config files. `init` writes a bare `openstategraph` that a venv install's
agent cannot resolve, so the server never started and nothing said so; the
resolution lives in `agent_config.resolve_server_command` and the wording in
`agent_config.command_note` — this file gained the call, the wrap and a comment
saying why that one line may not be broken on hyphens.

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

**964 -> 965** (`every-workflow-green` 51). One line: `DOOR_SHAPE_RULE`, the
sentence the build door's shape route claims, published here because this is
where the predicate that decides it lives. `src/view/ask/doorHeadline.ts` had
been the only statement of the rule, in a different language, with nothing
between the two — which is why a card offering to build a capability that had
just been used could not be diagnosed from either side.

**965 -> 957** (`osg-agent-experience/32`, 2026-09-05). Eight lines out.
`data_key_findings` no longer builds the "no field on this node type declares
this key" advisory: `document_checks.unknown_fields` says it on the verdict's
own list, and printing both put "so the document stays valid" directly above
`valid: false` on the editor's validate door. The required-key half is
unchanged and stays here, where the plan is.

**957 -> 958** (`osg-agent-experience/42`). One line: `ROUTE_CHECK_TYPE` joins
the type constants and the router's own edge clause takes it as a second
member of a tuple, because a fork decided by a package function is the same
edge as a fork decided by a model — the same one destination per branch. The
node's behaviour is 69 code lines away in `compile/nodes/route_check.py`, and
that this file grew by exactly one line for a whole new node type is the split
between topology and behaviour doing its job rather than a coincidence.

**958 -> 1018** (`osg-agent-experience/80`, 2026-09-06). Sixty lines, and
they are all one question this file was answering wrongly: *where does a
verdict go when nobody drew its branch?* It went to whichever branch happened
to be declared first, and the steps hanging off the undrawn branches were
wired from `START` because nothing pointed at them — so a live run took one
verdict and published five answers. The additions are `unrouted_route` on the
plan and the two small readers that fill it (`_declared_fallback`,
`_needs_feeding`), the `STOP_LABEL` edge to `END`, and `_unrouted_sentence`
splitting one report into the two things that can now happen. It is the edge
table again, which is this module's one reason to change: the node families
that write the record are 80 code lines away in `compile/nodes/`. The last six
of the sixty are the advisory naming a node the new entry preference declined
to start: not scheduling it is the fix, and doing that in silence would have
been the same defect one layer down.
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

**1042 -> 1046 (`every-workflow-green` 45).** Four lines: the `checked` set
handed to `AnswerChannel`, the `draft` key computed once per chunk beside
`withheld`, its optional emission in `_token_frame`, and its name in the frame
pin. The judgement itself is `AnswerChannel.is_draft` and stays in
`api/audience.py`, where every other question about who may see what already
lives.

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

**1034 -> 1038** (`every-workflow-green` 51). Four lines, and they buy the
fold back its channel's own reducer: `tool_use` declares `MERGE_ROWS` and this
door folded it with `dict.update`, which is `MERGE`, so a node re-entered by a
grader's revise loop had its second lap erase the first lap's record of a tool
that ran. One import and a `merge_rows` call — the same function the channel
declares, never a second spelling of it. This door folds frames by hand
because it has no finished state to read, which is exactly why every channel
it folds is a second implementation of a reducer and has to be the same one.

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

**698 -> 736** (`kanban-patrol/16`). Three tools — `kanban_attend_card`,
`kanban_set_stage`, `kanban_show_card` — 38 lines, each a thin wrapper over
`kanban_store.set_stage`/`read_card`. No new logic: `StageOrderError` and a
lost claim are both turned into `{"ok": false, "reason": ...}` here, the same
translation the CLI door (`kanban-patrol/19`) already makes at its own
boundary, not a second claim implementation.

**736 -> 738** (`kanban-patrol/25`). Two fields in `kanban_show_card`'s
response — `priority`, `priority_reason` — the same two `read_card` already
returns to the CLI door.

**738 -> 748** (`kanban-patrol/17`+`21`). `kanban_set_stage` grows three
string parameters — `test_id`, `reason`, `commit` — and catches
`MissingEvidenceError` beside `StageOrderError` it already caught, ten lines.
No new logic: `kanban_store.set_stage` owns the evidence gate itself; this
only threads the three strings through and turns the new exception into the
same `{"ok": false, "reason": ...}` shape a lost claim already gets.

**748 -> 755** (`kanban-patrol/19`, the explicit Release). A fourth tool,
`kanban_release_card` — seven lines, one `threshold_seconds` parameter
defaulting to the hour this ticket locked, one call to `kanban_store
.release_card`. No new logic: the "already flagged, then atomic reset" rule
lives there entirely; this turns its `SetStageResult` into the same
`{"ok": ..., "reason": ...}` shape every other kanban tool already answers
with.

**808 -> 864** (`kanban-patrol/16`, 2026-09-03). The board's fifth tool,
`kanban_list_cards` — the only kanban tool that does not take a `task_id` the
caller must already know, and therefore the one an agent arriving cold needs
first. Fifty-six lines, and the shape is deliberate: the filter loop is one
table of `(value, accepted)` pairs walked once, not four `if` blocks, because
"unknown value answers with the accepted set" is one rule and four spellings
of it would drift into three. `_card_payload` is a *net* reduction pushed up
to module scope — `kanban_show_card` listed eight fields inline and now shares
it, and the row itself is `kanban_store.card_row`, the same function
`GET /api/kanban/cards` builds its `KanbanCardResponse` from. No column logic
landed here: `column_for` lives in `kanban_store.py` beside the stage it reads.

**864 -> 887** (`kanban-patrol/15`, 2026-09-04). The board's sixth tool and
`16`'s last deferred one, `kanban_answer_card` — twenty-three lines wrapping
`kanban_store.answer_card`, deliberately unbuilt until the owner had decided
what Answer *does*, because building it first would have been inventing the
answer in the adapter. No new logic and no new identity path: the actor comes
through the same `_actor_on_the_card` the two writing tools already use, and
the two refusals become the same `{"ok": false, "reason": ...}` shape every
tool here answers with.

**755 -> 808** (`kanban-patrol/29`, 2026-09-03). The two kanban tools that
*write* stop taking the caller's word for who is writing. Fifty-three lines,
and none of it a second identity scheme: `_actor_on_the_card` calls the same
`IPrincipals.resolve` `api/deps.py` already calls, and `_request_headers`
folds the three ways a call can carry no headers — stdio, no identity header,
an identity header with no proxy signature — into one `None` so the decision
is made at one call site rather than at two tool bodies. The rest is the
import of `Context` (guarded, because the transport is an extra), the two
`ctx` parameters, and the comment recording why that annotation must stay
bare. A private module for two functions was priced and rejected: they read
`services.principals` and are called only from tool bodies, so the file that
holds the door is the file that should hold the doorkeeper.

**887 -> 891** (`kanban-patrol/08`, 2026-09-04). Four lines: `run_workflow`
and `WorkflowRuns.run` take an optional `session_id` and pass it to the two
places this door already wrote `""`. It is a caller *declaring* a sitting,
never the server minting one — `test_a_sitting_is_named_by_the_browser.py`
still pins that — and it is what lets an agent working a board card over MCP
mark its runs so the next patrol skips them.


**887 -> 897** (`osg-agent-experience/25`, 2026-09-04). Ten lines,
`get_engineering_rules` — the second half of the sentence the server's own
instructions already made mandatory. `get_node_vocabulary` says what exists;
this says what may be built out of it, for a caller who has installed the
wheel and therefore has no copy of this repository's architecture document.
The text is not here: it is package data with one reader
(`engineering_rules.py`), and this is a wrapper over it, so the rules cannot
acquire a second spelling on the transport that serves them.
**897 -> 947** (`osg-agent-experience/25`). Fifty lines, `kanban_file_card` —
the one kanban tool that *creates* a card, and thirty-two of the fifty are
its docstring, which is the same argument this entry opens with: over MCP the
docstring is the interface, and a model has to be told which three kinds this
door files, that the id is a slug of the title so two ideas cannot share one,
and that `agent_model`/`agent_effort` are advisory rather than a decision
somebody made. No new logic: `kanban_store.file_idea_card` owns every
refusal, and `_actor_on_the_card` — already here — owns whose name lands on
the card.

**947 -> 959** (`osg-agent-experience/25`, slice 4, 2026-09-04). Twelve lines,
`kanban_triage` — the board's seventh tool and the first read-only one that
answers a *ranking* rather than a filter: `kanban_list_cards` answers "what is
here," this answers "what first." No new logic: `kanban_store.triage` owns
the ordering and the `why_here` sentence entirely; this filters `list_cards`
by board and adds `rank`/`why_here` onto the same `_card_payload` row every
other kanban tool already answers with.

**959 -> 963** (`osg-agent-experience/33`, 2026-09-05). Four lines, and they
are a field the vocabulary was already the source of and did not publish: a
`select` field's `options`. `kind: select` tells a composing client a string
goes here and not *which* strings, so `matchMode` was still a guess — and a
guessed picker value is `validate`'s *not an option* finding rather than a
run. Read off the same catalogue record as every other key beside it; no new
reader, and nothing here decides anything.
**963 -> 970** (`osg-agent-experience/48`). Seven lines: an import and the
readiness refusal, returned in the `error`/`findings` shape an uncompilable
document already gets. No new decision here — `model_readiness` holds the
predicate and the sentence; this door only says it in its own shape.
**970 -> 971** (`osg-agent-experience/53`, 2026-09-05). One line: a generated
port group publishes its own `max_connections`, off the same catalogue record
the static ports beside it already read it from. The renderer had been
printing the literal `unlimited` for a branch port that takes one edge,
because the payload gave it nothing to print instead.
**971 -> 979** (`osg-agent-experience/46`, 2026-09-05). Eight lines: the two
runtime-minted namespaces (`tool.<name>`, `function.<name>`) publish the ports
every member of them has, where a one-line hint stood. Same shape as the line
above and the same reason — the payload gave a composing client a sentence and
no port ids, so the ids had to be read out of `default_port_resolver`'s
fallback, which accepts any in-port id and draws none of them. The ports are
generated (probed from the factory that mints these nodes) and this door only
reshapes them; no new reader, nothing decided here.

**979 -> 986** (`osg-agent-experience/30`). Seven lines: `kanban_file_card`
returns `unresolved_blockers` beside the id and column, and its docstring says
what `blocked_by` now accepts. The resolution and the refusal are the store's,
which is the point — this door and the CLI could otherwise disagree about what
a blocker is, and that disagreement was the defect.

**986 -> 993** (`osg-agent-experience/29`). Seven lines: the step budget key in
`document_shape.settings`, and the comment saying why it is there. The key,
the sentence and every number in it are `step_budget.py`'s — this door calls
`step_budget_document_hint()` and indexes `STEP_BUDGET_KEYS`, so nothing about
the budget is decided here. A literal typed into this payload is exactly the
defect the ticket closed, one layer along.

**993 -> 994** (`osg-agent-experience/72`). One line, plus its comment: the
`editor_only` mark on each published node type. A composing client that placed
`tool.reddit-search` got a document that validated and ran and then reported
the tool missing, after the model had been paid. The value is read off
`CATALOGUE.editor_only`, which reads the mark the editor's own descriptor
declares — this door decides nothing about it, exactly as it decides nothing
about the step budget one paragraph up.

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

`559 -> 586`, 2026-09-05 (`osg-agent-experience/45`). Twenty-seven lines: the
409 branch on the save route, its `responses=` declaration, `_digest_now`, and
the paragraphs that say why a save may be refused. All of it is the wire — a
status code this endpoint can now answer with, and the sentence that goes with
it — rather than a second reason for this module to change.

`586 -> 619`, 2026-09-05 (`osg-agent-experience/69`). Thirty-three lines: the
`GET /api/workflows/{slug}/events` SSE endpoint — the stream that tells an open
tab another writer changed the package it is editing. The canary is worth
reading honestly here, because a *stream* is arguably a second concern and it
was weighed as one: the three sibling streams all live in the route module for
the surface they belong to (`/api/events` in `main`, both kanban streams in
`routes/kanban.py`), the fan-out itself is a collaborator in
`api/workflow_events.py` and none of its knowledge is here, and what this route
holds is a subscription and a filter. Splitting the catalogue's one stream into
its own route module would have made `workflows.py` shorter and the endpoint
surface harder to find, which is the trade this table exists to refuse.
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

**640 -> 661** (`memory-and-replay/71` and `/74`). Twenty-one lines. Eighteen of them give the module's
*second* cadence reader the gate its first one has had since
`the-boundary-nobody-checked/02`. `read_run_bursts` requires an `audience` and
argues it from the column — `RunBurst.audience` is stored so a reader can
refuse — and `read_runs(with_bursts=True)` reached the same table through
`_attach_bursts` with no such parameter. Two readers of one column disagreeing
about whether it is a gate is a property of *this module*, and the eighteen
lines are the raise, the `WHERE` clause, and the paragraph saying that a
boolean flag cannot be made un-skippable by a signature the way a required
keyword can — so it is made un-skippable by not running.

The other three are `74`: `RunBurst.active_node`, its place in
`_BURST_COLUMNS`, and its place in `_burst_row`. A column is three lines here
by construction — the field, the schema, the writer — which is the shape this
module chose when it made the column list the one declaration both the writer
and the reader read.

**661 -> 792**, 2026-09-04 (`stable-beta-public/03`, slice 2 of
`docs/plans/token-status-bar`). A hundred and thirty-one lines: `spend_summary`
and the three frozen dataclasses it answers with — the **third reader of the
runs table**, beside `read_runs` and `read_run_bursts`.

That is the question this pin asks, so it is answered rather than asserted: a
sum over the rows is not a second reason to change, it is the same one. The
alternative considered and rejected was a `run_spend.py` that opens its own
`readonly_connection` to the same file — which would put the store's column
names, its `CHRONOLOGICAL` sort key and its *"a file this build cannot read is
not an error"* judgement in two modules, and this module's own docstring is
about what it costs when one table has two spellings. A reader that must move
with `_COLUMNS` belongs beside `_COLUMNS`.

**792 -> 803**, 2026-09-04 (`stable-beta-public/03`, slice 3 of
`docs/plans/token-status-bar`). Eleven lines: `spend_summary` grew the
`session_id`-filtered branch that fills `session_by_model` and `session_total`
— the same third reader, the same table, one more `WHERE` on a query it
already ran unfiltered two lines above. Not a second reason to change: it is
the *this session's* half of the question `spend_summary`'s own docstring
already promised slice 3 would answer.

**803 -> 829**, 2026-09-04 (`stable-beta-public/03`, slice 4 of
`docs/plans/token-status-bar`). Twenty-six lines, and almost none of them are
arithmetic: `_DETAILS` (the three `input_token_details` / `output_token_details`
keys as one table), `_detail`, `_added` and `_total_of` — four small named
things whose entire job is that **`None` is not `0`**. The sum itself is one
line in the walk that was already there.

Written as named functions rather than inlined on purpose, and that is the
argument for the twenty-six: `spent.get("input_token_details", {}).get(
"cache_read") or 0` is one expression, reads correctly, and is the defect —
it turns *no provider reported a cache figure* into *nothing came from cache*,
which the status bar then prints as a measurement. A rule that costs one
keystroke to break belongs somewhere a test can point at, and `_added`'s two
branches are the whole tri-state.

Still the third reader of the runs table, not a fourth reason to change: these
read deeper into the same `usage` document the same walk already parsed.

What would be a second reason, and is the shape to refuse here: a price table.
Tokens are what the store kept; money is a per-provider rate card nobody in
this repository holds, and the moment one arrives it is a module of its own
with a version and a currency, not another sum next to this one.
"""

#: Nine modules, derived and then argued for one at a time. Nothing in this
#: table was chosen; the census below produces the keys and this table has to
#: match it exactly, which is the mechanism the class censuses arrived at after
#: hand-picked pins were found to cover only the classes somebody had already
#: worried about.
SCHEMAS = """
Every response and request shape this API publishes, in one module, because
**there is exactly one of them**: `docs/openapi.json` is generated from these
classes and is the contract `contractDrift.test.ts` holds the TypeScript client
to. A second schema module would not be a second reason to change — it would be
the same reason, reached through two imports.

Its length is the wire's width, which is the argument `api/routes/workflows.py`
already records one level up and `WorkflowFileClient` records on the client
end: *"the class does not get to be narrower than the API it adapts."* Sixty-odd
Pydantic classes with no behaviour between them — no branches, no loops, three
`model_validator`s in the whole file — is a declaration list, and the ceiling's
own preamble says that is what the recorded-exception mechanism exists for.

**The seam that was considered and does not pay.** Splitting by subject — runs,
workflows, threads, mcp, kanban — is the obvious cut and the routes are already
split that way, so it looks free. It is not: several shapes are shared across
those subjects (`RecordedUsage` is read by the recordings door and the spend
door; `Audience` reaches four of them), so the split either duplicates them or
grows a `schemas/common.py` that every module imports, which is the same file
with an extra hop. What it would buy is a shorter file; what it would cost is
that `generate_openapi.py`, the drift test and every route module would each
need to know which of six modules a shape lives in.

**What this number is watching for is behaviour arriving.** A validator, a
computed field, a `model_validator` that reaches outside the document — those
are reasons to change that are not the wire's width, and any of them would move
the code count without moving the class count. That is the shape to refuse.

`490 -> 520`, 2026-09-04 (`stable-beta-public/03`, slice 1 of
`docs/plans/token-status-bar`). Thirty lines: `ModelSpendResponse`,
`SessionSpendResponse` and `SpendResponse`, the publication of what the runs
this deployment kept have cost. Declarations and their documentation, and the
documentation is load-bearing rather than decorative — three of those fields
are `int | None` where `None` means *no provider reported this* and `0` means
*nothing was spent*, and the comment beside each is the only place that
distinction is written down for whoever mirrors it next.

`520 -> 529`, 2026-09-04 (`kanban-patrol/15`). Nine lines: three fields on
`KanbanCardResponse` (the decision recorded on a Needs You card, who made it,
when) and `KanbanAnswerRequest`/`KanbanAnswerResponse` for the route that
writes them. Declarations and their documentation again, and again the
documentation is the load-bearing part: `actor` on the request is the
caller's *claim*, dropped rather than merged on a deployment that resolves a
principal, and the comment beside it is where that is said on the wire side.

`529 -> 534`, 2026-09-04 (`osg-agent-experience/25`). Five fields on
`KanbanCardResponse` — the brief a card filed from a conversation carries
(`story`, `done_when`, `blocked_by`) and the model and effort to give a
subagent that takes it. Declarations and their documentation once more, and
the documentation earns the lines the same way: `blocked_by` is a `list[str]`
here and JSON text in the column, and the comment is where a reader of the
wire is told the encoding is the store's business and not theirs.

`534 -> 556`, 2026-09-05 (`osg-agent-experience/45`). Twenty-two lines: the
`digest` field on the two shapes a client reads a package through, the
`base_digest` a save quotes back, and `SaveConflictDetail`/`SaveConflictResponse`
— the body of the 409 that refuses a save whose file moved on disk. The comments
are again the load-bearing half: an empty digest means *I cannot tell you which
version*, and a reader who takes it for *unchanged* turns the guard off exactly
where it is needed.
"""

KANBAN_STORE = """
The kanban card store — the stage machine, the evidence gate, and the two
writes that put a card on the board. It crossed the ceiling on the day it
gained the second write (`osg-agent-experience/25`), which is the honest
account: 493 -> 544 is `file_idea_card`, `idea_task_id`, `_decode_blocked_by`
and five columns.

**Why the second write is not a flag on the first.** `file_card` records what
a patrol found, and its whole justification is the run thread behind it, which
any later reader can open; it uses `INSERT OR IGNORE`, because the same
finding seen twice is one card. `file_idea_card` records what somebody said
they wanted, the conversation behind it is gone, and a second card with one
title is two different ideas — so it requires the brief and refuses the
duplicate. Every default and every refusal is opposite. One function with a
mode switch would be a function whose docstring has to say "unless" four
times, which is the god-object shape one function down.

**Why the module and not a sibling.** `column_for` decides where a filed card
lands and reads the same `Stage` and kind vocabulary the stage machine owns;
`card_row` is the one row both doors publish. A `kanban_ideas.py` importing
all three back would be a second module with no boundary — the split this
table exists to prompt is worth making when a *reason to change* separates,
and "what a card is and where it goes" is still one reason.

Its length is docstrings, the same as `mcp_server.py`'s: this module is what
two doors and an HTTP route all wrap, so the argument for each refusal is
written where the refusal is rather than three times at the doors.

**2026-09-04, `osg-agent-experience/25` slice 4.** `TriageRow` and `triage`
added: 544 -> 582. Pure ordering over `Card`s already in memory, no new
write path and no new column — it belongs beside `column_for` for the same
reason `column_for` is here at all, one function computing where a card
sits in a rule both doors (MCP `kanban_triage`, CLI `kanban triage`) must
answer identically.

**2026-09-05, `osg-agent-experience/36`.** `store_digest` added: 582 -> 600.
Eighteen lines and no new write path — the *opposite* of one: it is a read
whose whole purpose is to let a watcher outside this module tell whether any
of the three writes happened, because every one of them arrives from another
process (a CLI, an MCP tool) and the server that serves the board is one more
reader of this file. It belongs here rather than beside the stream for the
reason `column_for` does: it knows this schema's columns, and a digest built
in `api/` would be a second place that has to be told when one is added.

**2026-09-05, `osg-agent-experience/30`.** `resolve_blocked_by`,
`unresolved_blockers` and `_known_card_ids` added, plus the branch in
`triage`'s `why_here`: 600 -> 660. Sixty lines, and about forty of them are
the docstring on `resolve_blocked_by` — the argument for why a blocker naming
another project is refused while one no card carries *yet* is only reported,
which is a judgement two doors and a board all have to make the same way.
That is the same reason every other refusal's argument lives here: writing it
at the CLI would leave the MCP tool free to disagree, and the defect this
closed was exactly a field that meant different things depending on who typed
it.
"""

RECORDED: dict[str, Recorded] = {
    "kanban_store.py": Recorded(690, KANBAN_STORE),
    "compile/node_runtime.py": Recorded(583, NODE_RUNTIME),
    "cli.py": Recorded(1694, CLI),
    "compile/workflow_compiler.py": Recorded(1018, WORKFLOW_COMPILER),
    "api/streaming.py": Recorded(1038, STREAMING),
    "prebuilt_mcp.py": Recorded(758, PREBUILT_MCP),
    "mcp_server.py": Recorded(994, MCP_SERVER),
    "api/routes/workflows.py": Recorded(619, ROUTES_WORKFLOWS),
    "run_sinks.py": Recorded(829, RUN_SINKS),
    "api/schemas.py": Recorded(556, SCHEMAS),
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
