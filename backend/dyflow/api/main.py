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
import os
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

#: Where the editor dev server runs. Explicit, not `*` — the API will hold keys.
ALLOWED_ORIGINS = ["http://localhost:5273", "http://127.0.0.1:5273"]

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
    app = FastAPI(title="Dyflow runtime", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type"],
    )

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
                ToolCapabilityResponse(id=t.id, name=t.name, description=t.description, args_schema=t.args_schema)
                for t in tools
            ],
            functions=[
                FunctionCapabilityResponse(id=f.id, name=f.name, docstring=f.docstring, signature=f.signature)
                for f in functions
            ],
        )

    @app.get("/api/workflows/chinook-nl-to-sql/graph")
    def graph_preview() -> dict[str, str]:
        """Mermaid **text**, never a PNG.

        `draw_mermaid_png()` posts the graph to the Mermaid.Ink API; this endpoint
        exists partly so the frontend is never tempted to.
        """
        from graph import build_graph, mermaid

        # A structural preview needs no model, so none is required to see it.
        def _noop(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        return {"mermaid": mermaid(build_graph(_noop, _noop))}

    @app.post("/api/runs", response_model=RunResponse)
    def run_workflow(request: RunRequest) -> RunResponse:
        """Compiles and runs a canvas-authored workflow."""
        from dyflow.compile.node_runtime import NodeRuntime, RunState, chinook_tool_registry
        from dyflow.compile.workflow_compiler import WorkflowCompiler

        # Ollama cloud is the default (see `resolve_model`), so a model is
        # always resolved here — never `None`. A document with no
        # model-calling node still runs fine; `init_chat_model` builds a
        # client lazily and nothing calls it until an agent/worker node does.
        from dyflow.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        model = init_chat_model(resolve_model(request.model))

        compiler = WorkflowCompiler()
        plan = compiler.plan(request.workflow)
        runtime = NodeRuntime(model=model, tools=chinook_tool_registry())

        try:
            graph = compiler.build(request.workflow, RunState, runtime.factory(request.workflow))
            final = graph.invoke(
                {"question": request.question, "attempts": 0, "decisions": {}, "outputs": {}},
                {"recursion_limit": request.recursion_limit},
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

        warnings = list(plan.warnings)
        for tool_type in runtime.unresolved_tools:
            # The agent ran without this tool. Saying so is the difference
            # between a wrong answer and an explained one.
            warnings.append(
                f'No implementation for tool "{tool_type}" — the agent ran without it, '
                "so its answer may not be grounded in that data source."
            )

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
            chinook_tool_registry,
            keep_latest_nonempty,
            merge_decisions,
        )
        from dyflow.compile.workflow_compiler import WorkflowCompiler, safe_name

        # Ollama cloud is the default (see `resolve_model`) — a model is
        # always resolved, never `None`.
        from dyflow.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        model = init_chat_model(resolve_model(request.model))

        compiler = WorkflowCompiler()
        plan = compiler.plan(request.workflow)
        runtime = NodeRuntime(model=model, tools=chinook_tool_registry())

        try:
            graph = compiler.build(request.workflow, RunState, runtime.factory(request.workflow))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

        # LangGraph node names are `safe_name(node_id)` (colons are illegal),
        # so events are translated back to the canvas's own ids — otherwise
        # the sidebar could not tell the frontend which node to highlight.
        node_ids_by_name = {safe_name(n): n for n in plan.nodes}

        def events():
            answer = ""
            decisions: dict[str, str] = {}
            outputs: dict[str, str] = {}
            attempts = 0

            try:
                stream = graph.stream(
                    {"question": request.question, "attempts": 0, "decisions": {}, "outputs": {}},
                    {"recursion_limit": request.recursion_limit},
                    stream_mode=["updates", "messages"],
                    subgraphs=True,
                )
                for namespace, mode, payload in stream:
                    if mode == "updates":
                        for raw_name, update in payload.items():
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
                            # `namespace` alone does not distinguish concurrent
                            # `Send` dispatches to the *same* static worker
                            # node — verified directly: unlike an actual
                            # nested subgraph, a `Send` task shares its
                            # parent's checkpoint namespace, so every
                            # dispatched instance reports `namespace: []`
                            # here. The task id from `worker_results` is what
                            # actually tells two dispatched instances apart.
                            task_ids = list((update.get("worker_results") or {}).keys())
                            yield _sse(
                                "update",
                                {
                                    "node": node_id,
                                    "namespace": list(namespace),
                                    "taskId": task_ids[0] if task_ids else None,
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

            warnings = list(plan.warnings)
            for tool_type in runtime.unresolved_tools:
                warnings.append(
                    f'No implementation for tool "{tool_type}" — the agent ran without it, '
                    "so its answer may not be grounded in that data source."
                )

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

        return StreamingResponse(events(), media_type="text/event-stream")

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


def _sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event frame: an `event:` line, a `data:` line, blank line.

    `json.dumps` rather than string interpolation, because a node's output can
    contain newlines and quotes, and SSE's `data:` line is newline-delimited —
    an unescaped newline would silently split one event into two.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
