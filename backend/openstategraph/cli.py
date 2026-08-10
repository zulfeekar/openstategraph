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
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

#: Fixed, documented above, and referenced by name everywhere below so a
#: reader never has to decode a bare integer.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_MISSING_EXTRA = 3


def _error(message: str) -> int:
    print(message, file=sys.stderr)
    return EXIT_FAILURE


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
    calls, so the two can never produce different packages."""
    from openstategraph.scaffold import ScaffoldError, new_team, new_workflow

    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd() / "workflows"
    try:
        if args.team:
            target = new_team(root, args.slug, args.name)
        else:
            target = new_workflow(root, args.slug, args.name)
    except ScaffoldError as exc:
        return _error(str(exc))
    print(f"{'team' if args.team else 'workflow'} package created: {target}")
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
    """The free index tier: every topic and the hint that IS its first line."""
    from openstategraph.knowledge import PackageKnowledge

    package = Path(args.package).expanduser().resolve()
    topics = PackageKnowledge(
        package, knowledge_dir=getattr(args, "knowledge_dir", None)
    ).topics()
    if not topics:
        print("no knowledge topics — build them with: openstategraph knowledge build <package>")
        return EXIT_OK
    for entry in topics:
        print(f"- {entry.name} — {entry.hint}" if entry.hint else f"- {entry.name}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """uvicorn on the editor's HTTP app. Requires the `[server]` extra."""
    try:
        import uvicorn
    except ImportError:
        return _missing("uvicorn", "server", "the HTTP API")

    uvicorn.run("openstategraph.api.main:app", host=args.host, port=args.port)
    return EXIT_OK


def cmd_mcp(args: argparse.Namespace) -> int:
    """The MCP transport. Requires the `[mcp]` extra.

    `--transport` sets `OPENSTATEGRAPH_MCP_TRANSPORT` rather than replacing it:
    the environment variable is the shipped interface and keeps working.
    """
    import os

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

    new = subparsers.add_parser("new", help="scaffold a workflow package")
    new.add_argument("slug", help="lowercase letters, digits and hyphens")
    new.add_argument("name", nargs="?", help="display name (default: derived from the slug)")
    new.add_argument("--team", action="store_true", help="supervisor + worker + grader instead")
    new.add_argument("--root", help="where to create it (default: ./workflows)")
    new.set_defaults(handler=cmd_new)

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

    serve = subparsers.add_parser("serve", help="run the HTTP API (needs [server])")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
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
