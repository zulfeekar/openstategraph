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
   spends half its dependency floor on. A project arguing for a four-package
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
checkout. `new` writes to `./workflows` by convention, overridable with
`--root`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

# The one import this module makes eagerly, and it is stdlib-only: `--template`
# uses argparse `choices`, so the catalogue has to exist while the parser is
# being built. Everything else is still imported inside its command.
from openstategraph import templates

#: Fixed, documented above, and referenced by name everywhere below so a
#: reader never has to decode a bare integer.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_MISSING_EXTRA = 3


def _error(message: str) -> int:
    print(message, file=sys.stderr)
    return EXIT_FAILURE


def _usage(message: str) -> int:
    """A bad *invocation*, not a failed run — argparse's own code, so CI can
    tell "you typed it wrong" from "it did not work"."""
    print(message, file=sys.stderr)
    return EXIT_USAGE


def _load(args: argparse.Namespace) -> Any:
    """The one `load_workflow` call the whole CLI shares."""
    from openstategraph import load_workflow

    return load_workflow(
        args.package,
        model=getattr(args, "model", None),
        trace_file=getattr(args, "trace_file", None),
        knowledge_dir=getattr(args, "knowledge_dir", None),
    )


# --------------------------------------------------------------------------
# commands


def cmd_run(args: argparse.Namespace) -> int:
    """`load_workflow(pkg).ask(question)`, and nothing else."""
    workflow = _load(args)
    # The thread id is minted HERE rather than left to `ask()` so that `--json`
    # can report it: a caller who wants a follow-up turn needs the id of the
    # conversation they just had, and an id generated inside the run and thrown
    # away is an id they can never continue.
    thread_id = args.thread_id or f"openstategraph-cli-{uuid.uuid4().hex}"
    result = workflow.ask(args.question, thread_id=thread_id)

    if args.json:
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "decisions": result.decisions,
                    "outputs": result.outputs,
                    "warnings": result.warnings,
                    "attempts": result.attempts,
                    "thread_id": thread_id,
                    "slug": workflow.slug,
                },
                indent=2,
            )
        )
        return EXIT_OK

    for warning in result.warnings:
        # Degrade loud, never silent — on stderr, so `run … > answer.txt` still
        # gives you only the answer while the degradation stays visible.
        print(f"warning: {warning}", file=sys.stderr)
    print(result)
    return EXIT_OK


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


def cmd_validate(args: argparse.Namespace) -> int:
    """The compiler's own plan and findings, via the seam MCP already uses.

    `prebuilt_architect.ValidateWorkflowTool` — not a second validator. Two
    validators is how a document passes one gate and fails the other.
    """
    from openstategraph.prebuilt_architect import ValidateWorkflowTool
    from openstategraph.schema import normalize_document

    target = Path(args.target).expanduser().resolve()
    manifest = target if target.is_file() else target / "workflow.json"
    if not manifest.is_file():
        return _error(f"no workflow document at {manifest} — is that a workflow package?")

    try:
        document = normalize_document(json.loads(manifest.read_text()))
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")

    verdict = ValidateWorkflowTool().run(document=json.dumps(document))
    print(verdict.content if verdict.ok else verdict.error)
    return EXIT_OK if verdict.ok else EXIT_FAILURE


def cmd_graph(args: argparse.Namespace) -> int:
    """Mermaid **text**, on stdout. Never `draw_mermaid_png()`, which would post
    the user's graph to a third-party API."""
    print(_load(args).mermaid(xray=args.xray))
    return EXIT_OK


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
    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd() / "workflows"
    try:
        target = new_package(root, args.slug, template=template, name=args.name)
    except ScaffoldError as exc:
        return _error(str(exc))
    print(f"{template} package created: {target}")
    return EXIT_OK


def cmd_knowledge_build(args: argparse.Namespace) -> int:
    """`api.knowledge_build.run_build` — the same path the editor's button uses."""
    from openstategraph.api.knowledge_build import UnknownSourceError, resolve_build_model, run_build
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
            (e.name, e.hint, "")
            for e in PackageKnowledge(package, knowledge_dir=override).topics()
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
        print(
            f"{row.thread_id}  {row.updated_at}  {row.status:8}  "
            f"{row.workflow_slug or '-'}  {who}  {row.question[:60]}"
        )
    return EXIT_OK


def cmd_threads_show(args: argparse.Namespace) -> int:
    """One past run, read back. A **view**: nothing is executed again.

    Continuing a paused run is a different act with a different name —
    `POST /api/runs/resume`, or `run --thread-id` — and it does call models
    and tools. Printing what already happened does not.
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
    print(f"thread {thread.thread_id} — {thread.status}")
    print(f"  workflow: {thread.workflow_slug or '-'}")
    print(f"  user:     {thread.user_email or 'anonymous'}")
    print(f"  session:  {thread.session_id or '-'}")
    print(f"  updated:  {thread.updated_at}")
    print("  (a recording, not a re-run — no model or tool was called to show this)")
    for step in history.steps:
        print(f"\nstep {step.step} ({step.source}) {step.at}")
        for key, value in step.values.items():
            if not value:
                continue
            print(f"  {key}: {value}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """The whole product on one origin: editor at `/`, chat at `/chat`, API
    under `/api`. Requires the `[server]` extra.

    Two collaborators do the work — `api.listening` decides the port and binds
    it, `api.editor_assets` decides where the built editor comes from — so this
    stays argument handling plus a call, per the rules at the top of the file.

    The socket is bound here and handed to uvicorn rather than passing it a
    number, because that is the only way `--port 0` can print the URL it landed
    on *before* the server starts talking.

    Two refusals happen before anything is bound (scale-and-adopt ticket 06),
    because a message printed after a server is listening is a message someone
    scrolls past: more than one worker is refused outright, and an
    unauthenticated bind to a non-loopback address is warned about by name.
    """
    from openstategraph import deployment

    refusal = deployment.check_worker_count(explicit=getattr(args, "workers", None))
    if refusal is not None:
        return _error(refusal)

    try:
        import uvicorn
    except ImportError:
        return _missing("uvicorn", "server", "the HTTP API")

    from openstategraph.api import auth
    from openstategraph.api.listening import PortUnavailable, bind_listener, listen_urls

    exposure = auth.exposure_warning(args.host)
    if exposure is not None:
        print(exposure, file=sys.stderr, flush=True)

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

    uvicorn.Server(
        uvicorn.Config("openstategraph.api.main:app", host=args.host, port=port)
    ).run(sockets=[listener])
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
    run.add_argument("--json", action="store_true", help="print the whole result, not the answer")
    run.set_defaults(handler=cmd_run)

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
        help="expand subgraph internals (default: on)",
    )
    graph.set_defaults(handler=cmd_graph)

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
    new.add_argument("--root", help="where to create it (default: ./workflows)")
    new.set_defaults(handler=cmd_new)

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
        "serve", help="run the editor, the chat surface and the API (needs [server])"
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
    providers_parser.set_defaults(handler=cmd_providers)

    env_example = subparsers.add_parser(
        "env-example", help="print the provider block of .env.example (names only)"
    )
    env_example.set_defaults(handler=cmd_env_example)

    return parser


def cmd_providers(_args: argparse.Namespace) -> int:
    """Which providers exist, where their keys come from, and which work now.

    The question "why is it not using my key" has one honest answer and it is
    a list: what is registered, what each one reads, and which of them is
    actually configured on this machine.
    """
    from openstategraph.config_file import find_config_file
    from openstategraph.providers import provider_catalogue

    catalogue = provider_catalogue()
    config = find_config_file()
    print(f"config file: {config if config else '(none)'}")
    print()
    for spec in catalogue.list():
        state = "ready" if spec.is_configured() else "needs a key"
        variables = ", ".join(spec.env_vars) or "(no credential needed)"
        print(f"{spec.name:<12} {state:<12} {spec.model_string()}")
        print(f"{'':<12} reads {variables}; extra 'openstategraph[{spec.extra}]'")
    for warning in catalogue.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return EXIT_OK


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
        return _error(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


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
