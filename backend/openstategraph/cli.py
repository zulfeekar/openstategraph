"""`openstategraph` — the console script.

**Tier 2, provisional** as a Python module; the *command line* is the actual
contract and it follows the Tier 1 deprecation policy in `docs/stability.md`.
Nobody should be importing this module; everybody may depend on the commands.

**Why a CLI at all.** A framework is adopted in its first five minutes, and
until now those five minutes required writing a Python file to find out whether
a package even compiles. `openstategraph validate ./my-workflow` is the answer,
and `openstategraph run ./my-workflow "…"` is the demo.

**Two rules this module lives under, and a reviewer should enforce both:**

1. **No new logic.** Every command wraps a seam that already exists —
   `load_workflow`, `ValidateWorkflowTool`, `scaffold`, `run_build`,
   `PackageKnowledge`, `api.main:app`, `mcp_server.main`. A command body longer
   than argument handling plus a call is a bug: it means behaviour now exists
   here that the library does not have, and the CLI has become a second
   implementation of the framework.
2. **argparse only.** `click` and `rich` are what the reference framework
   spends half its dependency floor on. A project arguing for a four-dependency
   core cannot then add two for colour and a decorator syntax.

**Exit codes are the API for CI**, so they are fixed and few:

| | |
| --- | --- |
| `0` | success |
| `1` | the run failed, or validation found blocking findings |
| `2` | usage error — bad arguments, unknown command (argparse's own code) |
| `3` | a required extra is not installed; the message names the install line |

Every command works from any working directory: paths come from the arguments
and are resolved against the caller's cwd, and nothing is relative to a
checkout. The commands that *create* packages — `new` and `examples copy` —
write to `workflows_root()`, the same directory every reader resolves, with
`--root` as the explicit override that rule already puts on top. They used to
spell `Path.cwd() / "workflows"` themselves, which is the same answer only when
the project happens to use the convention and you happen to be standing in it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

# The one import this module makes eagerly, and it is stdlib-only: `--template`
# uses argparse `choices`, so the catalogue has to exist while the parser is
# being built. Everything else is still imported inside its command.
from openstategraph import templates

#: Fixed, documented above, and referenced by name everywhere below so a
#: reader never has to decode a bare integer.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from openstategraph.providers import ProviderEnvironment
    from openstategraph.results import RunResult

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_MISSING_EXTRA = 3


def _error(message: str) -> int:
    print(message, file=sys.stderr)
    return EXIT_FAILURE


def _terminal_message(exc: Exception) -> str:
    """What an uncaught exception says at the terminal — the message it was
    raised with, never the name of the Python class that carries it.

    Every exception this project raises on purpose already writes its own
    sentence (`PackageNotFound`, `FileNotFoundError` from a missing eval
    dataset, `ValueError` from a bad document) — that is the whole point of
    `errors.py` existing. Prefixing it with `type(exc).__name__` does not add
    information a reader can act on; it just makes half the CLI's errors open
    in a different voice than the other half (ticket 83).
    """
    return str(exc)


def _usage(message: str) -> int:
    """A bad *invocation*, not a failed run — argparse's own code, so CI can
    tell "you typed it wrong" from "it did not work"."""
    print(message, file=sys.stderr)
    return EXIT_USAGE


def _ephemeral_state() -> dict[str, Any]:
    """Durability for a command that compiles a graph and never runs it.

    `organisms-first-class` 77. `load_workflow`'s defaults are the *run*
    defaults, and they are right for a run: a sqlite saver and a sqlite store
    under `state_dir()`, so a `human.approval` pause survives a restart. A
    command that only compiles inherits them anyway, and the loader's
    `WorkflowServices` is rooted at `directory.parent` — so `validate` on a
    package created `.openstategraph/memory.sqlite` in whatever directory
    happened to *contain* the package. A template data directory shipped in
    the wheel, in the case that found this; a user's home or a checkout root
    just as easily. **A command whose whole contract is "read this and tell me
    what is wrong with it" must not write into the tree it was pointed at.**

    Both handles, together, because the pair is the defect: `_compiler_findings`
    already passed an `InMemorySaver` for exactly this reason and the Store —
    the sibling default, added later — was simply not passed beside it, which
    is what one of the two commands leaking one of the two files looked like.
    Not `None` and not a skipped compile: `builder.compile(store=)` is handed
    whatever this returns, so a compile-only command still exercises the same
    assembly a run does, and an in-memory pair is what makes that free.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    return {"checkpointer": InMemorySaver(), "store": InMemoryStore()}


def _load(args: argparse.Namespace, *, model: Any = None, ephemeral: bool = False) -> Any:
    """The one `load_workflow` call the whole CLI shares.

    `model` overrides what the arguments resolve to, for the commands that
    compile a graph without ever calling one — see `_drawing_only_model`.
    `ephemeral` is the same commands' answer to the same question about state:
    see `_ephemeral_state`. Both default to the run's answer, so a command
    opts *out* of durability by saying so rather than inheriting silence.
    """
    from openstategraph import load_workflow

    return load_workflow(
        args.package,
        model=model if model is not None else getattr(args, "model", None),
        trace_file=getattr(args, "trace_file", None),
        knowledge_dir=getattr(args, "knowledge_dir", None),
        **(_ephemeral_state() if ephemeral else {}),
    )


def _drawing_only_model() -> Any:
    """A model for a command that compiles a graph and never calls one.

    `graph` renders the compiled topology. It invokes nothing — but *building*
    the graph built a chat model, so the command required the resolved
    provider's integration package to be installed. In a venv holding only
    `[ollama]`, a document that resolved to Anthropic could not be **drawn**.
    Found by installing the wheel and using it.

    Reuses the stand-in that already exists for an unconfigured provider, so
    there is one thing in this codebase that means "a model nothing may call",
    and it explains itself if anything ever does.
    """
    from openstategraph.chat_model import UnconfiguredProvider

    return UnconfiguredProvider(
        "`openstategraph graph` compiles the topology to draw it and builds no "
        "model — nothing here should be calling one. Use `run` to execute the "
        "workflow."
    )


# --------------------------------------------------------------------------
# commands


def split_context_flags(pairs: Sequence[str]) -> tuple[dict[str, str], str]:
    """`--context key=value` occurrences as a mapping, or the usage error.

    **Grammar only.** Whether `acme` is a legal value for `tenant` needs the
    document, and that question is `coerce_context_flags`' — this one answers
    only *did they type a `key=value` pair*, which is the same question
    argparse answers for every other flag and gets the same exit code
    (`EXIT_USAGE`). A run's exit codes are this CLI's API: a script must be
    able to tell "you typed it wrong" from "the workflow refused it".

    A value may contain `=` — `--context filter=a=b` is a filter of `a=b` —
    because the split is on the *first* one. A key may not: there is nothing
    before the first `=` to be one.
    """
    values: dict[str, str] = {}
    for pair in pairs or ():
        key, separator, value = pair.partition("=")
        if not separator:
            return {}, f"--context expects key=value, and got {pair!r}."
        if not key.strip():
            return {}, f"--context expects key=value, and got {pair!r} with no key before the '='."
        values[key.strip()] = value
    return values, ""


def cmd_run(args: argparse.Namespace) -> int:
    """`load_workflow(pkg).ask(question)`, and nothing else."""
    workflow = _load(args)
    # Grammar first and the document second, because the two failures are
    # different exit codes: a pair with no `=` is a mistyped command line
    # (2, argparse's own), and a value the *declaration* refuses is a run that
    # cannot start (1). Both before the graph is invoked and before a single
    # token is spent.
    from openstategraph.compile.run_context import coerce_context_flags

    supplied, usage = split_context_flags(args.context or [])
    if usage:
        return _usage(usage)
    context = coerce_context_flags(workflow.document, supplied, slug=workflow.slug)
    # The thread id is minted HERE rather than left to `ask()` so that `--json`
    # can report it: a caller who wants a follow-up turn needs the id of the
    # conversation they just had, and an id generated inside the run and thrown
    # away is an id they can never continue.
    thread_id = args.thread_id or f"openstategraph-cli-{uuid.uuid4().hex}"
    result = workflow.ask(args.question, thread_id=thread_id, context=context or None)

    if args.json:
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "decisions": result.decisions,
                    "outputs": result.outputs,
                    "warnings": result.warnings,
                    "attempts": result.attempts,
                    # What the run spent, per model, and one total beside it
                    # (`workflow-gallery` 35). `total_tokens` is `null` — never
                    # `0` — when no provider reported: a script piping this
                    # must be able to tell "free" from "nobody said".
                    "usage": result.usage,
                    "total_tokens": result.total_tokens,
                    # `null` for a run that finished. A script piping this must
                    # be able to tell an answer from a question it was asked
                    # (`workflow-gallery` 24).
                    "pause": result.pause,
                    "thread_id": thread_id,
                    "slug": workflow.slug,
                },
                indent=2,
            )
        )
        return run_exit_code(result)

    for line in run_report_lines(result):
        # Degrade loud, never silent — on stderr, so `run … > answer.txt` still
        # gives you only the answer while the degradation stays visible.
        print(line, file=sys.stderr)
    for line in pause_report_lines(result, package=args.package, thread_id=thread_id):
        print(line, file=sys.stderr)
    print(result)
    return run_exit_code(result)


def resume_command_line(package: str, thread_id: str) -> str:
    """The one spelling of the command that finishes a paused run.

    `run`'s pause report and `threads show`'s both name this verb, and a
    paused thread has exactly one true resume command — so both build the
    line here rather than each writing its own sentence. `ship-it` 52 and 53
    each found a second, drifted spelling of a sentence that should have had
    one home; this is that home for the resume line (`workflow-gallery` 76).
    """
    return f"openstategraph resume {package} {thread_id} --approve | --reject --feedback '…'"


def mount_chain_line(pause: Mapping[str, Any] | None) -> str:
    """The mounted packages a pause is waiting inside, as one readable phrase.

    Empty for a gate in the document a person actually ran, which is where a
    gate usually is. When it is not, the question on screen was written by a
    package the top document merely *mounts*, and until this there was nothing
    on any surface saying so — the reviewer answering a day later could read
    the gate's sentence and still not know which document to open
    (`organisms-first-class` 64).

    One phrasing, built here and printed by both the run report and the resume
    announcement, because a pause described two ways is a pause described
    wrongly once.
    """
    chain = (pause or {}).get("mount") or []
    if not isinstance(chain, (list, tuple)):
        return ""
    names = [
        str((step or {}).get("workflow") or "").strip()
        for step in chain
        if isinstance(step, Mapping)
    ]
    named = [name for name in names if name]
    if not named:
        return ""
    return " -> ".join(named) + (
        " (a workflow this one mounts)"
        if len(named) == 1
        else " (workflows this one mounts, outermost first)"
    )


def pause_report_lines(result: "RunResult", *, package: str, thread_id: str) -> list[str]:
    """What a run that stopped at a `human.approval` gate has to say for itself.

    Empty for every run that finished, which is nearly all of them.

    A paused run answered *nothing* and used to say so with an empty line and
    exit 0 — the same silence the blocking HTTP endpoint refuses with a 409
    naming the endpoint that can carry it. This is that refusal at the
    terminal, and it goes one further: it names the exact command, because the
    pause report is the only place a person learns the verb exists.
    """
    if not result.pause:
        return []
    pause = result.pause
    lines = [f"paused: {pause.get('message') or 'a decision is needed'}"]
    candidate = str(pause.get("candidate") or "").strip()
    if candidate:
        lines.append(f"  candidate: {candidate}")
    asked_by = mount_chain_line(pause)
    if asked_by:
        lines.append(f"  asked by: {asked_by}")
    lines.append(f"  thread: {thread_id}")
    lines.append(f"  finish it: {resume_command_line(package, thread_id)}")
    return lines


def cmd_resume(args: argparse.Namespace) -> int:
    """`CompiledWorkflow.resume` — the other half of `run`, and its own verb.

    A person is the only thing a `human.approval` node is waiting for, and the
    terminal is where a person is already sitting; until this, a run could be
    *started* there and finished only over HTTP.

    The decision is a **required** choice between two flags rather than a value
    with a default, so the one thing this command cannot do is guess a verdict
    nobody gave — argparse refuses with the usage code, before anything is
    loaded or resumed.

    It says what it is about to do first. A resume runs the rest of the graph
    against a durable checkpoint — every tool downstream of the gate, for real
    — and consumes the pause, so the announcement is the last moment a
    `Ctrl-C` still means something. On stderr, so `resume … > answer.txt` is
    still just the answer.
    """
    decision = "approve" if args.approve else "reject"
    if args.feedback and decision == "approve":
        return _usage(
            "--feedback is a note on a rejection; an approval carries none. "
            "Drop it, or say --reject."
        )

    workflow = _load(args)
    pause = workflow.pause(args.thread_id)
    if pause is None:
        return _error(
            f"thread {args.thread_id!r} is not paused — there is nothing waiting "
            "for a decision. `openstategraph threads list` reports which threads are"
        )
    print(f"resuming {args.thread_id} with: {decision}", file=sys.stderr)
    print(f"  gate: {pause.get('message') or ''}", file=sys.stderr)
    print(f"  candidate: {str(pause.get('candidate') or '').strip()}", file=sys.stderr)
    asked_by = mount_chain_line(pause)
    if asked_by:
        print(f"  asked by: {asked_by}", file=sys.stderr)
    print("  this runs the rest of the workflow and cannot be undone", file=sys.stderr)

    result = workflow.resume(args.thread_id, decision=decision, feedback=args.feedback)

    if args.json:
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "decisions": result.decisions,
                    "outputs": result.outputs,
                    "warnings": result.warnings,
                    "attempts": result.attempts,
                    "usage": result.usage,
                    "total_tokens": result.total_tokens,
                    "pause": result.pause,
                    "thread_id": args.thread_id,
                    "slug": workflow.slug,
                },
                indent=2,
            )
        )
        return run_exit_code(result)

    for line in run_report_lines(result):
        print(line, file=sys.stderr)
    # A rejection re-enters the drafter and stops at the same gate again, so a
    # resumed run pauses exactly as a started one does — and reports it the
    # same way, with the command to type next.
    for line in pause_report_lines(result, package=args.package, thread_id=args.thread_id):
        print(line, file=sys.stderr)
    print(result)
    return run_exit_code(result)


def run_report_lines(result: "RunResult") -> list[str]:
    """A run's health report, prefixed by what each line actually is.

    Every line used to be `warning:` — including the one that ended the run
    and produced the `1` this command exits with, so a reader grepping for
    `error:` on a failed run found nothing and the prefix contradicted the
    exit code beside it (`workflow-gallery` 44).

    The split it needs already exists and is the same one `run_exit_code`
    gates on: `failures` is the claim the run failed, `warnings` is the whole
    report (`workflow-gallery` 49). So the prefix is derived from that
    membership rather than decided here — one rule, one place, and a line
    cannot be an `error:` on one surface and a `warning:` on the next.

    Order is `warnings`' order, which puts compile findings before what
    happened when it ran. Demoting nothing: a failure keeps its position.

    A failure absent from `warnings` is still printed, at the end. `ask()`
    builds the two so that `failures` is a subset — but a `RunResult` can be
    assembled by hand, for a resumed run or a test, and a reason this function
    silently dropped would be exactly the silence this ticket is about.
    """
    failures = set(result.failures)
    lines = [
        f"{'error' if warning in failures else 'warning'}: {warning}" for warning in result.warnings
    ]
    reported = set(result.warnings)
    lines += [f"error: {failure}" for failure in result.failures if failure not in reported]
    return lines


def run_exit_code(result: "RunResult") -> int:
    """`0` unless the run produced no answer *and* something went wrong.

    **This is the one place the rule lives**, which ticket 53 asked for in as
    many words: two failure modes were exiting with two different codes and
    the rule was decided per call site, so nobody could say what a `1` meant.

    Found by building the wheel and using it: a new user's first `run` after
    `new` has no provider credential, and got back an empty line and a success
    exit code. The diagnosis was in `outputs` and only `--json` showed it.

    The condition is deliberately both halves, not either:

    - **A step failed but there is still an answer** is a *degrade*, which this
      project prefers to a crash — a workflow whose optional tool was missing
      still answered, and failing the exit code there would make every partial
      run look broken. The warning on stderr is the report.
    - **An empty answer with nothing wrong** is legal too; a workflow may
      answer with nothing.

    Only the pair is a failed run, and a CLI that calls that success is a CLI
    a script cannot gate on.

    Both halves were being asked too narrowly, which is how a workflow
    mounting `no-such-package-anywhere` exited 0 (ticket 53):

    - *"produced no answer"* now includes `NO_ANSWER_PRODUCED`. The output
      node substitutes that sentence when it has nothing, so the string was
      never empty and the first test short-circuited every time.
    - *"something went wrong"* now includes `result.warnings`. A failed node
      leaves a marker in `outputs`; a mount that could not be loaded leaves
      none — it is a **compile** finding, and it arrives on `warnings`, which
      this function was not reading.

    **It reads `result.failures`, not `result.warnings`, and that is the whole
    reason the split exists.** `warnings` became the run's full health report
    when the library door was joined to `run_health` (`workflow-gallery` 49),
    and that report includes a node that produced nothing — which
    `silent_node_warnings` says must never reach an exit code: *a silent node
    is a report about how the answer was reached, not a claim that the run
    failed*. Gating on `warnings` would have made every legally-empty answer
    with a quiet node exit 1. `failures` carries both of the things this
    function ever wanted, so `outputs` is now belt to its braces rather than
    the only strap.
    """
    from openstategraph.compile.node_runtime import NO_ANSWER_PRODUCED
    from openstategraph.compile.workflow_compiler import node_failure_warnings

    # **A pause is checked before the answer, and it is the one condition that
    # does not need "and something went wrong"** (`workflow-gallery` 24). A run
    # stopped at a `human.approval` gate has not failed and has not answered —
    # it is waiting — and a CLI that calls that success is a CLI that reports a
    # truncated run as a finished one. The blocking HTTP endpoint has refused
    # the same document with a 409 since the node shipped; this is that
    # refusal's exit code.
    if result.pause:
        return EXIT_FAILURE
    answer = str(result).strip()
    if answer and answer != NO_ANSWER_PRODUCED:
        return EXIT_OK
    # `outputs` is still read directly, even though `failures` already carries
    # what is in it, because a `RunResult` can be built by hand — a resumed
    # run, a test — and a failure marker sitting in `outputs` is a failed run
    # whoever assembled the object.
    went_wrong = bool(node_failure_warnings(result.outputs)) or bool(result.failures)
    return EXIT_FAILURE if went_wrong else EXIT_OK


def cmd_eval(args: argparse.Namespace) -> int:
    """`evaluation.evaluate_package` — the harness's one seam, printed.

    Exits 1 below `--threshold` so a CI job can gate on it. The gate is
    *overall* accuracy (answerable questions graded by execution accuracy,
    unanswerable ones by whether the system declined): gating on execution
    accuracy alone would let a system score well by inventing an answer to
    every question it cannot possibly know.

    **This costs money and calls a model.** It is not in the default test run;
    see `docs/evaluation.md`.
    """
    from openstategraph.evaluation import evaluate_package

    scorecard = evaluate_package(
        args.package,
        dataset_path=args.dataset,
        model=args.model,
        limit=args.limit,
        # Progress on stderr, so `eval --json > card.json` still pipes cleanly
        # and a thirty-question run is not thirty minutes of silence.
        on_item=None
        if args.json
        else lambda item: print(f"  {item.case_id:<6} {item.verdict}", file=sys.stderr, flush=True),
    )
    print(json.dumps(scorecard.to_json(), indent=2) if args.json else scorecard.render())
    return EXIT_OK if scorecard.meets(args.threshold) else EXIT_FAILURE


def _compiler_findings(package: Path) -> tuple[list[str], list[str]]:
    """What the compiler noticed while building this package: (problems, notes).

    `organisms-first-class` 66. This docstring used to be a lie by omission —
    the command said "the compiler's own plan **and findings**" while reading
    `plan.warnings` and nothing else, so not one of the twelve `Finding` kinds
    had ever reached it. A document whose second Output bypassed the guardrail
    the rest of it kept printed `VALID`; `run`, one command later, printed the
    sentence twice. The command a person uses *before* shipping was the one
    that could not see them.

    The findings are recorded while the graph is **built**, not while it is
    run, so collecting them costs a compile and no model — the same
    drawing-only stand-in `graph` uses, so this stays the zero-token gate a
    script runs before a run costs anything, on a machine with no credential.
    (One recording site is genuinely run-time — the injection-screening gap
    inside `_agent`'s per-skill `agent_for` closure — so that one cause of
    `CAPABILITY_FAILED` cannot appear here. Its kind still can, from the
    several build-time sites that record it.)

    **The split is `REPORT_ONLY`'s, read at this surface rather than restated
    at it.** A failure-classed finding is a claim that the graph cannot do
    what it was drawn to do, which is exactly `validate`'s one question — is
    this ready to run **here** — so it is a *problem* and moves the exit code,
    the thing `failure_warnings()` was built for. A report is advice about the
    drawing; `8bda508`'s rule is that it may never move an exit code, and
    `support-triage` ships an unwired grader on purpose, so the rule has a
    real package guarding it.

    Measured before committing to that: of the 32 shipped packages (23
    examples, 9 workflows) exactly one carries a finding at all, and it is a
    report-only one — so **no shipped package's exit code moved**, measured
    again when `workflow-gallery` 61 settled the two members `9729338` brought
    to an exit code for the first time. 61 decided them apart on run evidence:
    `UNENFORCED_OUTCOME` became a report (it is the same predicate
    `UNWIRED_REVISE` reports one level down, and the run answers with nothing
    skipped), and `UNGUARDED_EXIT` stayed a problem (the unguarded door emits
    what the document's own policy redacts on the path beside it). This
    command deliberately holds no opinion of its own, so moving a member in
    `REPORT_ONLY` moves it here with no edit.

    A package that will not load at all is a problem, not a crash: `run` would
    meet the same wall, and saying so is this command's job.
    """
    from openstategraph import load_workflow

    try:
        # In-memory durability rather than the durable default: validating a
        # package must not create a checkpoint file — or a memory database —
        # for a run that never happens. See `_ephemeral_state`.
        workflow = load_workflow(
            package, model=_drawing_only_model(), **_ephemeral_state()
        )
    except Exception as exc:  # noqa: BLE001 - reported, never raised at a user
        return ([f"this package could not be compiled: {_terminal_message(exc)}"], [])
    try:
        failures = list(workflow.failure_warnings)
        blame = set(failures)
        return (failures, [w for w in workflow.warnings if w not in blame])
    finally:
        workflow.close()


def cmd_validate(args: argparse.Namespace) -> int:
    """The compiler's own plan and findings, via the seam MCP already uses.

    `prebuilt_architect.ValidateWorkflowTool` — not a second validator. Two
    validators is how a document passes one gate and fails the other. The
    findings that seam cannot see, because they are recorded by a *build*
    rather than by a plan, come from `_compiler_findings` below.

    A developer surface, and the sentences say so — they name node ids, tool
    types and package slugs. `api/audience.py` redacts those for a customer
    reading a run; nobody reaches this command except by having the package on
    their disk.
    """
    from openstategraph.prebuilt_architect import ValidateWorkflowTool
    from openstategraph.schema import normalize_document
    from openstategraph.validation import unresolved_mounts, unresolved_tool_bindings

    target = Path(args.target).expanduser().resolve()
    manifest = target if target.is_file() else target / "workflow.json"
    if not manifest.is_file():
        return _error(f"no workflow document at {manifest} — is that a workflow package?")

    try:
        document = normalize_document(json.loads(manifest.read_text()))
    except Exception as exc:
        return _error(_terminal_message(exc))

    verdict = ValidateWorkflowTool().run(document=json.dumps(document))
    report = verdict.content if verdict.ok else str(verdict.error)

    # The one check the in-memory plan cannot make (ticket 53). A mount is the
    # only reference a document holds to something outside itself, resolving
    # it is a filesystem lookup, and until this `validate` answered VALID for
    # a package mounting a slug that does not exist — the likeliest way there
    # is to break composition, and the cheapest one to catch.
    #
    # The root is where this package's *siblings* live, which is the same
    # directory the loader will search at run time. Taken from the package's
    # own location rather than from `workflows_root()`, so validating a
    # package by path answers about that path.
    # `slug=` is the package's own folder name, so a mount naming it closes a
    # cycle *here* and is refused by the same sentence the build raises rather
    # than by a later, more expensive surface (ticket 27).
    mounts = unresolved_mounts(document, manifest.parent.parent, slug=manifest.parent.name)
    # The second thing an in-memory plan cannot answer (ticket 79), and the
    # same shape as the first: a bound tool's implementation lives in this
    # installation — built-in, an installed plugin, or the package's own
    # `tools/` — and a document that travelled without its package binds tools
    # nothing here can supply. `validate` answered VALID for exactly that, and
    # printed `Tool bindings:` beneath it, while the run three warnings later
    # was the only surface telling the truth.
    #
    # It is a PROBLEM rather than a note, deliberately, and the exit code is
    # the reason: `validate` is the zero-token gate a script runs before a run
    # costs anything, and its one answer is "is this ready to run **here**".
    # An agent drawn with three tools and bound to none is not. Priced and
    # rejected: putting it on `plan.warnings` (that channel is the compiler's,
    # is asserted empty by every shipped example's own document test, and
    # carries no root, so it cannot see a package's `tools/` at all), and
    # reporting it under a VALID heading (which is the shape ticket 53 removed
    # from this command one paragraph above).
    tools = unresolved_tool_bindings(document, manifest.parent)
    # The third thing the in-memory plan cannot answer, and the largest of them
    # (`organisms-first-class` 66): everything the compiler noticed while
    # actually building the graph. Only for a real package — `validate` also
    # takes a bare document file, and there is nothing to compile without the
    # `tools/`, `functions/` and sibling packages a folder carries.
    findings, notes = (
        _compiler_findings(manifest.parent) if manifest.name == "workflow.json" else ([], [])
    )
    found = [line[2:] for line in report.splitlines() if line.startswith("- ")]
    # `plan.warnings` reaches this command twice — through the seam above and
    # again on `failure_warnings` — and one problem said once is the point.
    findings = [f for f in findings if f not in found]
    problems = [*found, *mounts, *tools, *findings]
    topology = report.split("\n\n", 1)[1] if "\n\n" in report else ""
    if problems:
        # Folded into the verdict rather than printed after it: one command,
        # one answer. A VALID followed by a list of problems is the shape
        # ticket 53 removed from this command.
        report = "\n".join(["PROBLEMS FOUND:", *(f"- {p}" for p in problems), "", topology])
    if notes:
        # Under their own heading, below the verdict, because that is what a
        # note *is*: a report cannot move the exit code, so printing one among
        # the problems would mean a reader could not tell from the page which
        # line failed their CI.
        report = "\n".join([report, "Notes:", *(f"- {n}" for n in notes), ""])

    print(report)
    return EXIT_FAILURE if problems or not verdict.ok else EXIT_OK


def cmd_graph(args: argparse.Namespace) -> int:
    """Mermaid **text**, on stdout. Never `draw_mermaid_png()`, which would post
    the user's graph to a third-party API.

    Drawing-only in both senses: no model is built (`_drawing_only_model`) and
    no state file is opened (`_ephemeral_state`). It compiles a graph it will
    never invoke, so it wrote both a checkpoint database and a memory database
    beside the package it was asked to draw — `organisms-first-class` 77."""
    print(_load(args, model=_drawing_only_model(), ephemeral=True).mermaid(xray=args.xray))
    return EXIT_OK


def cmd_export_plugin(args: argparse.Namespace) -> int:
    """`export_plugin` + `write_export` — the pair `GET /api/workflows/{slug}/
    plugin-export` already calls, with the write the GET deliberately does not do.

    The positional is a **package path**, as it is for every other command here,
    not the slug the two hosted doors take. Both are the same identity — the
    slug *is* the directory name, and `export_plugin` reads it from there — and
    a slug is a name the user never chose, so the CLI keeps asking for the one
    thing they did choose: where the package is.

    The two refusals are argument checks, not behaviour: a directory with no
    `workflow.json` is not a package (the seam would happily render a
    convincing bundle of nothing), and a destination that already holds files
    is somebody else's directory (`write_export` merges into what it finds,
    which is right for a library call and wrong for a command).
    """
    from openstategraph.plugin_interop import export_plugin, write_export

    package = Path(args.package).expanduser().resolve()
    if not (package / "workflow.json").is_file():
        return _error(f"no workflow.json in {package} — is that a workflow package?")
    destination = (
        Path(args.out).expanduser().resolve()
        if args.out
        else Path.cwd().resolve() / package.name
    )
    if destination.exists() and any(destination.iterdir()):
        return _error(f"{destination} already has files in it — name an empty --out")

    export = export_plugin(package)
    written = write_export(export, destination)
    for note in export.notes:
        print(f"note: {note}", file=sys.stderr)
    print(f"plugin exported: {written}")
    return EXIT_OK


def _write_root(args: argparse.Namespace) -> Path:
    """Where a command that *creates* a package puts it (install-experience T5).

    `--root` first, because it is the explicit argument the project-wide
    precedence rule already puts at the top; otherwise the same question every
    reader asks, answered by the same function — `workflows_root()`.

    Until this, `new` and `examples copy` each spelled
    `Path.cwd() / "workflows"` instead. So in a project with `workflows_dir:`
    set, or with `OPENSTATEGRAPH_WORKFLOWS_ROOT` exported, the first thing an
    adopter scaffolded landed where `serve` does not look, and the product
    answered *"No workflows exist yet."* with their package right there — the
    exact failure `workflows_root.py` exists to have ended, reintroduced by the
    two commands that create things.
    """
    from openstategraph.workflows_root import workflows_root

    if getattr(args, "root", None):
        return Path(args.root).expanduser().resolve()
    return workflows_root()


def cmd_new(args: argparse.Namespace) -> int:
    """`openstategraph.scaffold` — the same function `scripts/new_workflow.py`
    calls, so the two can never produce different packages.

    `--template` is validated by argparse's `choices` (exit 2, valid names in
    the message), so nothing here re-checks it. `--team` predates templates and
    keeps working as an alias with a one-line notice; removing it would break
    every script and README line that already uses it, for a flag whose whole
    cost is this branch.
    """
    from openstategraph.scaffold import ScaffoldError, new_package

    if args.list_templates:
        width = max(len(name) for name in templates.names())
        for entry in templates.catalogue():
            default = "  (default)" if entry.name == templates.DEFAULT_TEMPLATE else ""
            print(f"{entry.name.ljust(width)}  {entry.summary}{default}")
        return EXIT_OK

    if not args.slug:
        return _usage("new needs a slug: openstategraph new my-flow [--template NAME]")
    if args.team and args.template not in (None, "team"):
        return _usage(f"--team and --template {args.template} ask for different templates")
    if args.team:
        print("note: --team is deprecated; use --template team", file=sys.stderr)

    template = args.template or ("team" if args.team else templates.DEFAULT_TEMPLATE)
    root = _write_root(args)
    try:
        target = new_package(root, args.slug, template=template, name=args.name)
    except ScaffoldError as exc:
        return _error(str(exc))
    print(f"{template} package created: {target}")
    return EXIT_OK


def cmd_init(args: argparse.Namespace) -> int:
    """`openstategraph init [dir]` — the one command that creates a project.

    install-experience T6. `pip install openstategraph[directory:'my_demo']`
    is not a thing pip can parse, so the directory a user wants to name is
    named here. Nothing creates a project implicitly: `serve` in an
    unconfigured directory prints what to run rather than scattering a
    `workflows/` folder somewhere nobody chose.

    It is also where story one is first *shown* — the extra chose the vendor,
    the key is the only thing left, and the message names it.
    """
    from openstategraph.config_file import reset_active_config
    from openstategraph.providers import provider_catalogue
    from openstategraph.scaffold import ScaffoldError, init_project

    label = args.directory or "."
    try:
        result = init_project(
            label,
            label=label,
            workflows_dir=args.workflows_dir,
            force=args.force,
            starter=not args.empty,
        )
    except ScaffoldError as exc:
        return _error(str(exc))

    if result.reused_empty:
        print(f"{label}/ exists and is empty — using it")

    def state(path: Path) -> str:
        return "" if path in result.created else "   (already there — left alone)"

    print(f"created {result.directory}{os.sep}")
    print(f"  {result.config.name:<22}  workflows_dir: {args.workflows_dir}{state(result.config)}")
    print(f"  {'.gitignore':<22}  .env, .openstategraph/{state(result.gitignore)}")
    if result.starter is not None:
        where = f"{args.workflows_dir}/{result.starter.name}/"
        print(f"  {where:<22}  the smallest workflow that runs{state(result.starter)}")
    print()

    # The generated config was written before this process had any chance to
    # read one; the project it just made is the project the rest of this
    # command should be describing.
    reset_active_config()
    default = provider_catalogue().elected_default()
    print(
        textwrap.fill(
            f"default model: {default.model or '(none)'} — {default.reason}",
            width=88,
            subsequent_indent=" " * 15,
        )
    )
    print()
    print("no .env was written — a generated credential file is a committed one waiting")
    print(f"to happen. Create {label}/.env yourself; .gitignore already covers it:")
    for spec in provider_catalogue().list():
        for variable in spec.env_vars:
            print(f"  {variable}=")
    print("  (openstategraph env-example prints the full block, names only)")
    print()
    print("next:")
    if label != ".":
        print(f"  cd {label}")
    print("  openstategraph serve --open")
    if result.starter is not None:
        print(f'  openstategraph run {args.workflows_dir}/{result.starter.name} "hello"')
    return EXIT_OK


def cmd_examples_list(args: argparse.Namespace) -> int:
    """The shipped gallery — `openstategraph.examples`, printed.

    The same catalogue the editor's Examples shelf reads over
    `GET /api/examples`, so the two can never offer different galleries.
    """
    from openstategraph import examples

    width = max(len(slug) for slug in examples.slugs())
    for example in examples.catalogue():
        extra = len(example.requires()) - 1
        also = f"  [+{extra} mounted]" if extra else ""
        print(f"{example.slug.ljust(width)}  {example.pattern}{also}")
        print(f"{' ' * width}  {example.summary}")
        # The claim and the contents, together (`every-workflow-green` 03).
        # `summary` is `settings.purpose` — prose a person wrote once, which
        # nothing reads back against the graph, and which was found advertising
        # a classifier, a grader and a human gate on a document that had none.
        # The owner's decision was to show the shape beside the sentence rather
        # than police it: the reader sees both and judges.
        if example.shape:
            print(f"{' ' * width}  {example.shape}")
    return EXIT_OK


#: Said after every copy, because every shipped example carries
#: `published: false` (production-ready 55.2).
#:
#: The flag is not a mistake to fix in the gallery: publishing is a decision
#: about *your* package on *your* deployment, and a copy that published itself
#: would put a stranger's workflow on a customer surface without anybody
#: choosing it. What was wrong was the silence — `Workflows.published()` and the
#: `/chat` picker skip the fresh copy, and nothing said why.
_DRAFT_AFTER_COPY = (
    "a copy arrives as a draft: `published: false`, so `Workflows.published()` and "
    "the /chat picker skip it until you publish it — the editor's Workflows panel, "
    'or `"published": true` in its workflow.json. `Workflows.list()` shows it either way.'
)


def _say_it_is_a_draft() -> None:
    print(textwrap.fill(_DRAFT_AFTER_COPY, width=88, break_on_hyphens=False))


def cmd_examples_copy(args: argparse.Namespace) -> int:
    """`scaffold.copy_example` — the copy that severs it.

    An example is not mounted where it lies (it lies in `site-packages`); it is
    copied into the caller's own workflows directory and is theirs from then
    on. `openstategraph.examples` explains why that is the only honest option.
    """
    from openstategraph import examples
    from openstategraph.scaffold import ScaffoldError, copy_example

    if args.all and args.slug:
        return _usage(f"copy {args.slug} or copy --all, not both — they ask for different things")
    if not args.all and not args.slug:
        return _usage("examples copy needs a slug, or --all (see `openstategraph examples list`)")
    if args.all:
        return _copy_every_example(args)

    root = _write_root(args)
    try:
        written = copy_example(root, args.slug)
    except examples.UnknownExampleError as exc:
        return _usage(str(exc))
    except ScaffoldError as exc:
        return _error(str(exc))

    if written[0] in written.kept:
        print(f"{args.slug} already yours, unchanged — kept: {written[0]}")
    else:
        print(f"{args.slug} copied: {written[0]}")
    for path in written[1:]:
        if path in written.kept:
            print(f"  already yours, unchanged — kept: {path.name}")
        else:
            print(f"  also copied (it is mounted): {path.name}")
    _say_it_is_a_draft()
    print(f'next: openstategraph run {written[0]} "your question"')
    return EXIT_OK


def _copy_every_example(args: argparse.Namespace) -> int:
    """`examples copy --all` — install-experience T8.

    There is no `eject` verb, and there will not be one: `examples copy` is
    already eject semantics — take a finished package out of the wheel into
    your project, severed — and a second word for one act is the defect
    CLAUDE.md carries two worked cases of. What the story genuinely asked for
    and did not exist is the *plural*, and this is it.

    The size and count preamble prints **before** the writer is called, so a
    1 MB database is announced rather than discovered.
    """
    from openstategraph.scaffold import ScaffoldError, copy_all_examples, gallery_footprint

    root = _write_root(args)
    footprint = gallery_footprint()
    print(
        textwrap.fill(
            f"this copies all {footprint.packages} examples into {root} — about "
            f"{footprint.human}, of which {footprint.largest_name} is "
            f"{footprint.largest_human}.",
            width=88,
            break_on_hyphens=False,
        )
    )

    try:
        written = copy_all_examples(root)
    except ScaffoldError as exc:
        return _error(str(exc))

    print(f"copied {len(written)} examples into {root}")
    print(
        textwrap.fill(
            ", ".join(path.name for path in written),
            width=88,
            initial_indent="  ",
            subsequent_indent="  ",
            break_on_hyphens=False,
        )
    )
    _say_it_is_a_draft()
    print(f'next: openstategraph run {written[0]} "your question"')
    return EXIT_OK


def cmd_knowledge_build(args: argparse.Namespace) -> int:
    """`api.knowledge_build.run_build` — the same path the editor's button uses."""
    from openstategraph.api.knowledge_build import (
        UnknownSourceError,
        resolve_build_model,
        run_build,
    )
    from openstategraph.schema import normalize_document

    package = Path(args.package).expanduser().resolve()
    manifest = package / "workflow.json"
    if not manifest.is_file():
        return _error(f"no workflow.json in {package} — is that a workflow package?")

    document = normalize_document(json.loads(manifest.read_text()))
    try:
        report = run_build(
            package,
            document,
            resolve_build_model(args.model, None),
            package.parent,
            source=args.source,
            instruction=args.instruction,
        )
    except UnknownSourceError as exc:
        return _error(str(exc))

    for label in ("written", "skipped", "collisions", "warnings"):
        values = report.get(label) or []
        print(f"{label}: {', '.join(values) if values else 'none'}")
    return EXIT_OK


def cmd_knowledge_list(args: argparse.Namespace) -> int:
    """The free index tier: every topic, the hint that IS its first line, and
    who owns it.

    Two lines per store were previously invisible from a terminal: **who wrote
    a doc** and **whether its source has moved since**. Both are recorded on
    disk — the generated marker names the owning builder and stamps a hash of
    the brief, and a claimed doc keeps that hash in a trailing comment — and
    both were only ever surfaced by the editor's curation panel. A developer
    checking their second brain is right does it from a terminal, so this
    reads the same `knowledge_curation.list_topics` the panel does.

    `--knowledge-dir` falls back to the plain index: a store outside the
    package has no `workflow.json` to recompute briefs from, so ownership is
    still readable but staleness is genuinely unknowable — and unknown is not
    stale.

    **An absent store is not an empty one.** Every path below that cannot
    exist says so and fails, because the alternative — the shared "no
    knowledge topics — build them with…" line — answers a typo'd path with
    advice to rebuild into a directory that is not there. Three distinct
    answers, three distinct messages: no such package, not a workflow package,
    and a real store that happens to be empty.
    """
    package = Path(args.package).expanduser().resolve()
    override = getattr(args, "knowledge_dir", None)
    if override is not None:
        store = Path(override).expanduser().resolve()
        if not store.is_dir():
            return _error(f"no such knowledge directory: {store}")
    elif not package.is_dir():
        return _error(f"no such package: {package}")
    elif not (package / "workflow.json").is_file() and not (package / "knowledge").is_dir():
        # `knowledge build`'s wording, because it is the same question.
        return _error(f"no workflow.json in {package} — is that a workflow package?")
    if override is not None or not (package / "workflow.json").is_file():
        from openstategraph.knowledge import PackageKnowledge

        entries = [
            (e.name, e.hint, "") for e in PackageKnowledge(package, knowledge_dir=override).topics()
        ]
    else:
        from openstategraph.api import knowledge_curation
        from openstategraph.schema import normalize_document

        document = normalize_document(json.loads((package / "workflow.json").read_text()))
        entries = [
            (
                s.name,
                s.hint,
                (f"generated: {s.source}" if s.generated else "yours")
                + (", STALE" if s.stale else ""),
            )
            for s in knowledge_curation.list_topics(package, document, package.parent)
        ]
    if not entries:
        print("no knowledge topics — build them with: openstategraph knowledge build <package>")
        return EXIT_OK
    for name, hint, badge in entries:
        line = f"- {name} — {hint}" if hint else f"- {name}"
        print(f"{line}  [{badge}]" if badge else line)
    return EXIT_OK


def _thread_savers(args: argparse.Namespace) -> tuple[Any, Any]:
    """`(services, savers)` — the same assembly the HTTP transport uses.

    No new logic here, per the rules at the top of this file: the CLI opens
    the checkpointer the server would have opened and asks
    `api.threads` the same two questions the endpoints ask it.
    """
    from openstategraph.api.services import WorkflowServices
    from openstategraph.api import threads as thread_queries

    services = WorkflowServices(getattr(args, "workflows_root", None))
    return services, thread_queries.savers_for(services, getattr(args, "workflow", None))


def cmd_threads_list(args: argparse.Namespace) -> int:
    """Past runs this deployment stored — read from the checkpointer, not a log."""
    from openstategraph.api import threads as thread_queries

    services, savers = _thread_savers(args)
    try:
        rows = thread_queries.list_threads(
            savers,
            workflow_slug=args.workflow,
            user_email=args.user,
            session_id=args.session,
            limit=args.limit,
        )
    finally:
        services.close()

    if args.json:
        print(json.dumps([row.model_dump() for row in rows], indent=2))
        return EXIT_OK
    if not rows:
        print("no stored runs — the checkpointer has no threads yet")
        return EXIT_OK
    for row in rows:
        who = row.user_email or "anonymous"
        # `status` says whether the run is waiting on the user; `failed` is a
        # separate fact — a node wrote the failure sentinel into `outputs` —
        # and it is shown alongside status rather than folded into it, so a
        # run that failed but finished still reads "finished" and additionally
        # "failed" (production-ready/78).
        label = f"{row.status} failed" if row.failed else row.status
        print(
            f"{row.thread_id}  {row.updated_at}  {label:15}  "
            f"{row.workflow_slug or '-'}  {who}  {row.question[:60]}"
        )
    # A footer, not a column: `list` is read by scanning, and a resume line
    # per row would turn a table into a wall of text. `threads show
    # <thread-id>` is where the actual payload and the copy-pasteable command
    # live — this only says that a next step exists (`workflow-gallery` 76).
    paused = [row.thread_id for row in rows if row.status == "paused"]
    if paused:
        plural = "s" if len(paused) != 1 else ""
        print(
            f"\n{len(paused)} thread{plural} paused — "
            "`openstategraph threads show <thread-id>` says what each is waiting for"
        )
    return EXIT_OK


def cmd_threads_show(args: argparse.Namespace) -> int:
    """One past run, read back. A **view**: nothing is executed again.

    Continuing a paused run is a different act with a different name —
    `openstategraph resume`, or `POST /api/runs/resume` — and it does call
    models and tools. Printing what already happened does not. (`run
    --thread-id` is a third thing again: it starts a *new* turn on the same
    conversation, and it has never been able to answer an `interrupt()`.)
    """
    from openstategraph.api import threads as thread_queries

    services, savers = _thread_savers(args)
    try:
        history = thread_queries.read_thread(savers, args.thread_id)
    finally:
        services.close()

    if history is None:
        return _error(f"no stored run for thread {args.thread_id!r}")
    if args.json:
        print(json.dumps(history.model_dump(), indent=2))
        return EXIT_OK

    thread = history.thread
    status_line = f"{thread.status} — failed" if thread.failed else thread.status
    print(f"thread {thread.thread_id} — {status_line}")
    print(f"  workflow: {thread.workflow_slug or '-'}")
    print(f"  user:     {thread.user_email or 'anonymous'}")
    print(f"  session:  {thread.session_id or '-'}")
    print(f"  updated:  {thread.updated_at}")
    print("  (a recording, not a re-run — no model or tool was called to show this)")
    if thread.status == "paused":
        for line in _thread_pause_lines(services, thread):
            print(f"  {line}")
    for step in history.steps:
        print(f"\nstep {step.step} ({step.source}) {step.at}")
        for key, value in step.values.items():
            if not value:
                continue
            print(f"  {key}: {value}")
    return EXIT_OK


def _thread_pause_lines(services: Any, thread: Any) -> list[str]:
    """What a paused thread read back from `threads show` has to say.

    `thread.pause` is the payload `_pause_payload` read off the checkpoint's
    pending `__interrupt__` write — the same fact `run`'s own pause report
    prints, from the same field a live run leaves behind. This is the surface
    that answers `workflow-gallery` 76: a reviewer who did not start the run
    reads `threads show` a day later and this is where they learn what the
    gate is asking and the exact command that answers it.

    The resume line names a package, a thread and a decision, and `threads
    show` only ever knew the *slug* — so before promising a copy-pasteable
    line this resolves the slug to the package directory the same way the
    store resolves any slug, and says plainly when it cannot: an unset or
    invalid slug is not a package path, and `CLAUDE.md`'s law is not to
    promise which is not possible.
    """
    lines: list[str] = []
    pause = thread.pause or {}
    message = str(pause.get("message") or "").strip()
    lines.append(f"waiting: {message or 'a decision is needed'}")
    candidate = str(pause.get("candidate") or "").strip()
    if candidate:
        lines.append(f"candidate: {candidate}")
    package = _package_directory(services, thread.workflow_slug)
    if package is not None:
        lines.append(f"finish it: {resume_command_line(str(package), thread.thread_id)}")
    else:
        lines.append(
            "finish it: openstategraph resume <package> "
            f"{thread.thread_id} --approve | --reject --feedback '…'  "
            "(this thread's workflow slug is unknown, so the exact package "
            "path above is a placeholder — point it at the package yourself)"
        )
    return lines


def _package_directory(services: Any, slug: str) -> Any:
    """The package directory a stored thread's slug names, or `None`.

    `None` covers both an empty slug (an older or unlabelled thread) and one
    the store refuses — `WorkflowStore.directory_for` validates the slug
    shape before resolving it, which is the same check `resume`'s own loader
    ultimately relies on, so a slug this rejects would not have loaded either.
    """
    from openstategraph.api.workflow_store import InvalidSlugError

    if not slug:
        return None
    try:
        return services.store.directory_for(slug)
    except InvalidSlugError:
        return None


def no_provider_warning() -> str | None:
    """One line when this install can serve the product and run none of it.

    Workflow-gallery ticket 37: `[server]` is fastapi, uvicorn and sqlite, and
    contains no provider integration — a defensible boundary (folding one in
    would choose a vendor for everyone) that was, until this, **invisible
    until the first Run button**. The knowledge to say so already existed:
    `openstategraph providers` prints the extra per provider, so this asks the
    same catalogue rather than hard-coding a list.

    `None` when *any* provider integration is importable. The threshold is
    deliberately "none at all" rather than "not the one this document names":
    a serve command has no document in front of it, and a warning that fired
    for an Anthropic-only install serving an Ollama example would fire on
    every correct install too.

    The sentence itself belongs to the catalogue
    (`ProviderCatalogue.no_provider_message`), because three surfaces print it
    — this warning, the `default:` line of `openstategraph providers`, and
    `resolve_model`'s `NoProviderInstalled` — and three copies of a sentence
    is three chances to fix two of them.
    """
    from openstategraph.providers import ProviderEnvironment, provider_catalogue

    catalogue = provider_catalogue()
    specs = catalogue.list()
    if not specs or any(ProviderEnvironment(spec).is_installed() for spec in specs):
        return None
    return catalogue.no_provider_message()


def startup_facts() -> list[str]:
    """What Run will actually do, in two lines, before anything is bound.

    The two questions a reader has when a server they just started shows them
    an editor: *which model will this call*, and *where are my workflows*. Both
    were answerable only by reading source or by pressing Run and finding out
    (install-experience T3).

    A function rather than four `print`s inside `cmd_serve`, for the reason the
    header of this file gives: a command is argument handling plus a call, and
    a block of formatting inside one is a block of formatting no test reaches
    without binding a socket.

    Never raises. `resolve_model` refuses an install with no provider, which is
    correct for a run and wrong here — `serve` is expected to start on a bare
    install and say what will happen, and `no_provider_warning` has already
    said the rest.
    """
    from openstategraph.providers import provider_catalogue
    from openstategraph.workflows_root import workflows_root

    default = provider_catalogue().elected_default()
    return [
        f"default model  {default.model or '(none)'}",
        f"workflows      {workflows_root()}",
    ]


def cmd_serve(args: argparse.Namespace) -> int:
    """The whole product on one origin: editor at `/`, chat at `/chat`, API
    under `/api`. Requires the `[server]` extra.

    Two collaborators do the work — `api.listening` decides the port and binds
    it, `api.editor_assets` decides where the built editor comes from — so this
    stays argument handling plus a call, per the rules at the top of the file.

    The socket is bound here and handed to uvicorn rather than passing it a
    number, because that is the only way `--port 0` can print the URL it landed
    on *before* the server starts talking.

    Five things are said before anything is bound (scale-and-adopt ticket 06,
    workflow-gallery tickets 37 and 40, production-ready 60), because a message
    printed after a server is listening is a message someone scrolls past: more
    than one worker is refused outright, a second process pointed at a state
    directory another server already holds is refused by name, an
    unauthenticated bind to a non-loopback address is warned about by name, an
    install with no provider integration is told that every run will fail, and
    — in a checkout only — an editor built before the last `src/` change says
    so, because this process serves `dist/` and the dev server on 5273 does
    not.

    **The state-directory lock is checked twice, on purpose.** The
    authoritative lock still lives in the FastAPI lifespan
    (`api/main.py:single_server_lifespan`) — it has to, because the resources
    it guards (the checkpointer, the memory store, the `/api/events`
    fan-out) are constructed there, and hoisting *that* setup ahead of the
    socket bind would be a much larger, riskier change for a message-ordering
    fix. What moves here is only the cheap part: `SingleServerLock.acquire()`
    is a non-blocking `flock` on a small file, with no sqlite or FastAPI
    involved, so it costs nothing to ask early and release immediately if it
    succeeds. A `serve` that fails this early check never reaches
    `bind_listener` and never prints a URL it cannot honour (workflow-gallery
    40). A `serve` that passes it can still be refused by the lifespan's own
    acquire a moment later — another process could win the race in between —
    and that refusal still reaches `AnotherServerIsRunning`'s full message on
    stderr; it is simply no longer the *only* place the check happens, so the
    common case (a second `serve` started well after the first) is caught
    before the URLs print instead of after.
    """
    from openstategraph import deployment

    refusal = deployment.check_worker_count(explicit=getattr(args, "workers", None))
    if refusal is not None:
        return _error(refusal)

    try:
        import uvicorn
    except ImportError:
        return _missing("uvicorn", "server", "the HTTP API")

    from openstategraph.state_dir import state_dir
    from openstategraph.workflows_root import workflows_root

    lock = deployment.SingleServerLock(state_dir(workflows_root()))
    try:
        lock.acquire()
    except deployment.AnotherServerIsRunning as exc:
        return _error(str(exc))
    else:
        # Only a fast fail-early check: release immediately so the lifespan's
        # own acquire (the one that actually owns the resource for the life of
        # the process) is the sole long-lived holder.
        lock.release()

    from openstategraph.api import auth
    from openstategraph.api.listening import PortUnavailable, bind_listener, listen_urls

    exposure = auth.exposure_warning(args.host)
    if exposure is not None:
        print(exposure, file=sys.stderr, flush=True)

    # A fourth thing, and it is said here for the reason the other three are:
    # a message printed after a server is listening is a message somebody
    # scrolls past. This one is silent for every installed user, because
    # `editor_is_stale` returns `None` when there is no `src/` to compare
    # against (production-ready 60).
    from openstategraph.editor_freshness import warn_if_stale

    stale = warn_if_stale()
    if stale is not None:
        print(stale, file=sys.stderr, flush=True)

    # The third thing said before anything is bound, and the same rule: the
    # documented install carries a provider extra, and an install that lost it
    # must not discover that fact one Run button at a time (ticket 37).
    providers = no_provider_warning()
    if providers is not None:
        print(providers, file=sys.stderr, flush=True)

    # …and the two facts that answer "what will Run actually do". Not a
    # warning, so stdout; `flush` for the reason the URLs below flush.
    for fact in startup_facts():
        print(fact, flush=True)

    try:
        listener = bind_listener(args.host, args.port)
    except PortUnavailable as exc:
        return _error(str(exc))

    # `serve` means "open the product", so the editor is served. `setdefault`
    # rather than assignment: OPENSTATEGRAPH_SERVE_STATIC=0 in the environment
    # is somebody deliberately asking for an API-only process, and that is
    # theirs to ask for.
    os.environ.setdefault("OPENSTATEGRAPH_SERVE_STATIC", "1")

    port = int(listener.getsockname()[1])
    urls = listen_urls(args.host, port)
    # The last thing printed before uvicorn's own output, and the reason
    # anyone ran the command: where to click.
    #
    # `flush=True` is load-bearing, not decoration. stdout is block-buffered
    # whenever it is not a terminal — a log file, a pipe, a supervisor — and
    # `Server.run` then blocks forever with these lines still in the buffer.
    # The one thing a script waits for is the URL, and it never arrived.
    for label, url in urls.items():
        print(f"{label:<7} {url}", flush=True)

    if args.open:
        import webbrowser

        # Safe before the loop starts: the socket is already listening, so the
        # browser's connection queues rather than being refused.
        webbrowser.open(urls["editor"])

    uvicorn.Server(uvicorn.Config("openstategraph.api.main:app", host=args.host, port=port)).run(
        sockets=[listener]
    )
    return EXIT_OK


def cmd_mcp(args: argparse.Namespace) -> int:
    """The MCP transport. Requires the `[mcp]` extra.

    `--transport` sets `OPENSTATEGRAPH_MCP_TRANSPORT` rather than replacing it:
    the environment variable is the shipped interface and keeps working.
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        return _missing("mcp", "mcp", "the MCP transport")

    if args.transport:
        os.environ["OPENSTATEGRAPH_MCP_TRANSPORT"] = args.transport
    from openstategraph.mcp_server import main as mcp_main

    mcp_main()
    return EXIT_OK


def _missing(module: str, extra: str, why: str) -> int:
    from openstategraph._extras import install_hint

    print(f"{module} is required for {why} — {install_hint(extra)}", file=sys.stderr)
    return EXIT_MISSING_EXTRA


# --------------------------------------------------------------------------
# parsing


def build_parser() -> argparse.ArgumentParser:
    from openstategraph import __version__

    parser = argparse.ArgumentParser(
        prog="openstategraph",
        description="Compile and run OpenStateGraph workflow packages.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="ask a workflow package a question")
    run.add_argument("package", help="the folder holding workflow.json")
    run.add_argument("question")
    run.add_argument("--model", help="a model string, e.g. ollama:gpt-oss:120b-cloud")
    run.add_argument("--trace-file", dest="trace_file", help="append one JSON line per run")
    run.add_argument("--thread-id", dest="thread_id", help="continue an earlier conversation")
    run.add_argument("--knowledge-dir", dest="knowledge_dir", help="override <package>/knowledge")
    # Repeatable, and typed by the document rather than guessed from the
    # literal: a command line carries strings, and guessing would make
    # `caseId=00123` a number for one workflow and a string for the next.
    run.add_argument(
        "--context",
        action="append",
        metavar="KEY=VALUE",
        help="a run context value the workflow declares; repeat for more than one",
    )
    run.add_argument("--json", action="store_true", help="print the whole result, not the answer")
    run.set_defaults(handler=cmd_run)

    resume = subparsers.add_parser(
        "resume", help="answer an approval a run is paused on, and let it finish"
    )
    resume.add_argument("package", help="the folder holding workflow.json")
    resume.add_argument("thread_id", help="the paused thread — `threads list` names it")
    # Required and mutually exclusive: argparse refuses "neither" and "both"
    # with exit 2 on its own, which is the contract, and no code path here can
    # ever assume a decision nobody typed.
    verdict = resume.add_mutually_exclusive_group(required=True)
    verdict.add_argument("--approve", action="store_true", help="let it through")
    verdict.add_argument("--reject", action="store_true", help="send it back")
    resume.add_argument(
        "--feedback", help="what to change — a note on a rejection, read as the spec"
    )
    resume.add_argument("--model", help="a model string, e.g. ollama:gpt-oss:120b-cloud")
    resume.add_argument("--trace-file", dest="trace_file", help="append one JSON line per run")
    resume.add_argument("--knowledge-dir", dest="knowledge_dir", help="override <package>/knowledge")
    resume.add_argument("--json", action="store_true", help="print the whole result, not the answer")
    resume.set_defaults(handler=cmd_resume)

    evaluate = subparsers.add_parser(
        "eval", help="grade a package against its golden dataset (runs a model)"
    )
    evaluate.add_argument("package", help="the folder holding workflow.json")
    evaluate.add_argument(
        "--dataset", help="a *.eval.json file (default: the one in <package>/evals)"
    )
    evaluate.add_argument("--limit", type=int, help="grade only the first N cases")
    evaluate.add_argument("--model", help="a model string, e.g. ollama:gpt-oss:120b-cloud")
    evaluate.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help=(
            "exit 1 when overall accuracy is below this (0..1). Default 0, i.e. "
            "report but do not gate; set it in CI to the number you will defend."
        ),
    )
    evaluate.add_argument("--json", action="store_true", help="print the scorecard as JSON")
    evaluate.set_defaults(handler=cmd_eval)

    validate = subparsers.add_parser("validate", help="compile-check a package or a document")
    validate.add_argument("target", help="a workflow package folder, or a workflow.json file")
    validate.set_defaults(handler=cmd_validate)

    graph = subparsers.add_parser("graph", help="print the compiled topology as Mermaid text")
    graph.add_argument("package")
    graph.add_argument("--model")
    graph.add_argument(
        "--xray",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "expand LangGraph subgraph internals (default: on). A no-op today "
            "— nothing this compiler emits is one; see CompiledWorkflow.mermaid"
        ),
    )
    graph.set_defaults(handler=cmd_graph)

    # The only command that creates a project, and the substitute for the one
    # thing the install line cannot carry — see `cmd_init`.
    init = subparsers.add_parser(
        "init", help="make a directory an OpenStateGraph project (default: this one)"
    )
    init.add_argument(
        "directory",
        nargs="?",
        help="the project directory, yours to name (default: the current one)",
    )
    init.add_argument(
        "--workflows-dir",
        dest="workflows_dir",
        default="workflows",
        help="what to call the packages folder inside it (default: workflows)",
    )
    init.add_argument(
        "--empty",
        action="store_true",
        help="skip workflows/starter/, for a repository that already has packages",
    )
    # A flag, not a prompt: exit codes are this CLI's API for CI, and a command
    # that blocks on stdin hangs a CI job. It is named inside the refusal it
    # answers, so it is never something to go and look up.
    init.add_argument(
        "--force",
        action="store_true",
        help="use a directory that already has things in it; overwrites nothing",
    )
    init.set_defaults(handler=cmd_init)

    new = subparsers.add_parser("new", help="scaffold a workflow package from a template")
    # Optional so `--list-templates` can stand alone; `cmd_new` supplies the
    # usage error argparse would otherwise give, with the same exit code.
    new.add_argument("slug", nargs="?", help="lowercase letters, digits and hyphens")
    new.add_argument("name", nargs="?", help="display name (default: derived from the slug)")
    # `choices` on purpose: argparse then rejects an unknown template with exit
    # 2 and the valid names, which is exactly the contract, without this module
    # growing a second copy of the catalogue to validate against.
    new.add_argument(
        "--template",
        choices=templates.names(),
        help=f"starting point (default: {templates.DEFAULT_TEMPLATE}); see --list-templates",
    )
    new.add_argument(
        "--list-templates",
        action="store_true",
        help="print the templates and what each is for, then exit",
    )
    new.add_argument(
        "--team",
        action="store_true",
        help="deprecated alias for --template team",
    )
    new.add_argument("--root", help="where to create it (default: the project's workflows root)")
    new.set_defaults(handler=cmd_new)

    # The gallery ships in the wheel as package data (gallery ticket 07) and is
    # deliberately NOT under the workflows root, so it needs a command of its
    # own rather than another `--template`: a template is rendered, an example
    # is copied whole — tests, knowledge, database and all.
    example_group = subparsers.add_parser(
        "examples", help="the worked examples that ship with OpenStateGraph"
    )
    # Not `required=True`: the bare verb lists (production-ready 55.1). The
    # top-level help offers `examples` as "the worked examples that ship with
    # OpenStateGraph", so the bare word is what a newcomer types first, and an
    # argparse usage error is a poor answer in a product whose complaint is
    # that nobody knows the examples exist. Listing costs nothing and writes
    # nothing, so it is the only subcommand safe to assume.
    example_group.set_defaults(handler=cmd_examples_list)
    example_commands = example_group.add_subparsers(dest="examples_command")

    example_list = example_commands.add_parser(
        "list", help="print the examples and what each one demonstrates"
    )
    example_list.set_defaults(handler=cmd_examples_list)

    example_copy = example_commands.add_parser(
        "copy", help="copy one into your workflows directory, mounts included"
    )
    # No `choices`: the gallery has more entries than argparse should print on
    # every usage error, and it grows. `examples.get` raises with the list.
    # (This comment said "twenty-one" for as long as there were twenty-three.)
    # Optional so `--all` can stand alone; `cmd_examples_copy` supplies the
    # usage error argparse would otherwise give, with the same exit code.
    example_copy.add_argument("slug", nargs="?", help="see `openstategraph examples list`")
    example_copy.add_argument(
        "--all",
        action="store_true",
        help="copy every example, all-or-nothing; prints the size first",
    )
    example_copy.add_argument(
        "--root", help="where to copy it (default: the project's workflows root)"
    )
    example_copy.set_defaults(handler=cmd_examples_copy)

    export_group = subparsers.add_parser(
        "export", help="write this package out in somebody else's format"
    )
    # `required=True`, unlike `examples`: every leaf here writes a directory,
    # so there is no safe thing for the bare verb to assume.
    export_commands = export_group.add_subparsers(dest="export_command", required=True)

    export_plugin_cmd = export_commands.add_parser(
        "plugin", help="write an Agent Plugins v1 bundle (what the HTTP door previews)"
    )
    export_plugin_cmd.add_argument("package", help="the folder holding workflow.json")
    export_plugin_cmd.add_argument(
        "--out", help="where to write the bundle (default: ./<the package's folder name>)"
    )
    export_plugin_cmd.set_defaults(handler=cmd_export_plugin)

    threads = subparsers.add_parser("threads", help="past runs stored by the checkpointer")
    thread_commands = threads.add_subparsers(dest="threads_command", required=True)

    thread_list = thread_commands.add_parser("list", help="list past runs, newest first")
    thread_list.add_argument("--workflow", help="only this workflow slug")
    thread_list.add_argument("--user", help="only this user_email (case-insensitive)")
    thread_list.add_argument("--session", help="only this session_id")
    thread_list.add_argument("--limit", type=int, default=25)
    thread_list.add_argument("--workflows-root", dest="workflows_root")
    thread_list.add_argument("--json", action="store_true")
    thread_list.set_defaults(handler=cmd_threads_list)

    thread_show = thread_commands.add_parser(
        "show", help="print one past run, checkpoint by checkpoint (does not re-run it)"
    )
    thread_show.add_argument("thread_id")
    thread_show.add_argument("--workflow", help="the slug, if it keeps its own checkpoint file")
    thread_show.add_argument("--workflows-root", dest="workflows_root")
    thread_show.add_argument("--json", action="store_true")
    thread_show.set_defaults(handler=cmd_threads_show)

    knowledge = subparsers.add_parser("knowledge", help="the package's second brain")
    knowledge_commands = knowledge.add_subparsers(dest="knowledge_command", required=True)

    build = knowledge_commands.add_parser("build", help="generate knowledge docs")
    build.add_argument("package")
    build.add_argument("--source", help="one builder's source_kind (default: every one that finds)")
    build.add_argument("--instruction", help="steering text for the agentic builder")
    build.add_argument("--model")
    build.set_defaults(handler=cmd_knowledge_build)

    listing = knowledge_commands.add_parser("list", help="topics and their index hints")
    listing.add_argument("package")
    listing.add_argument("--knowledge-dir", dest="knowledge_dir")
    listing.set_defaults(handler=cmd_knowledge_list)

    serve = subparsers.add_parser(
        "serve",
        help="run the editor, the chat surface and the API (needs [server] plus a provider extra)",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "bind address (default: 127.0.0.1, this machine only). Not 0.0.0.0: "
            "this process holds your provider API keys and has no authentication, "
            "so exposing it to the network exposes those. Use 0.0.0.0 only behind "
            "something that authenticates."
        ),
    )
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "exactly this port, failing if it is taken. Omit to take 8000, or the "
            "next free port if 8000 is busy. Use 0 to let the OS choose."
        ),
    )
    serve.add_argument(
        "--open",
        action="store_true",
        help="open the editor in your browser once it is listening (default: off)",
    )
    # Accepted only so it can be REFUSED by name. Without the flag, argparse
    # answers `--workers 4` with "unrecognized arguments", which reads like a
    # version skew and sends the deployer to `uvicorn --workers 4` — the one
    # path that skips every check we have. See `openstategraph.deployment`.
    serve.add_argument(
        "--workers",
        type=int,
        default=None,
        help="must be 1. More than one worker is refused — see docs/deploying.md.",
    )
    serve.set_defaults(handler=cmd_serve)

    mcp_parser = subparsers.add_parser("mcp", help="run the MCP server (needs [mcp])")
    mcp_parser.add_argument("--transport", choices=("stdio", "streamable-http"))
    mcp_parser.set_defaults(handler=cmd_mcp)

    providers_parser = subparsers.add_parser(
        "providers", help="what model providers are registered, and are they configured"
    )
    providers_parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "make one real, BILLABLE request per configured provider and report "
            "which answered. Off by default: a status command must not spend money."
        ),
    )
    providers_parser.set_defaults(handler=cmd_providers)

    env_example = subparsers.add_parser(
        "env-example", help="print the provider block of .env.example (names only)"
    )
    env_example.set_defaults(handler=cmd_env_example)

    return parser


def cmd_providers(args: argparse.Namespace) -> int:
    """Which providers exist, where their keys come from, and what was measured.

    The question "why is it not using my key" has one honest answer and it is
    a list: what is registered, what each one reads, which variable actually
    supplied a credential — and, said out loud, that none of this was verified
    by a request.

    **Five states, three of them knowable from here** (providers-and-credentials
    12). The extra is installed; a credential is present; which variable
    supplied it — all three are `find_spec` and the environment. *The endpoint
    is reachable* and *a request will be answered* are neither, and this
    command used to answer them anyway, in one word: `ready`. A supervisor
    session read that word, concluded three live credentials, and sent a
    correction into a running session telling it to call a model.

    So the row says `configured`, which is exactly the question
    `ProviderEnvironment.is_configured` asks, the footer defines the word
    rather than leaving a reader to, and `--check` is the only thing here that
    makes a claim about running — because it is the only thing here that calls
    anybody. `/api/providers` and its `verify` route already drew this line;
    this is the terminal catching up with the vocabulary the HTTP surface
    shipped.

    **Exit codes are deliberate and they differ between the two modes.** Plain
    `providers` is a *status* command: it exits 0 whenever it could report,
    including on a machine where nothing at all is configured, because it is
    the command you run precisely when things are broken and a non-zero exit
    would make it useless inside `set -e`. `--check` is an *assertion* — "can
    this machine run a workflow" — so it exits 1 when any configured provider
    failed to answer, and 1 when there was nothing to check at all, which is
    the same answer to the same question.
    """
    from openstategraph.config_file import find_config_file
    from openstategraph.dotenv import environment_source_note
    from openstategraph.providers import ProviderEnvironment, provider_catalogue

    catalogue = provider_catalogue()
    config = find_config_file()
    default = catalogue.elected_default()
    print(f"config file: {config if config else '(none)'}")
    # The line providers-and-credentials/13 was filed over: this command reads
    # `.env` (`console_main` loaded it before this ran) and a server does not,
    # unless it too was started through `openstategraph providers`/`serve`.
    print(environment_source_note(loaded=True))
    # The line the list was missing: which provider won, and why. Everything
    # else here answers "what could work"; only this answers the question the
    # reader actually arrived with (install-experience T3).
    print(
        textwrap.fill(
            f"default:     {default.model or '(none)'} — {default.reason}",
            width=88,
            subsequent_indent=" " * 13,
        )
    )
    print()
    environments = [ProviderEnvironment(spec) for spec in catalogue.list()]
    for here in environments:
        spec = here.spec
        # Three states, not two. "needs a key" on a provider whose integration
        # is absent sent a reader to fix the wrong thing, and then round again
        # for the real one — the round trip workflow-gallery ticket 38 exists
        # to end, in the surface it named as already doing this correctly.
        gap = here.readiness()
        if gap is None:
            state = "configured"
        elif gap.missing_package:
            state = "needs its extra"
        else:
            state = "needs a key"
        elected = "   (default)" if spec is default.spec else ""
        print(f"{spec.name:<12} {state:<12} {here.model_string()}{elected}")
        print(f"{'':<12} {_credential_line(here)}")
        print(f"{'':<12} extra 'openstategraph[{spec.extra}]'")
    for warning in catalogue.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if not args.check:
        print()
        print(
            textwrap.fill(
                "No provider was called. \"configured\" means a credential is present "
                "in this environment — not that the endpoint is reachable, and not "
                "that a request will be answered. Run `openstategraph providers "
                "--check` to make one real (billable) request per configured "
                "provider and find out.",
                width=88,
            )
        )
        return EXIT_OK
    return _check_providers(environments)


def _credential_line(here: "ProviderEnvironment") -> str:
    """What this provider reads, and which of it actually answered.

    Naming the winning variable is the state a reader could not previously
    see, and it is the one that settles Ollama: `env_vars` is two, `any` of
    them configures it, and *which* one tells a developer whether they are on
    the cloud key or on a daemon of their own. The value is a
    `credential_source` glance — a secret masked to a fixed width, an address
    shown whole, since masking a URL hides the only readable thing about it.
    """
    variables = ", ".join(here.spec.env_vars)
    if not variables:
        return "needs no credential"
    source = here.credential_source()
    if source is None:
        absent = "it is not set" if len(here.spec.env_vars) == 1 else "none of them is set"
        return f"reads {variables}; {absent}"
    name, hint = source
    # `reads X; X is set` says the name twice for the two single-variable
    # providers and is worth the branch: the name is *information* only where
    # there was a choice, which is Ollama, which is the whole reason the
    # winning variable is printed at all.
    which = "it is set" if len(here.spec.env_vars) == 1 else f"{name} is set"
    return f"reads {variables}; {which} ({hint})"


def _check_providers(environments: "list[ProviderEnvironment]") -> int:
    """One real request per configured provider. The only certain answer.

    Deliberately skips a provider that has no credential rather than calling
    it: the answer is already known and the failure would be ours, not the
    vendor's. With nothing configured at all there is nothing to check, and
    that is a failed check rather than a vacuous pass — the question `--check`
    asks is "can this machine run a workflow", and the answer is no.

    The call is `chat_model.verify_provider`, the same function
    `POST /api/providers/{name}/verify` uses, so the editor and the terminal
    cannot come to different conclusions about one key.
    """
    from openstategraph import chat_model

    checkable = [here for here in environments if here.readiness() is None]
    print()
    if not checkable:
        print("--check: nothing to check — no provider has both its extra and a credential.")
        return EXIT_FAILURE
    print(
        f"--check: making one real, billable request to each of {len(checkable)} "
        "configured providers."
    )
    failures = 0
    for here in checkable:
        failure = chat_model.verify_provider(here)
        if failure is None:
            print(f"{here.spec.name:<12} answered      {here.model_string()}")
            continue
        failures += 1
        print(f"{here.spec.name:<12} did not answer {here.model_string()}")
        print(textwrap.fill(failure, width=88, initial_indent=" " * 13, subsequent_indent=" " * 13))
    return EXIT_FAILURE if failures else EXIT_OK


def cmd_env_example(_args: argparse.Namespace) -> int:
    """The provider block of `.env.example`, generated from the registry.

    Names only, never values — see `providers.env_example_section`.
    """
    from openstategraph.providers import env_example_section

    print(env_example_section())
    return EXIT_OK


from openstategraph.dotenv import load_env_file


def main(argv: Sequence[str] | None = None) -> int:
    """The entry point. Returns the exit code rather than calling `sys.exit`,
    so a test can invoke it directly instead of shelling out to a subprocess
    — which is how a CLI ends up with untested commands."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.handler(args))
    except ImportError as exc:
        # A missing provider integration already carries our install line
        # (`_extras.provider_extra_hint`); everything else is a genuine failure.
        print(str(exc), file=sys.stderr)
        return EXIT_MISSING_EXTRA if "pip install" in str(exc) else EXIT_FAILURE
    except KeyboardInterrupt:
        return EXIT_FAILURE
    except Exception as exc:
        return _error(_terminal_message(exc))


def console_main() -> int:
    """The installed `openstategraph` command — the **process** entry point.

    `.env` is read here and not in `main()`, and the distinction is the whole
    design. `main()` is a function: this project's own tests call it in-process
    (its docstring says so, deliberately, so a CLI does not end up with
    untested commands), and a function that rewrites `os.environ` from a file on
    disk poisons every test that runs after it — which is exactly what happened
    when this lived one level down.

    So: a **process** the user launched may populate their environment from
    their file; a **function** anyone can call may not. Same boundary
    `load_workflow` observes for a library consumer, one layer in.

    Already-exported variables always win — see `openstategraph/dotenv.py`.
    """
    load_env_file()
    return main()


if __name__ == "__main__":  # pragma: no cover
    # **`console_main`, not `main`** — `python3 -m openstategraph.cli` is a
    # process the user launched, which is the whole basis of the split above,
    # and it was calling the function that deliberately does not read `.env`.
    #
    # The symptom is not an error. Every provider reads "needs key", the editor
    # reports "no provider is configured on this server", and workflows run
    # against mock data — so a wiring gap and a missing credential become the
    # same thing, which is the failure mode `CLAUDE.md` writes a whole standing
    # instruction about.
    #
    # Found from the other end on 2026-08-18: `.claude/launch.json` starts the
    # backend with `python3 -m uvicorn openstategraph.api.main:app`, the same
    # bypass one layer out. `scripts/dev.sh` has always known — it loads `.env`
    # into the shell itself before launching uvicorn, in a block whose comment
    # explains why.
    raise SystemExit(console_main())
