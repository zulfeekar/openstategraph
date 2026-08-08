"""The editor ↔ runtime boundary.

FastAPI, on the MIT pieces of LangGraph. The LangGraph **Agent Server** is ruled
out on licence (ticket 07): `langgraph-api` is Elastic License 2.0, which forbids
offering the software as a hosted service — it fails twice for an OSS project. So
we build the seam ourselves and copy the Agent Server's *shape* (assistants,
threads, runs, stream modes) to keep a later swap cheap.

Two rules this file exists to enforce:

**The browser never reaches a model provider.** Keys live here, server-side. The
frontend posts a question and receives an answer; it holds no credentials and runs
no graph.

**The seam is one-directional.** `workflow.json` and a question flow in; an answer
and a Mermaid diagram flow out. Nothing reads runtime objects back into the editor
model.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# `basicConfig` is a no-op if the root logger already has handlers (e.g. under
# pytest, or when `uvicorn --log-config` sets its own), so this is safe to call
# unconditionally rather than guessing whether we're the entrypoint.
logging.basicConfig(level=os.getenv("DYFLOW_LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

#: Where the editor dev server runs. Explicit, not `*` — the API will hold keys.
ALLOWED_ORIGINS = ["http://localhost:5273", "http://127.0.0.1:5273"]

#: Human-in-the-loop's prerequisite: `interrupt()` requires the compiled
#: graph to have a checkpointer, or LangGraph raises at compile time. One
#: process-lifetime, in-memory instance, shared by every `/api/runs/stream`
#: and `/api/runs/resume` call so a resume can find the run it is
#: continuing. A real, stated limitation, not glossed over: this does not
#: survive a process restart and does not work across multiple workers —
#: the same "local dev tool, not hosted" boundary `capability_discovery.py`
#: already draws for its own lack of sandboxing. A production deployment
#: needs a real persisted checkpointer (Postgres), which is ticket 10's own
#: already-named, still-open gap.
from langgraph.checkpoint.memory import InMemorySaver

_HUMAN_IN_THE_LOOP_CHECKPOINTER = InMemorySaver()

#: The Ollama model to use — a **cloud** model, never a local one.
#:
#: Standing project instruction: local models are not performant enough for this
#: workload, and the evidence is direct. `llama3.1:8b` locally could not hold
#: structured output at all, took minutes per run, and produced a confidently
#: wrong answer about global music revenue when asked a database question. The
#: same workflow on `gpt-oss:120b-cloud` wrote a correct two-join `GROUP BY` and
#: answered in 23s.
#:
#: So a bare `ollama:` fallback must resolve to cloud. Anyone wanting a local
#: model has to name it explicitly in the request, which is the right amount of
#: friction for a choice that changes the result this much.
OLLAMA_CLOUD_MODEL = "ollama:gpt-oss:120b-cloud"

class AskRequest(BaseModel):
    model_config = {"extra": "forbid"}

    question: str = Field(min_length=1, description="A natural-language question.")
    #: Provider-prefixed, e.g. `anthropic:claude-haiku-4-5` or `ollama:llama3.1:8b`.
    model: str | None = None
    #: Superstep budget, **not** an iteration count. See graph.py.
    recursion_limit: int = Field(default=50, ge=10, le=1000)


class RunRequest(BaseModel):
    """Run **the posted document**, not a server-side graph.

    This is what makes the editor's Run button honest: the workflow the developer
    can see on the canvas is the workflow that executes. The document is
    vendor-neutral `workflow.json`, so the compile seam stays one-directional.
    """

    model_config = {"extra": "forbid"}

    workflow: dict[str, Any] = Field(description="A workflow.json document.")
    question: str = Field(min_length=1)
    model: str | None = None
    recursion_limit: int = Field(default=50, ge=10, le=1000)
    #: Set by the client on a fresh send; echoed back so a paused run's
    #: eventual resume call can target the same checkpointed thread.
    thread_id: str | None = None
    #: Customer-client identity (ticket 64): a browser session and the person.
    #: Neither ever enters a Store namespace by itself — per the memory
    #: research (ticket 65), `user_email` namespaces long-term memory and
    #: `thread_id`/`session_id` scope only the checkpointer/config.
    session_id: str | None = None
    user_email: str | None = None
    #: The open workflow's slug, when the client knows it. Tools discovered
    #: in that workflow's own `tools/` folder are layered over the defaults,
    #: so a document can bind the tools that live beside it. Optional and
    #: additive — omitting it runs with the default registry, never a crash.
    workflow_slug: str | None = None


class ResumeRequest(BaseModel):
    """Continues a run a `human.approval` node paused.

    Carries the whole workflow again (not just the thread id) for the same
    reason `RunRequest` does — the compile seam is one-directional and
    stateless per call; nothing server-side remembers *which* document a
    thread belongs to between requests, only the checkpointed graph state
    LangGraph itself owns.
    """

    model_config = {"extra": "forbid"}

    thread_id: str = Field(min_length=1)
    session_id: str | None = None
    user_email: str | None = None
    workflow: dict[str, Any]
    decision: Literal["approve", "reject"]
    feedback: str | None = None
    model: str | None = None
    recursion_limit: int = Field(default=50, ge=10, le=1000)
    #: Same as `RunRequest.workflow_slug` — and it must exist on BOTH models:
    #: this class forbids extras, so a client that echoes the slug on resume
    #: (as ours does) would otherwise be rejected 422 and every approval
    #: would die at validation. A resumed run must also bind the *same*
    #: tool set as the run it resumes.
    workflow_slug: str | None = None


class RunResponse(BaseModel):
    answer: str
    #: node id -> branch taken, so the editor can highlight the path that ran.
    decisions: dict[str, str] = {}
    #: node id -> that node's output, for per-node inspection in the sidebar.
    outputs: dict[str, str] = {}
    attempts: int = 0
    mermaid: str = ""
    warnings: list[str] = []


class SaveWorkflowRequest(BaseModel):
    """The whole document plus the display name — never the slug: the slug
    is the URL path parameter, frozen at creation (see `workflow_store.py`).
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    document: dict[str, Any]


class WorkflowSummaryResponse(BaseModel):
    slug: str
    name: str
    saved_at: str
    node_count: int
    edge_count: int


class WorkflowDocumentResponse(BaseModel):
    slug: str
    document: dict[str, Any]


class ToolCapabilityResponse(BaseModel):
    id: str
    name: str
    description: str
    args_schema: dict[str, Any]
    #: The canvas node type the tool declares (`BaseTool.node_type`); empty
    #: when the tool is listable but not placeable.
    node_type: str = ""


class FunctionCapabilityResponse(BaseModel):
    id: str
    name: str
    docstring: str
    signature: str


class CapabilitiesResponse(BaseModel):
    tools: list[ToolCapabilityResponse]
    functions: list[FunctionCapabilityResponse]


class AskResponse(BaseModel):
    """What the editor renders.

    The SQL and rows are returned alongside the prose deliberately: an answer a
    developer cannot audit is not much use, and seeing the query is how they tell
    a right answer from a plausible one.
    """

    answer: str
    sql: str
    rows: str
    attempts: int
    passed: bool
    reason: str


def resolve_model(requested: str | None) -> str:
    """Picks a model, preferring an explicit request.

    **Ollama cloud is the default**, not an opt-in — a developer with neither
    an Anthropic nor an OpenAI key still gets a working model with zero
    configuration, because `ollama` authenticates from its own local
    credentials (verified live: `init_chat_model("ollama:gpt-oss:120b-cloud")`
    works with no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OLLAMA_HOST` env vars
    set at all). This never falls back to a *local* model — see
    `OLLAMA_CLOUD_MODEL`'s own comment for why that standing rule exists —
    and an explicit `model` argument still always wins, so a surprise
    provider is only possible by asking for one.
    """
    if requested:
        return requested
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic:claude-haiku-4-5"
    if os.getenv("OPENAI_API_KEY"):
        return "openai:gpt-4.1-mini"
    return os.getenv("DYFLOW_OLLAMA_MODEL") or OLLAMA_CLOUD_MODEL


#: Injectable so tests can exercise the HTTP layer without a provider.
GraphFactory = Callable[[str], Any]


def _default_factory(model: str) -> Any:
    from graph import build_live_graph

    return build_live_graph(model)


def _document_of(workflow: dict[str, Any]) -> dict[str, Any]:
    """Accepts a bare document or the store's `{…, document}` envelope.

    The store saves `{version, name, savedAt, document}`; the editor's export
    posts the bare document. Both arrive at the run endpoints, and compiling
    the *envelope* silently produces a zero-node graph — so every endpoint
    unwraps through this one helper, resume included.
    """
    inner = workflow.get("document")
    return inner if isinstance(inner, dict) else workflow


def build_tool_registry(workflow_store: Any, slug: str | None) -> dict[str, Any]:
    """Default tools, with the open workflow's own tools layered over.

    The defaults (Chinook) stay so documents that bind them — the
    intent-routed demo — keep working from any workflow context. A slug adds
    that workflow's `tools/`, keyed by each tool's own `node_type`
    declaration (ticket 33); same-type collisions resolve workflow-wins,
    mirroring the frontend's local-shadows-global registry rule. A failed
    discovery degrades to the defaults with a log line, never a crash —
    `NodeRuntime.unresolved_tools` keeps missing bindings loud.
    """
    from dyflow.api.capability_discovery import discover_tool_registry
    from dyflow.compile.node_runtime import chinook_tool_registry

    from dyflow.prebuilt_sql import SQL_EXPLORER_TOOLS

    registry: dict[str, Any] = chinook_tool_registry()
    # Prebuilt SQL Explorer (ticket 66): any workflow can point these at its
    # own .sqlite file — the user's N-tables-with-JOIN-rules case as config.
    registry.update({tool.node_type: tool for tool in SQL_EXPLORER_TOOLS})
    if slug:
        try:
            registry.update(discover_tool_registry(workflow_store.directory_for(slug), slug))
        except Exception:
            logger.warning("Tool discovery failed for %r", slug, exc_info=True)
    return registry


def build_function_registry(workflow_store: Any, slug: str | None) -> dict[str, Any]:
    """`function.<name>` -> callable, from the workflow's own `functions/`.

    Mirrors `build_tool_registry`: slug-scoped, degrade-loud (the runtime
    records an unresolved function; discovery failures log and return {}).
    """
    from dyflow.api.capability_discovery import discover_function_callables

    if not slug:
        return {}
    try:
        return discover_function_callables(workflow_store.directory_for(slug), slug)
    except Exception:
        logger.warning("Function discovery failed for %r", slug, exc_info=True)
        return {}


def workflow_default_model(document: dict[str, Any]) -> str | None:
    """The document's own default model, from `settings.model` (ticket 36)."""
    settings = document.get("settings")
    if isinstance(settings, dict):
        value = settings.get("model")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def runtime_warnings(runtime: Any) -> list[str]:
    """Every "this step silently lost a capability" condition, spelled out."""
    warnings: list[str] = []
    for tool_type in runtime.unresolved_tools:
        warnings.append(
            f'No implementation for tool "{tool_type}" — the agent ran without it, '
            "so its answer may not be grounded in that data source."
        )
    for fn_type in runtime.unresolved_functions:
        warnings.append(
            f'No function found for "{fn_type}" — the step passed its input through unchanged.'
        )
    for slug_name in runtime.unresolved_subgraphs:
        warnings.append(
            f'Subgraph workflow "{slug_name}" could not be loaded — the node produced nothing.'
        )
    return warnings


def create_app(
    graph_factory: GraphFactory | None = None,
    workflows_root: Any = None,
) -> FastAPI:
    """Builds the app.

    A factory rather than a module-level singleton so tests get an isolated
    instance and can inject a stub graph — and, since tickets 10/14/16, an
    isolated `workflows_root` so a test never touches the real `workflows/`
    tree at the repo root.
    """
    from dyflow.api.workflow_store import WorkflowStore

    factory = graph_factory or _default_factory
    workflow_store = WorkflowStore(root=workflows_root)

    def tool_registry_for(slug: str | None) -> dict[str, Any]:
        return build_tool_registry(workflow_store, slug)

    def runtime_for(slug: str | None, document: dict[str, Any], model: Any) -> Any:
        """One NodeRuntime construction shared by run/stream/resume, so the
        three endpoints can never disagree about capabilities again."""
        from dyflow.compile.node_runtime import NodeRuntime

        return NodeRuntime(
            model=model,
            tools=tool_registry_for(slug),
            functions=build_function_registry(workflow_store, slug),
            document_loader=lambda child_slug: _document_of(workflow_store.load(child_slug)),
            registry_loader=lambda child_slug: (
                tool_registry_for(child_slug),
                build_function_registry(workflow_store, child_slug),
            ),
            store=memory_store,
            skills_context=(
                discover_skills(workflow_store.directory_for(slug)) if slug else ""
            ),
            workflow_middleware=(
                discover_middlewares(workflow_store.directory_for(slug), slug) if slug else {}
            ),
        )
    from dyflow.api.capability_discovery import discover_middlewares, discover_skills
    from dyflow.memory import build_store, checkpointer_for

    #: Long-term memory, process-wide (ticket 65): one Store shared by every
    #: run, namespaced per user inside the tools themselves.
    memory_store = build_store()

    app = FastAPI(title="Dyflow runtime", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type"],
    )

    @app.get("/chat", include_in_schema=False)
    def chat_page() -> Any:
        """The customer chat surface (ticket 64) — one self-contained page."""
        from fastapi.responses import HTMLResponse

        from dyflow.api.chat_page import CHAT_PAGE

        return HTMLResponse(CHAT_PAGE)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        # Always true now: Ollama cloud is the default, not an opt-in, so
        # `resolve_model` never fails to name *a* model. Kept in the response
        # rather than removed, since the frontend already reads this field
        # and a provider actually being reachable is a separate question this
        # endpoint was never answering anyway.
        return {"ok": True, "model_configured": True}

    @app.get("/api/workflows", response_model=list[WorkflowSummaryResponse])
    def list_workflows() -> list[WorkflowSummaryResponse]:
        from dyflow.api.workflow_store import WorkflowSummary

        def to_response(s: WorkflowSummary) -> WorkflowSummaryResponse:
            return WorkflowSummaryResponse(
                slug=s.slug, name=s.name, saved_at=s.saved_at,
                node_count=s.node_count, edge_count=s.edge_count,
            )

        return [to_response(s) for s in workflow_store.list()]

    @app.get("/api/workflows/{slug}", response_model=WorkflowDocumentResponse)
    def get_workflow(slug: str) -> WorkflowDocumentResponse:
        from dyflow.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            document = workflow_store.load(slug)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return WorkflowDocumentResponse(slug=slug, document=document)

    @app.put("/api/workflows/{slug}", response_model=WorkflowDocumentResponse)
    def save_workflow(slug: str, request: SaveWorkflowRequest) -> WorkflowDocumentResponse:
        from datetime import datetime, timezone

        from dyflow.api.workflow_store import InvalidSlugError

        try:
            workflow_store.save(
                slug,
                name=request.name,
                document=request.document,
                saved_at=datetime.now(timezone.utc).isoformat(),
            )
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return WorkflowDocumentResponse(slug=slug, document=request.document)

    @app.delete("/api/workflows/{slug}", status_code=204)
    def delete_workflow(slug: str) -> None:
        from dyflow.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            workflow_store.delete(slug)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/workflows/{slug}/capabilities", response_model=CapabilitiesResponse)
    def get_capabilities(slug: str) -> CapabilitiesResponse:
        """Ticket 18: what a workflow's own `tools/`/`functions/` folders
        offer, discovered by importing them — not a static registration.

        Requires the workflow to already be saved (so its directory exists);
        an unsaved, canvas-only workflow has no folder to scan yet.
        """
        from dyflow.api.capability_discovery import discover_functions, discover_tools
        from dyflow.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            workflow_dir = workflow_store.directory_for(slug)
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not workflow_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from WorkflowNotFoundError(slug)

        tools = discover_tools(workflow_dir, slug=slug)
        functions = discover_functions(workflow_dir, slug=slug)
        return CapabilitiesResponse(
            tools=[
                ToolCapabilityResponse(id=t.id, name=t.name, description=t.description, args_schema=t.args_schema, node_type=t.node_type)
                for t in tools
            ],
            functions=[
                FunctionCapabilityResponse(id=f.id, name=f.name, docstring=f.docstring, signature=f.signature)
                for f in functions
            ],
        )

    @app.get("/api/workflows/{slug}/graph")
    def compiled_graph(slug: str) -> dict[str, str]:
        """The COMPILED topology as Mermaid text (ticket 54) — what the
        compiler actually produced, not a hand-drawn approximation.

        `xray=True` expands subgraph internals (a concierge shows its routed
        children; a Team shows its members), which is also the cheap half of
        the editor's dual-view ask (ticket 68). Text, never a PNG —
        `draw_mermaid_png()` posts the graph to a third-party API.
        """
        from dyflow.api.workflow_store import InvalidSlugError, WorkflowNotFoundError
        from dyflow.compile.node_runtime import NodeRuntime, RunState
        from dyflow.compile.workflow_compiler import WorkflowCompiler

        try:
            document = workflow_store.load(slug)
        except WorkflowNotFoundError:
            raise HTTPException(status_code=404, detail=f"No workflow '{slug}'")
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        runtime = runtime_for(slug, document, None)
        compiler = WorkflowCompiler()
        try:
            graph = compiler.build(
                document, RunState, runtime.factory(document), store=memory_store
            )
            mermaid_text = graph.get_graph(xray=True).draw_mermaid()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")
        return {"mermaid": mermaid_text}

    @app.post("/api/runs", response_model=RunResponse)
    def run_workflow(request: RunRequest) -> RunResponse:
        """Compiles and runs a canvas-authored workflow."""
        from dyflow.compile.node_runtime import NodeRuntime, RunState
        from dyflow.compile.workflow_compiler import WorkflowCompiler

        # Ollama cloud is the default (see `resolve_model`), so a model is
        # always resolved here — never `None`. A document with no
        # model-calling node still runs fine; `init_chat_model` builds a
        # client lazily and nothing calls it until an agent/worker node does.
        from dyflow.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        document = _document_of(request.workflow)
        # Model precedence: explicit request > the document's own
        # settings.model > environment default. A workflow that names its
        # model runs the same everywhere it is opened.
        model = init_chat_model(resolve_model(request.model or workflow_default_model(document)))

        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = runtime_for(request.workflow_slug, document, model)

        try:
            graph = compiler.build(document, RunState, runtime.factory(document), store=memory_store)
            final = graph.invoke(
                {"question": request.question, "attempts": 0, "decisions": {}, "outputs": {}},
                {"recursion_limit": request.recursion_limit},
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

        warnings = list(plan.warnings) + runtime_warnings(runtime)

        return RunResponse(
            answer=str(final.get("answer") or ""),
            decisions={k: str(v) for k, v in (final.get("decisions") or {}).items()},
            outputs={k: str(v) for k, v in (final.get("outputs") or {}).items()},
            attempts=int(final.get("attempts") or 0),
            mermaid=graph.get_graph().draw_mermaid(),
            warnings=warnings,
        )

    @app.post("/api/runs/stream")
    def run_workflow_stream(request: RunRequest) -> StreamingResponse:
        """The same run as `/api/runs`, surfaced as it happens.

        Ticket 27's sidebar needs to show **which node is currently in
        charge**, live — not just the final answer — and dynamically
        dispatched worker instances need to appear as they are created. A
        single blocking `/api/runs` response cannot do either: everything
        arrives at once, after the fact.

        `stream_mode=["updates", "messages"]` with `subgraphs=True` is what
        the docs (and ticket 27's own notes) call mandatory for streaming a
        graph containing an *actual* nested subgraph — without it, an inner
        graph's tokens never surface. Verified directly against the installed
        LangGraph before writing this, against **both** shapes: a nested
        subgraph does get its own `namespace_tuple`, but a `Send`-dispatched
        worker does not — every concurrently dispatched instance of the same
        static worker node reports `namespace: ()`, because `Send` fans out
        *tasks* against one node, not separate subgraphs. So `namespace`
        alone cannot tell two dispatched worker instances apart; the task id
        pulled from `worker_results` below is what actually does that.
        `subgraphs=True` is kept anyway, both for correctness if a future
        node type nests a real subgraph and because it costs nothing when
        there is none.

        No second LLM run to compute the final answer: the same reducers
        `RunState` declares (`keep_latest_nonempty`, `merge_decisions`) are
        applied here, by hand, to fold the incremental `updates` payloads into
        the same shape `/api/runs` returns — replicating the *documented*
        reducer, not reimplementing new logic, so the two endpoints cannot
        silently disagree about what "the final answer" means.
        """
        from dyflow.compile.node_runtime import (
            NodeRuntime,
            RunState,
            keep_latest_nonempty,
            merge_decisions,
        )
        from dyflow.compile.workflow_compiler import WorkflowCompiler, safe_name

        # Ollama cloud is the default (see `resolve_model`) — a model is
        # always resolved, never `None`.
        from dyflow.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        document = _document_of(request.workflow)
        model = init_chat_model(resolve_model(request.model or workflow_default_model(document)))

        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = runtime_for(request.workflow_slug, document, model)

        try:
            graph = compiler.build(
                document,
                RunState,
                runtime.factory(document),
                checkpointer=checkpointer_for(
                    document.get("settings"), request.workflow_slug, _HUMAN_IN_THE_LOOP_CHECKPOINTER
                ),
                store=memory_store,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

        # LangGraph node names are `safe_name(node_id)` (colons are illegal),
        # so events are translated back to the canvas's own ids — otherwise
        # the sidebar could not tell the frontend which node to highlight.
        node_ids_by_name = {safe_name(n): n for n in plan.nodes}
        thread_id = request.thread_id or f"run-{id(graph)}-{os.urandom(4).hex()}"
        config = {
            "recursion_limit": request.recursion_limit,
            "configurable": {
                "thread_id": thread_id,
                "session_id": request.session_id or "",
                "user_email": request.user_email or "",
            },
        }
        graph_input = {
            "question": request.question,
            "attempts": 0,
            "decisions": {},
            "outputs": {},
        }

        return StreamingResponse(
            _stream_run(graph, graph_input, config, plan, node_ids_by_name, runtime, thread_id),
            media_type="text/event-stream",
        )

    @app.post("/api/runs/resume")
    def resume_workflow_stream(request: ResumeRequest) -> StreamingResponse:
        """Continues a run a `human.approval` node paused (see `NodeRuntime._human_approval`).

        Same event vocabulary as `/api/runs/stream` (`_stream_run`) — a
        resumed run is not a different kind of thing from the frontend's
        point of view, it is the same stream picking back up, so it reuses
        the identical parsing code on the client rather than needing a
        second one.

        Requires the *same* `thread_id` the original run's `interrupt` event
        carried — this is what tells the shared checkpointer
        (`_HUMAN_IN_THE_LOOP_CHECKPOINTER`) which paused run to continue.
        """
        from dyflow.compile.node_runtime import NodeRuntime, RunState
        from dyflow.compile.workflow_compiler import WorkflowCompiler, safe_name
        from langgraph.types import Command

        from dyflow.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        document = _document_of(request.workflow)
        model = init_chat_model(resolve_model(request.model or workflow_default_model(document)))

        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = runtime_for(request.workflow_slug, document, model)

        try:
            graph = compiler.build(
                document,
                RunState,
                runtime.factory(document),
                checkpointer=checkpointer_for(
                    document.get("settings"), request.workflow_slug, _HUMAN_IN_THE_LOOP_CHECKPOINTER
                ),
                store=memory_store,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

        node_ids_by_name = {safe_name(n): n for n in plan.nodes}
        config = {
            "recursion_limit": request.recursion_limit,
            "configurable": {
                "thread_id": request.thread_id,
                "session_id": request.session_id or "",
                "user_email": request.user_email or "",
            },
        }
        resume_value: dict[str, Any] = {"decision": request.decision}
        if request.feedback:
            resume_value["feedback"] = request.feedback

        return StreamingResponse(
            _stream_run(
                graph,
                Command(resume=resume_value),
                config,
                plan,
                node_ids_by_name,
                runtime,
                request.thread_id,
            ),
            media_type="text/event-stream",
        )

    @app.post("/api/workflows/chinook-nl-to-sql/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        model = resolve_model(request.model)
        graph = factory(model)

        try:
            final = graph.invoke(
                {"question": request.question, "attempts": 0},
                # A standalone config key — putting it inside `configurable`
                # silently does nothing, which is the common mistake.
                {"recursion_limit": request.recursion_limit},
            )
        except Exception as exc:
            # Includes GraphRecursionError. The graph guards against runaway
            # loops itself, so reaching here means something else went wrong.
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

        verdict = final.get("verdict") or {"passed": True, "reason": ""}
        return AskResponse(
            answer=final.get("answer", ""),
            sql=final.get("sql", ""),
            rows=final.get("rows", ""),
            attempts=final.get("attempts", 0),
            passed=bool(verdict.get("passed")),
            reason=str(verdict.get("reason", "")),
        )

    return app


def _coerce_update(raw: Any) -> dict[str, Any]:
    """A node's contribution to one `updates`-mode chunk, defensively.

    Found live, mid-run, not in any fixture: once `subgraphs=True` is on,
    LangGraph auto-detects a nested graph invoked *synchronously inside* a
    plain node (the worker's `create_agent` call, the deep grader's
    `create_deep_agent` call) and surfaces its own internal steps in the
    same stream. Some of those steps contribute `None` rather than `{}` for
    "nothing to report this tick" — every `.get()` on a raw chunk value
    must go through this first, or the ones that changed it call directly
    crash on `'NoneType' object has no attribute 'get'`.
    """
    return raw if isinstance(raw, dict) else {}


def _sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event frame: an `event:` line, a `data:` line, blank line.

    `json.dumps` rather than string interpolation, because a node's output can
    contain newlines and quotes, and SSE's `data:` line is newline-delimited —
    an unescaped newline would silently split one event into two.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_run(
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
    plan: Any,
    node_ids_by_name: dict[str, str],
    runtime: Any,
    thread_id: str,
) -> Any:
    """Drives one `graph.stream()` call and yields SSE frames.

    Shared by `/api/runs/stream` (a fresh run) and `/api/runs/resume` (a
    run a `human.approval` node paused) — from the frontend's point of
    view a resume is not a different kind of thing, it is the same stream
    picking back up with a `Command(resume=...)` for `graph_input` instead
    of the initial state dict, so both endpoints reuse this one generator
    and the client's SSE parsing never needs to know which one it got.

    After the stream ends, `graph.get_state(config).next` tells apart "the
    run actually finished" (empty — nothing left scheduled) from "a
    `human.approval` node paused it" (non-empty — LangGraph does not raise
    or emit an `updates` chunk for the interrupted node itself, since it
    never completed; the loop above just stops, indistinguishable from a
    normal finish without this check).
    """
    from dyflow.compile.node_runtime import keep_latest_nonempty, merge_decisions

    answer = ""
    decisions: dict[str, str] = {}
    outputs: dict[str, str] = {}
    attempts = 0

    try:
        stream = graph.stream(
            graph_input,
            config,
            stream_mode=["updates", "messages"],
            subgraphs=True,
        )
        for namespace, mode, payload in stream:
            if mode == "updates":
                for raw_name, raw_update in payload.items():
                    update = _coerce_update(raw_update)
                    node_id = node_ids_by_name.get(raw_name, raw_name)
                    answer = keep_latest_nonempty(answer, str(update.get("answer") or ""))
                    decisions = merge_decisions(
                        decisions, {k: str(v) for k, v in (update.get("decisions") or {}).items()}
                    )
                    outputs = merge_decisions(
                        outputs, {k: str(v) for k, v in (update.get("outputs") or {}).items()}
                    )
                    if "attempts" in update:
                        attempts = int(update["attempts"])
                    task_ids = list((update.get("worker_results") or {}).keys())
                    # Internal frames — `model`, `tools`, a middleware's own
                    # node — are real LangGraph steps inside an agent's
                    # compiled loop, but not canvas nodes. They are emitted
                    # *tagged* (`internal: true`) rather than dropped: the
                    # flat activity feed ignores them, and the trace tree
                    # (ticket 63) nests them under their owning canvas node —
                    # which is exactly where a LangSmith-style view wants
                    # them.
                    is_internal = node_id not in node_ids_by_name.values()
                    yield _sse(
                        "update",
                        {
                            "node": node_id,
                            "namespace": list(namespace),
                            "taskId": task_ids[0] if task_ids else None,
                            "internal": is_internal,
                            "output": (update.get("outputs") or {}).get(node_id)
                            or (update.get("worker_results") or {}).get(
                                task_ids[0] if task_ids else "", None
                            ),
                        },
                    )
            elif mode == "messages":
                message, metadata = payload
                content = getattr(message, "content", "")
                if isinstance(content, str) and content:
                    raw_name = metadata.get("langgraph_node", "")
                    yield _sse(
                        "token",
                        {
                            "node": node_ids_by_name.get(raw_name, raw_name),
                            "namespace": list(namespace),
                            "content": content,
                        },
                    )
    except Exception as exc:  # noqa: BLE001 — reported to the client, not swallowed
        yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})
        return

    snapshot = graph.get_state(config)
    if snapshot.next:
        interrupts = snapshot.tasks[0].interrupts if snapshot.tasks else ()
        payload_value = interrupts[0].value if interrupts else {}
        yield _sse(
            "interrupt",
            {
                "threadId": thread_id,
                "message": (payload_value or {}).get("message", "Approval needed"),
                "candidate": (payload_value or {}).get("candidate", ""),
            },
        )
        return

    warnings = list(plan.warnings) + runtime_warnings(runtime)

    yield _sse(
        "done",
        {
            "answer": answer,
            "decisions": decisions,
            "outputs": outputs,
            "attempts": attempts,
            "mermaid": graph.get_graph().draw_mermaid(),
            "warnings": warnings,
        },
    )


#: For `uvicorn dyflow.api.main:app --reload`.
app = create_app()

__all__ = [
    "OLLAMA_CLOUD_MODEL",
    "AskRequest",
    "AskResponse",
    "RunRequest",
    "RunResponse",
    "app",
    "create_app",
    "resolve_model",
]
