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

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# `basicConfig` is a no-op if the root logger already has handlers (e.g. under
# pytest, or when `uvicorn --log-config` sets its own), so this is safe to call
# unconditionally rather than guessing whether we're the entrypoint.
logging.basicConfig(level=os.getenv("OPENSTATEGRAPH_LOG_LEVEL", "INFO"))
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


from openstategraph.api.model_resolution import (  # noqa: E402
    OLLAMA_CLOUD_MODEL,
    GraphFactory,
    apply_credentials,
    resolve_model,
    workflow_default_model,
)
from openstategraph.api.registries import (  # noqa: E402
    _document_of,
    build_function_registry,
    build_tool_registry,
    runtime_warnings,
    suggestible_tool_catalog,
)
from openstategraph.api.schemas import (  # noqa: E402
    AskRequest,
    AskResponse,
    CapabilitiesResponse,
    FunctionCapabilityResponse,
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    ResumeRequest,
    RunRequest,
    RunResponse,
    SaveWorkflowRequest,
    ToolCapabilityResponse,
    WorkflowDocumentResponse,
    WorkflowSummaryResponse,
)
from openstategraph.api.streaming import _coerce_update, _sse, _stream_run  # noqa: E402, F401  (underscored names re-exported for tests)

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
    from openstategraph.api.workflow_store import WorkflowStore

    factory = graph_factory or _default_factory
    workflow_store = WorkflowStore(root=workflows_root)

    def tool_registry_for(slug: str | None) -> dict[str, Any]:
        return build_tool_registry(workflow_store, slug)

    def runtime_for(
        slug: str | None, document: dict[str, Any], model: Any, *, advisor: bool = False
    ) -> Any:
        """One NodeRuntime construction shared by run/stream/resume, so the
        three endpoints can never disagree about capabilities again.

        `advisor` is the editor-only capability-gap flag: it turns the tool
        catalogue into an extra agent context block (see `advisor_context`).
        Passed per call rather than baked into the app, because the same
        process serves both the editor and `/chat` and only one of them may
        ever propose edits to the canvas."""
        from openstategraph.compile.node_runtime import NodeRuntime, PackageAssets, RuntimeServices

        return NodeRuntime(services=RuntimeServices(
            model=model,
            tools=tool_registry_for(slug),
            functions=build_function_registry(workflow_store, slug),
            document_loader=lambda child_slug: _document_of(workflow_store.load(child_slug)),
            package_loader=lambda child_slug: PackageAssets(
                tools=tool_registry_for(child_slug),
                functions=build_function_registry(workflow_store, child_slug),
                skills_context=discover_skills(workflow_store.directory_for(child_slug)),
                workflow_middleware=discover_middlewares(
                    workflow_store.directory_for(child_slug), child_slug
                ),
            ),
            store=memory_store,
            skills_context=(
                discover_skills(workflow_store.directory_for(slug)) if slug else ""
            ),
            workflow_middleware=(
                discover_middlewares(workflow_store.directory_for(slug), slug) if slug else {}
            ),
            advisor_catalog=(
                suggestible_tool_catalog(tool_registry_for(slug)) if advisor else ""
            ),
        ))
    from openstategraph.api.capability_discovery import discover_middlewares, discover_skills
    from openstategraph.memory import build_store, checkpointer_for

    #: Long-term memory, process-wide (ticket 65): one Store shared by every
    #: run, namespaced per user inside the tools themselves.
    memory_store = build_store()

    app = FastAPI(title="OpenStateGraph runtime", version="0.1.0")
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

        from openstategraph.api.chat_page import chat_page_html

        # Read per request, not the import-time constant: chat.html is not a
        # .py file, so uvicorn's reloader never picks up edits to it — a
        # cached constant serves stale markup until a coincidental restart.
        return HTMLResponse(chat_page_html())

    @app.get("/api/node-contracts")
    def node_contracts() -> dict[str, dict[str, str]]:
        """The LOCKED prompt sections per model-driven node type (ticket 31).

        Served from the Python ladder classes — the single source of truth —
        so the editor can show a developer what the machinery already says
        (read-only, beside their editable rules) instead of letting them
        duplicate or contradict it. The original RouterNode bug this
        prevents: an editable field pre-filled with the output contract,
        cleared by the first person who wrote their own rules.
        """
        from openstategraph.abc.agent import BaseAgentNode
        from openstategraph.abc.grader import BaseGrader
        from openstategraph.abc.orchestrator import BaseOrchestrator
        from openstategraph.abc.router import BaseRouter

        return {
            "agent.llm": {
                "preamble": BaseAgentNode.PREAMBLE,
                "contract": BaseAgentNode.OUTPUT_CONTRACT,
            },
            "route.classifier": {
                "preamble": BaseRouter.PREAMBLE,
                "contract": BaseRouter.OUTPUT_CONTRACT,
            },
            "route.grader": {
                "preamble": BaseGrader.PREAMBLE,
                "contract": BaseGrader.OUTPUT_CONTRACT,
            },
            "orchestrate.supervisor": {
                "preamble": BaseOrchestrator.PREAMBLE,
                "contract": BaseOrchestrator.OUTPUT_CONTRACT,
            },
        }

    @app.get("/chat/mermaid.js", include_in_schema=False)
    def chat_mermaid_asset() -> Any:
        """Mermaid for the /chat live-flow view (ticket 68) — served from the
        repo's own node_modules so the chat page stays CDN-free and cannot
        version-skew against the editor's copy."""
        from fastapi.responses import FileResponse

        asset = Path(__file__).resolve().parent.parent.parent.parent / (
            "node_modules/mermaid/dist/mermaid.min.js"
        )
        if not asset.is_file():
            raise HTTPException(status_code=404, detail="mermaid asset not installed")
        return FileResponse(asset, media_type="text/javascript")

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
        from openstategraph.api.workflow_store import WorkflowSummary, validate_package

        def to_response(s: WorkflowSummary) -> WorkflowSummaryResponse:
            return WorkflowSummaryResponse(
                slug=s.slug, name=s.name, saved_at=s.saved_at,
                node_count=s.node_count, edge_count=s.edge_count,
                findings=validate_package(workflow_store.directory_for(s.slug)),
            )

        return [to_response(s) for s in workflow_store.list()]

    @app.get("/api/workflows/{slug}", response_model=WorkflowDocumentResponse)
    def get_workflow(slug: str) -> WorkflowDocumentResponse:
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

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

        from openstategraph.api.workflow_store import InvalidSlugError

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
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

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
        from openstategraph.api.capability_discovery import discover_functions, discover_tools
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

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

    @app.post("/api/workflows/{slug}/knowledge/build", response_model=KnowledgeBuildResponse)
    def build_knowledge(slug: str, request: KnowledgeBuildRequest) -> KnowledgeBuildResponse:
        """'Build second brain' (knowledge layer): one doc per topic, written
        to `workflows/<slug>/knowledge/` by every registered builder whose
        source material exists in this workflow — SQL tables today, codebase
        and OpenAPI sources by registration (`knowledge_builders.BUILDERS`).

        Synchronous on purpose: topics are few (tables of a workflow's own
        databases), and the report is the button's feedback. Regeneration is
        safe — a doc without the generated marker is hand-authored and is
        skipped, never overwritten (see `knowledge_builders`' policy).
        """
        from openstategraph.api import knowledge_build
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            document = workflow_store.load(slug)
            workflow_dir = workflow_store.directory_for(slug)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Model precedence mirrors the run endpoints: explicit request >
        # document settings.model > environment default.
        model = knowledge_build.resolve_build_model(
            request.model or workflow_default_model(document), request.credentials
        )
        try:
            report = knowledge_build.run_build(
                workflow_dir, document, model, workflow_store.root, source=request.source
            )
        except knowledge_build.UnknownSourceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not report["written"] and not report["skipped"]:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No knowledge source found in this workflow — no SQL tool "
                    "node names a database file under workflows/."
                ),
            )
        return KnowledgeBuildResponse(**report)

    @app.get("/api/workflows/{slug}/graph")
    def compiled_graph(slug: str) -> dict[str, str]:
        """The COMPILED topology as Mermaid text (ticket 54) — what the
        compiler actually produced, not a hand-drawn approximation.

        `xray=True` expands subgraph internals (a concierge shows its routed
        children; a Team shows its members), which is also the cheap half of
        the editor's dual-view ask (ticket 68). Text, never a PNG —
        `draw_mermaid_png()` posts the graph to a third-party API.
        """
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError
        from openstategraph.compile.node_runtime import RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

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
        from openstategraph.compile.node_runtime import RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        # Ollama cloud is the default (see `resolve_model`), so a model is
        # always resolved here — never `None`. A document with no
        # model-calling node still runs fine; `init_chat_model` builds a
        # client lazily and nothing calls it until an agent/worker node does.
        from openstategraph.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        document = _document_of(request.workflow)
        # Browser-held keys, applied only where the server has none — see
        # `apply_credentials` for why the server's own env always wins.
        apply_credentials(request.credentials)
        # Model precedence: explicit request > the document's own
        # settings.model > environment default. A workflow that names its
        # model runs the same everywhere it is opened.
        model = init_chat_model(resolve_model(request.model or workflow_default_model(document)))

        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = runtime_for(request.workflow_slug, document, model, advisor=request.advisor)

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
        from openstategraph.compile.node_runtime import (
            RunState,
        )
        from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

        # Ollama cloud is the default (see `resolve_model`) — a model is
        # always resolved, never `None`.
        from openstategraph.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        document = _document_of(request.workflow)
        # Browser-held keys, fallback-only (see `apply_credentials`).
        apply_credentials(request.credentials)
        model = init_chat_model(resolve_model(request.model or workflow_default_model(document)))

        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = runtime_for(request.workflow_slug, document, model, advisor=request.advisor)

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
                "workflow_slug": request.workflow_slug or "",
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
        from openstategraph.compile.node_runtime import RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name
        from langgraph.types import Command

        from openstategraph.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        document = _document_of(request.workflow)
        # Browser-held keys, fallback-only (see `apply_credentials`).
        apply_credentials(request.credentials)
        model = init_chat_model(resolve_model(request.model or workflow_default_model(document)))

        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = runtime_for(request.workflow_slug, document, model, advisor=request.advisor)

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
                "workflow_slug": request.workflow_slug or "",
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


# --- Container-only: serve the built editor SPA from this same process. ------
# Off unless OPENSTATEGRAPH_SERVE_STATIC=1, so a host-run backend (scripts/dev.sh,
# pytest) behaves exactly as before — Vite serves the editor there. Mounted last
# and only at "/", so every route declared above (/api/*, /chat, /chat/mermaid.js)
# still wins; StaticFiles only sees what nothing else claimed. html=True serves
# index.html at "/" (it does not invent a catch-all for arbitrary deep links —
# the editor has no client-side router, so it does not need one).
if os.getenv("OPENSTATEGRAPH_SERVE_STATIC") == "1":
    _static_dir = Path(os.getenv("OPENSTATEGRAPH_STATIC_DIR", "dist"))
    if _static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=_static_dir, html=True), name="editor")
    else:
        logger.warning("OPENSTATEGRAPH_SERVE_STATIC=1 but %s is not a directory", _static_dir)
