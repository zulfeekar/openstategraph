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
from typing import Any

from openstategraph.errors import InvalidPackageName, PackageNotFound
from openstategraph.results import RunResult
from openstategraph.schema import normalize_document

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

    def mermaid(self, *, xray: bool = True) -> str:
        """The compiled topology as Mermaid **text**, with no network call.

        `xray=True` expands subgraph internals, so what you render is what the
        compiler actually produced. Never `draw_mermaid_png()`: that posts the
        graph to a third-party API.
        """
        return self.graph.get_graph(xray=xray).draw_mermaid()

    def ask(
        self,
        question: str,
        *,
        thread_id: str | None = None,
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
        """
        thread = thread_id or f"load-workflow-{uuid.uuid4().hex}"
        config = {
            "recursion_limit": recursion_limit,
            "configurable": {"thread_id": thread},
        }
        started = time.monotonic()
        final = self.graph.invoke(
            {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )
        result = RunResult(
            str(final.get("answer") or ""),
            decisions=final.get("decisions") or {},
            outputs=final.get("outputs") or {},
            warnings=self.warnings,
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

    def as_tool(self, *, name: str | None = None, description: str | None = None) -> Any:
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


def load_workflow(
    package_dir: str | Path,
    *,
    model: Any = None,
    checkpointer: Any = None,
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

    `checkpointer` is optional. By default the package's own
    `settings.checkpointer` decides (sqlite, or an in-process saver), which is
    what makes `human.approval` nodes able to pause and `ask(thread_id=...)`
    able to continue. Pass your own — a Postgres saver, say — to own durability.

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
    from openstategraph.memory import checkpointer_for

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

    services = WorkflowServices(directory.parent)
    resolved_model = model
    if model is None or isinstance(model, str):
        from langchain.chat_models import init_chat_model

        from openstategraph._extras import provider_extra_hint

        model_name = resolve_model(model or workflow_default_model(document))
        try:
            resolved_model = init_chat_model(model_name)
        except ImportError as exc:
            # Provider SDKs are extras (framework-packaging §3.1). The adopter
            # installed *us*, not `langchain-anthropic`, so name our install
            # line rather than leaving them to map a package to an extra.
            hint = provider_extra_hint(model_name)
            raise ImportError(
                f"{exc} — model {model_name!r} needs its provider integration"
                + (f": {hint}" if hint else "")
            ) from exc

    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    knowledge_override = Path(knowledge_dir).expanduser().resolve() if knowledge_dir else None
    runtime = services.runtime_for(slug, document, resolved_model, knowledge_dir=knowledge_override)

    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = checkpointer_for(document.get("settings"), slug, InMemorySaver())

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
    )


__all__ = ["CompiledWorkflow", "DEFAULT_RECURSION_LIMIT", "RunResult", "load_workflow"]
