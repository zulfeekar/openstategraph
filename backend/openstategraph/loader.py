"""The one public entry point for running a workflow package you own.

**Why this exists.** OpenStateGraph is a compiler, so the artifact a developer
commits is a package folder — `workflow.json` plus `tools/`, `functions/`,
`middlewares/`, `skills/`, `knowledge/`. Compiling that document is two lines;
compiling it *with the package's own capabilities wired* is six, and the
difference between them is invisible at run time. Verified live: a package
loaded with a bare ``NodeRuntime(model=...)`` compiles, runs, and answers —
while ``unresolved_tools`` holds every tool the agent was drawn with and the
agent replies "we need to call chinook_list_tables" instead of querying
anything. That is the parametric-answer failure this codebase treats as the
worst kind, reached by following the documented snippet.

So the assembly `WorkflowServices` already owns for HTTP and MCP is exposed
here as **one function** with the package directory as its only required
argument. A consumer passes exactly what they have — a folder — and gets back
a small value object: the compiled graph (the full escape hatch), the
capabilities that could not be resolved, a Mermaid rendering, and one
convenience for asking a question.

**Import cost is part of the contract.** Nothing here imports LangGraph,
LangChain or FastAPI at module scope, so ``import openstategraph`` stays cheap
and side-effect free; the runtime arrives on the first ``load_workflow`` call.
A consumer running a graph in-process never touches the web layer at all.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from openstategraph.errors import InvalidPackageName, PackageNotFound
from openstategraph.results import RunResult
from openstategraph.schema import normalize_document

if TYPE_CHECKING:
    # TYPE_CHECKING, not a plain import: `import openstategraph` must stay
    # cheap — the runtime arrives on the first `load_workflow()` call, and a
    # subprocess test plus `scripts/clean_install_proof.sh` both assert that
    # langgraph and langchain_core are absent from `sys.modules` until then.
    # `from __future__ import annotations` above makes every annotation a
    # string, so these names are never evaluated at run time.
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

#: Supersteps, not iterations — see CLAUDE.md. Matches the editor's own
#: default so a workflow behaves the same run from a script as from the canvas.
DEFAULT_RECURSION_LIMIT = 50


@dataclass(frozen=True)
class CompiledWorkflow:
    """One loaded package, ready to run.

    Deliberately small: `graph` is the escape hatch (a plain compiled
    LangGraph object — stream it, checkpoint it, mount it in your own service),
    and everything else here is the convenience that makes the common case one
    line. Nothing wraps LangGraph's own surface, because wrapping it would be
    the beginning of the execution engine this project refuses to write.
    """

    #: The compiled LangGraph `StateGraph`. Everything LangGraph can do, you
    #: can do — `.stream()`, `.astream_events()`, `.get_state()`, `.invoke()`.
    graph: Any
    #: Capabilities the package names but this process could not resolve —
    #: a bound tool with no implementation, a `function.*` with no callable, a
    #: subgraph whose workflow is missing. Empty is the healthy case; anything
    #: here means the graph will run and answer *less well than it looks*.
    warnings: list[str] = field(default_factory=list)
    #: The package's identity, derived from the directory name.
    slug: str = ""
    package_dir: Path = Path()
    #: The vendor-neutral document that was compiled, envelope already peeled.
    document: dict[str, Any] = field(default_factory=dict)
    #: Where `ask()` appends one JSON line per run, or None for no trace.
    #: Set through `load_workflow(..., trace_file=...)`; see `_append_trace`
    #: for exactly what is written and — more importantly — what is not.
    trace_file: Path | None = None
    #: What `load_workflow` opened on this object's behalf and must therefore
    #: release: the `WorkflowServices` (checkpointer + memory store) and, when
    #: the document asked for `settings.checkpointer: "sqlite"`, that
    #: workflow's own saver. Underscored and excluded from `repr`/equality
    #: because it is bookkeeping, not part of what a loaded workflow *is* —
    #: but it is a field rather than a closure so the dataclass stays frozen
    #: and comparable. A checkpointer the *caller* passed is never in here.
    _owned: tuple[Any, ...] = field(default=(), repr=False, compare=False)

    def close(self) -> None:
        """Release the sqlite handles this load opened. Idempotent.

        Only needed by a process that loads workflows repeatedly — a script
        that loads one and exits has never had a problem, which is exactly why
        the leak survived: langgraph's sqlite saver and store have no
        `close()`, so one file descriptor per `load_workflow` accumulated
        invisibly in the long-lived transports.

        After this, `graph` and `ask()` are no longer usable. Use the context
        manager form when the scope is obvious:

            with load_workflow("workflows/billing") as billing:
                print(billing.ask("How much did we invoice in March?"))
        """
        from openstategraph.memory import close_resource

        for resource in self._owned:
            closer = getattr(resource, "close", None)
            if callable(closer):
                closer()
            else:
                close_resource(resource)

    def __enter__(self) -> "CompiledWorkflow":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def mermaid(self, *, xray: bool = True) -> str:
        """The compiled topology as Mermaid **text**, with no network call.

        `xray` expands a **LangGraph subgraph**, and this compiler emits none,
        so today the flag changes nothing: an agent is built lazily inside its
        node's closure, and a mount is a closure over the child's `invoke()`.
        Neither is a node LangGraph can open. Verified byte-identical against
        `xray=False` on all 23 shipped examples.

        The parameter stays because the day a node type compiles to a real
        subgraph it starts mattering again, and
        `backend/tests/test_behind_the_scenes.py` fails on that day rather
        than letting the words drift back.

        (Until 2026-08-16 this said "`xray=True` expands subgraph internals,
        so what you render is what the compiler actually produced" — aspirational
        for the one construct it named, and the third unciteable claim found in
        this area.)

        Never `draw_mermaid_png()`: that posts the graph to a third-party API.
        """
        diagram: str = self.graph.get_graph(xray=xray).draw_mermaid()
        return diagram

    def ask(
        self,
        question: str,
        *,
        thread_id: str | None = None,
        user_email: str | None = None,
        session_id: str | None = None,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    ) -> RunResult:
        """Run the graph once and return its answer.

        The return value **is** the answer string — `RunResult` subclasses
        `str`, so everything that worked when this returned a bare `str` still
        works — with the rest of the run attached: `.decisions`, `.outputs`,
        `.warnings`, `.attempts`. Those are what you need when the answer is
        wrong, and reaching them used to mean dropping to `.graph.invoke()`
        with hand-seeded state, which is the ceremony this function replaces.

        The initial state is not arbitrary — `attempts`/`decisions`/`outputs`
        must be seeded or a grader loop reads `None` where it expects a
        counter. Getting that wrong is silent, so it is done here rather than
        printed in a snippet for everyone to copy.

        `thread_id` names a conversation for the checkpointer: omit it and
        every call is independent; pass the same string twice and the second
        call continues the first. Use `.graph` directly for streaming,
        multi-key results, or an interrupted human-approval resume.

        `user_email` is **who this run is for**, and it is what scopes
        per-person long-term memory. Omit it and user-scoped memory does not
        bind at all — `save_memory(scope="user")` says so rather than writing
        into a namespace shared with everyone else who did not identify
        (memory ticket 01). Over HTTP this value is the server's to determine
        and a client may not send it; here **you are** the server, so it is
        yours to supply. `session_id` scopes thread listing only.

        Both use the same names as `RunRequest`, so one vocabulary describes
        identity whichever way a run is started.

        `workflow_slug` needs no argument: this object knows its own slug and
        now passes it, which is what scopes workflow memory and stamps the
        provenance of an app-scope deposit. Before this it was dropped, so
        every workflow in a process shared `("workflow-memory", "unsaved")`.
        """
        thread = thread_id or f"load-workflow-{uuid.uuid4().hex}"
        config = {
            "recursion_limit": recursion_limit,
            "configurable": {
                "thread_id": thread,
                "user_email": user_email or "",
                "session_id": session_id or "",
                "workflow_slug": self.slug or "",
            },
        }
        from openstategraph.compile.workflow_compiler import run_health_from_state

        started = time.monotonic()
        final = self.graph.invoke(
            {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )
        outputs = final.get("outputs") or {}
        # The third door onto `run_health`, and the one that had been reading
        # a third of it (`workflow-gallery` 49). Derived from the assembly
        # rather than re-listed here: this door fell behind three times, once
        # per source added to `run_health`, and each time by re-listing.
        health = run_health_from_state(final)
        result = RunResult(
            str(final.get("answer") or ""),
            decisions=final.get("decisions") or {},
            outputs=outputs,
            # A warning about how the workflow was *built* explains one about
            # how it ran, so compile findings go first; a claim the run failed
            # goes before a report about how the answer was reached.
            warnings=[*self.warnings, *health.failures, *health.silent],
            # Only the failure half — a silent node, a forced pass and an
            # unrouted verdict must never reach an exit code. A compile
            # finding does: a mount that could not be loaded leaves no marker
            # in `outputs` and is still a broken run (`production-ready` 53).
            failures=[*self.warnings, *health.failures],
            attempts=int(final.get("attempts") or 0),
        )
        self._append_trace(question, result, time.monotonic() - started)
        return result

    def _append_trace(self, question: str, result: RunResult, seconds: float) -> None:
        """One JSON line per run, appended to `trace_file`. Never fatal.

        **A file sink, not a tracing framework.** LangSmith and OpenTelemetry
        exist; this is the thing you attach to a support ticket, and inventing
        a span model to compete with them would be inventing an abstraction we
        do not have.

        **The answer text is deliberately not written — only its length.** A
        trace file gets committed, emailed and pasted into issues, and an
        answer is the one field in a run that reliably contains a customer's
        data. `decisions` and `attempts` are what tell you *which way the graph
        went*, which is what a wrong answer is diagnosed from; the answer
        itself you already have in front of you.

        A path that cannot be written **warns and returns**. A trace is
        diagnostics: losing it must never lose the run that produced it.
        """
        if self.trace_file is None:
            return
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "slug": self.slug,
            "question": question,
            "decisions": result.decisions,
            "attempts": result.attempts,
            "warnings": result.warnings,
            "seconds": round(seconds, 3),
            "answer_chars": len(result),
        }
        try:
            self.trace_file.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line) + "\n")
        except OSError as exc:
            logger.warning("Could not write the run trace to %s: %s", self.trace_file, exc)

    def as_tool(self, *, name: str | None = None, description: str | None = None) -> BaseTool:
        """This whole workflow, as one LangChain tool your existing agent can call.

        For the team already on `create_agent` who does not want to restructure:

            from langchain.agents import create_agent

            billing = load_workflow("workflows/billing").as_tool(
                name="billing_analyst",
                description="Answers questions about invoices and revenue.",
            )
            agent = create_agent(model, tools=[billing, ...])

        **Adapted at the seam, never subclassed** — the same rule and the same
        `StructuredTool.from_function` shape `abc/tool.py` uses, so an upstream
        change to LangChain's tool internals cannot reach into us.

        **Isolation, stated plainly, because it is the part people get wrong.**
        The workflow runs as its own graph. It sees the question string and
        nothing else — not the calling agent's message history, not its state,
        not its tools — and it returns its answer text as the tool's result.
        That is exactly the subagent rule this codebase already states
        (CLAUDE.md, "State flows down; subagents do not receive it"): a
        subagent is invoked as a tool, gets a task, and reports a result. If
        the caller needs the workflow to know something, it has to be in the
        question.

        Each call runs on its own thread id, so two calls never continue each
        other's conversation. Use `.ask(thread_id=...)` directly if you want
        one that does.

        There is deliberately **no middleware equivalent**. Middleware would
        have to decide *when* to consult the workflow, which is a routing
        policy — and a router is something this framework already expresses as
        a document (`route.classifier`). Shipping a second, worse one inside
        the library would be the duplicated-knowledge defect CLAUDE.md names.
        """
        from pydantic import BaseModel, Field

        from langchain_core.tools import StructuredTool

        class _Question(BaseModel):
            model_config = {"extra": "forbid"}
            question: str = Field(description="The question to ask this workflow.")

        def _call(question: str) -> str:
            return str(self.ask(question))

        tool_name = name or re.sub(r"[^a-zA-Z0-9_]+", "_", self.slug or "workflow").strip("_")
        return StructuredTool.from_function(
            func=_call,
            name=tool_name or "workflow",
            description=description or self._default_tool_description(),
            args_schema=_Question,
        )

    def _default_tool_description(self) -> str:
        """A description from the document, so the tool is usable un-configured.

        Named `description=` is still the right answer — the calling model
        picks tools by this text — but a missing one must not produce a tool
        the model cannot tell apart from any other.
        """
        title = str(self.document.get("name") or self.slug or "workflow")
        return f"Ask the {title!r} OpenStateGraph workflow a question and get its answer."


def _warnings_with_node_failures(
    warnings: Sequence[str], outputs: Mapping[str, Any]
) -> list[str]:
    """Compile findings, then the steps that broke — the **failure** half.

    Superseded as the library door's report by `run_health_from_state`, which
    carries all four sources rather than this one (`workflow-gallery` 49).
    Kept because this is exactly `RunResult.failures` for a caller that holds
    outputs and no state, and because deleting a name three tests and the
    ticket record all cite would lose the chain back.
    """
    from openstategraph.compile.workflow_compiler import node_failure_warnings

    return [*warnings, *node_failure_warnings(outputs)]


def load_workflow(
    package_dir: str | Path,
    *,
    model: Any = None,
    # Named rather than `Any`: these have one published base class each, and
    # the failure mode of the wrong object is a stack trace inside LangGraph
    # that mentions no code of ours.
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    store: BaseStore | None = None,
    tools: dict[str, Any] | None = None,
    functions: dict[str, Any] | None = None,
    middleware: dict[str, Any] | None = None,
    knowledge_dir: str | Path | None = None,
    trace_file: str | Path | None = None,
) -> CompiledWorkflow:
    """Compile the workflow package at `package_dir`, capabilities and all.

    `package_dir` is the folder holding `workflow.json`. Both things the
    runtime needs are derived from it — the workflows **root** is its parent
    and the **slug** is its own name — so a consumer passes the one path they
    actually have rather than restating it twice.

    `model` accepts either a LangChain model string (`"anthropic:claude-..."`,
    `"ollama:gpt-oss:120b-cloud"`), resolved through the *same* path the HTTP
    API uses so behaviour is identical, or an already-built LangChain model
    object, which is passed through untouched. `None` means: the document's own
    `settings.model` if it names one, otherwise the environment default
    (`ANTHROPIC_API_KEY` → Claude, `OPENAI_API_KEY` → GPT, else Ollama
    **cloud**). A node that names its own model still overrides all of this.

    `checkpointer` is optional, and durable by default. Threads land in
    `<workflows root>/.openstategraph/checkpoints.sqlite` — the workflows root
    being this package's parent — so a `human.approval` pause and an
    `ask(thread_id=...)` conversation both outlive the process. A package's own
    `settings.checkpointer: "sqlite"` still takes its own per-workflow file;
    `OPENSTATEGRAPH_CHECKPOINT_PATH` moves the default or, set to `memory`,
    opts out of durability entirely. Pass your own — a Postgres saver, say —
    to own durability, which outranks all of the above.

    `store` is the long-term memory `Store` — the collaborator the prebuilt
    `save_memory`/`search_memory` tools read and write, namespaced per user.
    `None` keeps the environment-driven default (in-process, or sqlite when
    `OPENSTATEGRAPH_MEMORY_PATH` is set). Pass a LangGraph `BaseStore` —
    Postgres, Redis, your own — to own memory durability the same way
    `checkpointer` lets you own thread durability. The two are siblings and
    are meant to be supplied together: owning half of persistence is how a
    deployment ends up with durable conversations and evaporating memories.

    `tools` and `functions` are explicit capability mappings —
    `{"tool.my-thing": instance}` and `{"function.my_fn": callable}` — keyed
    exactly as a document names them. `middleware` is the same idea for the
    slot table (`{"summarization": middleware_object}`), keyed by slot name
    as `middlewares/<slot>.py` is.

    **Precedence: built-in < installed plugin < the package's own files <
    these arguments.** An explicit mapping is the most specific source there
    is, so it outranks every discovered one. The filesystem describes what a
    package *shipped*; an argument describes what *this process* is to run,
    and only the caller knows which is right — a vendored package, a package
    on a read-only mount, a test that needs one tool stubbed and the rest
    real. The reverse order would make substitution impossible: a package
    could veto the host application. A collision with a discovered capability
    is therefore **not** reported on `.warnings`; it is a deliberate
    substitution, and warning about it would train adopters to ignore the one
    list that means "this run lost a capability".

    `knowledge_dir` overrides where the package's second brain is read from.
    The default stays the **convention** — `<package>/knowledge` — because
    discovery-by-convention is why this function takes one argument. The
    override is for the cases convention cannot express: knowledge shared
    between two packages, knowledge that lives outside the repository, or a
    test pointing at a fixture directory. It names the directory that *holds
    the `<topic>.md` files*, not the package above it.

    `trace_file` appends one JSON line per `ask()` — question, slug,
    decisions, attempts, warnings, duration and the answer's **length**, never
    the answer text (see `CompiledWorkflow._append_trace` for why). A path
    that cannot be written warns; it never fails a run.

    **Unresolved capabilities never raise.** They land on `.warnings` and log
    one WARNING line naming them, because the alternative failure mode is a
    workflow that answers confidently without the tools it was drawn with.
    """
    directory = Path(package_dir).expanduser().resolve()
    manifest = directory / "workflow.json"
    if not manifest.is_file():
        raise PackageNotFound(f"no workflow.json in {directory} — is that a workflow package?")

    # Lazy, all of it: this is where a consumer opts into the runtime.
    from openstategraph.api.model_resolution import resolve_model, workflow_default_model
    from openstategraph.api.registries import runtime_warnings
    from openstategraph.api.services import WorkflowServices
    from openstategraph.api.workflow_store import slugify
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    slug = directory.name
    if slug != slugify(slug):
        # The slug is the package's frozen identity and is what scopes tool,
        # function, skill and knowledge discovery. A directory the store
        # cannot address would silently discover nothing — the exact silent
        # degradation this function exists to prevent — so say it instead.
        raise InvalidPackageName(
            f"workflow package directory {slug!r} is not a valid slug; "
            f"rename it to {slugify(slug)!r} (lowercase letters, digits and hyphens)"
        )

    document = normalize_document(json.loads(manifest.read_text()))

    # One assembly point, shared with HTTP and MCP: the caller's collaborators
    # go in here rather than into a second wiring path beside it.
    services = WorkflowServices(
        directory.parent,
        # The public parameter is `store=` and stays that way — it is in
        # `public_api.txt`, so renaming it would break an adopter's call. The
        # *internal* keyword says which store it is (ticket 12).
        memory_store=store,
        checkpointer=checkpointer,
        tools=tools,
        functions=functions,
        middleware=middleware,
    )
    resolved_model = model
    if model is None or isinstance(model, str):
        from openstategraph.chat_model import build_chat_model

        # The credential gate, the endpoint and the extras hint all live in
        # `chat_model`. They used to live here, which meant the HTTP, MCP and
        # per-node paths called `init_chat_model` directly and got the vendor
        # SDK's error instead of ours.
        resolved_model = build_chat_model(
            resolve_model(model or workflow_default_model(document))
        )

    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    knowledge_override = Path(knowledge_dir).expanduser().resolve() if knowledge_dir else None
    # A capability that failed to load — a half-installed plugin distribution
    # (ticket 05), a tool class left abstract (ticket 07) — is a capability
    # this run does not have, so it belongs on `.warnings` beside every other
    # one, not only in a log line the consumer's service will never show them.
    # It arrives through `runtime_warnings(runtime)` below: `runtime_for` hangs
    # the findings on the runtime itself, so every transport reports them and
    # this one no longer needs its own sink (passing one as well would report
    # each finding twice).
    runtime = services.runtime_for(
        slug,
        document,
        resolved_model,
        knowledge_dir=knowledge_override,
    )

    # The services were built here, so their two sqlite handles are this
    # workflow's to close (see `CompiledWorkflow.close`).
    owned: list[Any] = [services]
    if checkpointer is None:
        # The same seam the HTTP and MCP transports use, and the same default:
        # `services.checkpointer` is durable (a sqlite file under the workflows
        # root) unless the environment opts out. Before ticket 05 this was a
        # fresh `InMemorySaver` per call, which meant a `human.approval` pause
        # could not be resumed by a second process — or even by a second
        # `load_workflow` in the same one.
        checkpointer = services.checkpointer_for(document.get("settings"), slug)
        # A per-workflow `settings.checkpointer: "sqlite"` file is opened and
        # owned by the services object itself, so nothing extra to track here.

    graph = compiler.build(
        document,
        RunState,
        runtime.factory(document),
        checkpointer=checkpointer,
        store=services.memory_store,
    )

    warnings = list(plan.warnings) + runtime_warnings(runtime)
    if warnings:
        # Degrade loud, never silent — the same rule the run endpoints follow.
        logger.warning(
            "Workflow %r loaded with %d unresolved capability warning(s): %s",
            slug,
            len(warnings),
            " | ".join(warnings),
        )

    return CompiledWorkflow(
        graph=graph,
        warnings=warnings,
        slug=slug,
        package_dir=directory,
        document=document,
        trace_file=Path(trace_file).expanduser() if trace_file else None,
        _owned=tuple(owned),
    )


__all__ = ["CompiledWorkflow", "DEFAULT_RECURSION_LIMIT", "RunResult", "load_workflow"]
