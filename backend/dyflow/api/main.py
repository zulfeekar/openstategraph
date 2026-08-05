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

#: Surfaced on `/api/runs` and `/api/runs/stream` whenever a run completes
#: with no model resolved. Found necessary live: a workflow with no provider
#: configured runs *successfully* (router, grader and fan-out logic need no
#: model) but every agent/worker node returns immediately with nothing, which
#: without this warning is indistinguishable from a real bug — "no answer was
#: produced" reads the same whether the model failed or was never asked.
_NO_MODEL_WARNING = (
    "No model provider is configured on the runtime, so nodes that need one "
    "(AI Agent, Worker) produced no output. Set ANTHROPIC_API_KEY or "
    "OPENAI_API_KEY, set DYFLOW_USE_OLLAMA=1 for Ollama cloud, or pass a "
    "model explicitly."
)


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

    Raises rather than silently falling back to a provider the caller did not ask
    for — a surprise provider means a surprise bill and a surprise data path.
    """
    if requested:
        return requested
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic:claude-haiku-4-5"
    if os.getenv("OPENAI_API_KEY"):
        return "openai:gpt-4.1-mini"
    if os.getenv("OLLAMA_HOST") or os.getenv("DYFLOW_USE_OLLAMA"):
        # Cloud, not local. See OLLAMA_CLOUD_MODEL.
        return os.getenv("DYFLOW_OLLAMA_MODEL") or OLLAMA_CLOUD_MODEL
    raise HTTPException(
        status_code=503,
        detail=(
            "No model configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, set "
            "DYFLOW_USE_OLLAMA=1 to use Ollama cloud, or pass `model` in the request."
        ),
    )


#: Injectable so tests can exercise the HTTP layer without a provider.
GraphFactory = Callable[[str], Any]


def _default_factory(model: str) -> Any:
    from graph import build_live_graph

    return build_live_graph(model)


def create_app(graph_factory: GraphFactory | None = None) -> FastAPI:
    """Builds the app.

    A factory rather than a module-level singleton so tests get an isolated
    instance and can inject a stub graph.
    """
    factory = graph_factory or _default_factory
    app = FastAPI(title="Dyflow runtime", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "model_configured": _model_available()}

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

        # A model is optional here, unlike /ask: the compiler and the routing
        # fallbacks work without one, so a developer can check the *shape* of a
        # workflow before configuring a provider.
        model = None
        if request.model or _model_available():
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
        if model is None:
            warnings.append(_NO_MODEL_WARNING)
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

        model = None
        if request.model or _model_available():
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
            if model is None:
                warnings.append(_NO_MODEL_WARNING)
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


def _model_available() -> bool:
    return bool(
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("OLLAMA_HOST")
        or os.getenv("DYFLOW_USE_OLLAMA")
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
