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

import os
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

#: Where the editor dev server runs. Explicit, not `*` — the API will hold keys.
ALLOWED_ORIGINS = ["http://localhost:5273", "http://127.0.0.1:5273"]


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
        return "ollama:llama3.1:8b"
    raise HTTPException(
        status_code=503,
        detail=(
            "No model configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or set "
            "DYFLOW_USE_OLLAMA=1 for a local model, or pass `model` in the request."
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
    "AskRequest",
    "AskResponse",
    "RunRequest",
    "RunResponse",
    "app",
    "create_app",
    "resolve_model",
]
