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
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# `basicConfig` is a no-op if the root logger already has handlers (e.g. under
# pytest, or when `uvicorn --log-config` sets its own), so this is safe to call
# unconditionally rather than guessing whether we're the entrypoint.
logging.basicConfig(level=os.getenv("OPENSTATEGRAPH_LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

#: Where the editor dev server runs. Explicit, not `*` — the API will hold keys.
ALLOWED_ORIGINS = ["http://localhost:5273", "http://127.0.0.1:5273"]

# Human-in-the-loop's prerequisite — `interrupt()` requires the compiled graph
# to have a checkpointer, or LangGraph raises at compile time — used to be a
# module-level `InMemorySaver` right here. It is gone (ticket 05): the saver
# lives on `WorkflowServices` like every other shared collaborator, so HTTP,
# MCP and `load_workflow` reach the same one, a test can scope it, and a
# paused approval outlives the process that paused it. `create_app` resolves
# it at startup and logs where it landed.
from openstategraph.api.model_resolution import (  # noqa: E402, F401  (re-exported for tests)
    OLLAMA_CLOUD_MODEL,
    GraphFactory,
    apply_credentials,
    resolve_model,
    workflow_default_model,
)
from openstategraph.api.editor_assets import mount_editor  # noqa: E402
from openstategraph.api.registries import (  # noqa: E402, F401  (re-exported for tests)
    build_tool_registry,
    runtime_warnings,
)
from openstategraph.schema import normalize_document  # noqa: E402
from openstategraph.api.schemas import (  # noqa: E402
    AskRequest,
    AskResponse,
    CapabilitiesResponse,
    FunctionCapabilityResponse,
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeTopicDocResponse,
    KnowledgeTopicSaveRequest,
    KnowledgeTopicStatusResponse,
    PluginExportResponse,
    PublishWorkflowRequest,
    PublishWorkflowResponse,
    ResumeRequest,
    RunRequest,
    RunResponse,
    SaveWorkflowRequest,
    TemplateResponse,
    PluginToolCapabilityResponse,
    ToolCapabilityResponse,
    ToolFieldResponse,
    WorkflowDocumentResponse,
    WorkflowSummaryResponse,
)
from openstategraph.api.catalogue_events import (  # noqa: E402
    KEEPALIVE_SECONDS,
    CatalogueEvent,
    ChangeReason,
)
from openstategraph.api.streaming import (  # noqa: E402, F401  (underscored names re-exported for tests)
    _coerce_update,
    _sse,
    _stream_run,
    stop_when_client_leaves,
    stop_when_client_leaves_async,
)

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
    from openstategraph.api.services import WorkflowServices

    factory = graph_factory or _default_factory

    # The store, the process-wide memory Store and the one NodeRuntime
    # construction live on a collaborator (`api/services.py`) rather than in
    # closures here, because the MCP transport needs exactly the same assembly
    # without starting FastAPI. Same objects, same behaviour — the local names
    # below are kept so every endpoint reads as it did.
    services = WorkflowServices(workflows_root)
    workflow_store = services.store
    memory_store = services.memory_store
    runtime_for = services.runtime_for

    # Resolved at startup, not on the first approval: the one line it logs
    # ("approvals persist at X" / "approvals are in-memory and will NOT survive
    # a restart") has to reach the operator *before* anyone can lose work. The
    # value is not bound to a name — every endpoint now asks
    # `services.checkpointer_for(...)`, which resolves this same property.
    services.checkpointer

    app = FastAPI(title="OpenStateGraph runtime", version="0.1.0")
    #: The assembly point, reachable for ops and tests. Not a second wiring
    #: path — every endpoint below still goes through the local names above.
    app.state.services = services
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
        """Mermaid for the /chat live-flow view (ticket 68) — never a CDN.

        Two homes, one behaviour: the wheel carries its own copy as package
        data (scale-and-adopt ticket 01, `hatch_build.py`), and a checkout
        serves the repo's own `node_modules` so the page cannot version-skew
        against the editor's copy. A checkout with no `npm install` still 404s
        here, and `/chat` degrades to "flow view unavailable" rather than
        breaking.
        """
        from fastapi.responses import FileResponse

        from openstategraph.api.editor_assets import PACKAGED_MERMAID

        asset = PACKAGED_MERMAID
        if not asset.is_file():
            asset = Path(__file__).resolve().parent.parent.parent.parent / (
                "node_modules/mermaid/dist/mermaid.min.js"
            )
        if not asset.is_file():
            raise HTTPException(status_code=404, detail="mermaid asset not installed")
        return FileResponse(asset, media_type="text/javascript")

    def announce(reason: ChangeReason, slug: str) -> None:
        """Say that the catalogue changed. Called **after** a change succeeded.

        One call per real mutation (save, publish/unpublish, delete) and never
        on a read — an event that fires when nothing moved trains every client
        to ignore it. `surface_visible` is recomputed from the store rather
        than inferred from the request, because "is this on `/chat` now?" is
        the conjunction of `published` and `hidden` and only the store knows
        both; a deleted slug simply is not in the list, so it reports False
        without a special case. The extra directory scan is paid at
        human-click frequency.
        """
        visible = any(s.slug == slug for s in workflow_store.list(published_only=True))
        services.events.publish(
            CatalogueEvent(reason=reason, slug=slug, surface_visible=visible)
        )

    @app.get("/api/events")
    async def catalogue_events(http: Request) -> StreamingResponse:
        """Catalogue changes, live — `event: workflows.changed`.

        Why this exists: `/chat` fetched its picker once, on load, so a
        customer sitting on the page never saw a newly published workflow
        until they reloaded. The editor's Workflows panel had the same blind
        spot with respect to a second tab.

        **SSE, not WebSocket, not polling.** This process already speaks SSE
        (`/api/runs/stream`), the flow is one-way, and `EventSource` reconnects
        by itself. Framed by `_sse` — the one framer.

        The payload is a **hint, not a catalogue**: `{reason, slug,
        surface_visible}`. A client refetches `/api/workflows` on it, so there
        is exactly one spelling of the catalogue and it cannot go stale in a
        cache built from events.

        Limits, stated rather than discovered (full reasoning in
        `catalogue_events`): the fan-out is **in-process**, so it covers one
        worker — which is the documented ceiling (`uvicorn --workers 1`, for
        sqlite's per-instance write lock); a multi-worker deployment needs
        Redis pub/sub or Postgres LISTEN/NOTIFY behind the same
        publish/subscribe pair. And only writes **through this API** emit: a
        `workflow.json` hand-edited on disk or arriving by `git pull` produces
        nothing. A filesystem watch would close that gap and is recorded as
        future work rather than implied.
        """
        broadcaster = services.events

        async def frames() -> Any:
            # The subscription's lifetime IS this generator's: the `with` block
            # unsubscribes on a normal end, on a disconnect (the wrapper closes
            # this generator) and on a raise alike. Nothing has to remember to.
            with broadcaster.subscribe() as subscriber:
                # A first comment, immediately: it flushes response headers so
                # `EventSource` fires `onopen` now rather than whenever the
                # first change happens to occur — and the client's refetch on
                # open is what recovers anything missed while disconnected.
                yield ": connected\n\n"
                async for event in subscriber.events(idle_timeout=KEEPALIVE_SECONDS):
                    if event is None:
                        # Keepalive. An SSE comment: proxies and load balancers
                        # see bytes, `EventSource` ignores it, no client code
                        # needs to know it exists. Produced by the idle timeout
                        # on the wait rather than by a companion task, so there
                        # is no task that could outlive this connection.
                        yield ": keepalive\n\n"
                    else:
                        yield _sse("workflows.changed", event.as_dict())

        return StreamingResponse(
            # Wrapped for the same reason run streaming is: Starlette does not
            # notice a disconnect on a modern ASGI server, and a subscription
            # that outlives its socket is a leak that only shows up as an
            # overflow drop much later.
            stop_when_client_leaves_async(frames(), http.receive),
            media_type="text/event-stream",
            # Buffering an event stream defeats it; the hop-by-hop hint is the
            # conventional way to tell nginx not to.
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        # Always true now: Ollama cloud is the default, not an opt-in, so
        # `resolve_model` never fails to name *a* model. Kept in the response
        # rather than removed, since the frontend already reads this field
        # and a provider actually being reachable is a separate question this
        # endpoint was never answering anyway.
        return {"ok": True, "model_configured": True}

    @app.get("/api/templates", response_model=list[TemplateResponse])
    def list_templates(name: str = "New Workflow") -> list[TemplateResponse]:
        """The starting points, rendered — the same ones `openstategraph new`
        offers, from the same catalogue (scale-and-adopt ticket 04).

        `name` matters more than it looks: a template may put the display name
        *inside* the document (the team template titles its supervisor
        "<name> Lead"), so rendering server-side is what keeps the editor's
        result identical to the CLI's rather than approximately like it.

        A template is a scaffold input, so nothing here is a node type and no
        saved document ever refers back to one: this returns a document, and
        the template stops existing the moment it is imported.
        """
        from openstategraph import templates

        return [
            TemplateResponse(
                name=template.name,
                summary=template.summary,
                document=template.document(name),
            )
            for template in templates.catalogue()
        ]

    @app.get("/api/workflows", response_model=list[WorkflowSummaryResponse])
    def list_workflows(surface: Literal["editor", "chat"] = "editor") -> list[WorkflowSummaryResponse]:
        """Ticket 04 (launch-readiness): the listing is surface-aware.

        - ``surface=editor`` (default): everything non-hidden, drafts
          included, each row carrying its ``published`` flag.
        - ``surface=chat``: the customer surface — published AND not hidden
          only (hidden trumps published, enforced in the store).
        """
        from openstategraph.api.workflow_store import WorkflowSummary, validate_package

        def to_response(s: WorkflowSummary) -> WorkflowSummaryResponse:
            return WorkflowSummaryResponse(
                slug=s.slug, name=s.name, saved_at=s.saved_at,
                node_count=s.node_count, edge_count=s.edge_count,
                findings=validate_package(workflow_store.directory_for(s.slug)),
                published=s.published,
            )

        return [to_response(s) for s in workflow_store.list(published_only=surface == "chat")]

    @app.post("/api/workflows/{slug}/publish", response_model=PublishWorkflowResponse)
    def publish_workflow(slug: str, request: PublishWorkflowRequest) -> PublishWorkflowResponse:
        """Flip the draft→publish flag. One endpoint for both directions —
        the body's ``published`` bool IS the whole lifecycle state.

        Deliberately does NOT auto-run the knowledge model builder (knowledge
        builds are build-time-only, never a side effect); the note reminds
        the caller routing knowledge can be rebuilt.
        """
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            workflow_store.set_published(slug, request.published)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # After the store wrote, so a failed flip announces nothing.
        announce("published" if request.published else "unpublished", slug)
        return PublishWorkflowResponse(
            slug=slug,
            published=request.published,
            note=(
                "Concierge routing knowledge was not rebuilt automatically; "
                "rebuild it via POST /api/workflows/{root}/knowledge/build "
                "when routing should learn about this change."
            ),
        )

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
        announce("saved", slug)
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
        announce("deleted", slug)

    @app.get("/api/workflows/{slug}/capabilities", response_model=CapabilitiesResponse)
    def get_capabilities(slug: str) -> CapabilitiesResponse:
        """What this editor may put on a canvas, from all three sources.

        Ticket 18 covered the first: a workflow's own `tools/`/`functions/`
        folders, discovered by importing them rather than by registration.
        Register PK-06 adds the second — tools **installed distributions**
        contribute, which the runtime has been able to bind since ticket 05 and
        the editor had no way to show — and the honesty that goes with both:
        `warnings` carries every capability that failed to load, every plugin
        that replaced a built-in, and every Python tool that has no editor card
        at all (the half-authored case, which used to be pure silence).

        Requires the workflow to already be saved (so its directory exists);
        an unsaved, canvas-only workflow has no folder to scan yet.
        """
        from openstategraph.api.capability_discovery import discover_functions, discover_tools
        from openstategraph.api.plugin_capabilities import (
            bindable_tool_types,
            editor_renderable_types,
            plugin_tool_capabilities,
            unrenderable_tool_warning,
        )
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            workflow_dir = workflow_store.directory_for(slug)
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not workflow_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from WorkflowNotFoundError(slug)

        warnings: list[str] = []
        tools = discover_tools(workflow_dir, slug=slug, warnings=warnings)
        functions = discover_functions(workflow_dir, slug=slug)
        plugin_tools, plugin_warnings = plugin_tool_capabilities()
        warnings.extend(plugin_warnings)

        # A type is renderable if the editor ships a card for it (the generated
        # catalogue) or if this very payload describes it — a plugin's declared
        # fields and a workflow-local discovery both produce a card with no
        # TypeScript at all. Anything left is authored on one side only.
        declared = {t.node_type for t in tools if t.node_type} | {p.node_type for p in plugin_tools}
        half_authored = unrenderable_tool_warning(
            bindable=bindable_tool_types(),
            renderable=editor_renderable_types(),
            declared=declared,
        )
        if half_authored:
            warnings.append(half_authored)

        return CapabilitiesResponse(
            tools=[
                ToolCapabilityResponse(id=t.id, name=t.name, description=t.description, args_schema=t.args_schema, node_type=t.node_type)
                for t in tools
            ],
            functions=[
                FunctionCapabilityResponse(id=f.id, name=f.name, docstring=f.docstring, signature=f.signature)
                for f in functions
            ],
            plugin_tools=[
                PluginToolCapabilityResponse(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    args_schema=p.args_schema,
                    node_type=p.node_type,
                    distribution=p.distribution,
                    fields=[ToolFieldResponse(**f) for f in p.fields],
                    replaces_builtin=p.replaces_builtin,
                )
                for p in plugin_tools
            ],
            warnings=warnings,
        )

    @app.get("/api/workflows/{slug}/plugin-export", response_model=PluginExportResponse)
    def export_workflow_as_plugin(slug: str) -> PluginExportResponse:
        """Preview this workflow package as an Agent Plugins v1 plugin.

        A GET writes nothing: it returns the manifest, the layout a caller
        would materialize, and the honest list of what does not survive the
        crossing. The verdict and the full mapping are in
        `docs/decisions/agent-plugins.md` — adopt-as-interop, never as our
        format, with all of their vocabulary confined to `plugin_interop.py`.
        """
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError
        from openstategraph.plugin_interop import InvalidPluginError, export_plugin

        try:
            workflow_dir = workflow_store.directory_for(slug)
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not workflow_dir.is_dir():
            raise HTTPException(
                status_code=404, detail=f"No workflow named {slug!r}"
            ) from WorkflowNotFoundError(slug)
        try:
            export = export_plugin(workflow_dir)
        except InvalidPluginError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return PluginExportResponse(
            manifest=export.manifest, paths=sorted(export.files), notes=export.notes
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
                workflow_dir,
                document,
                model,
                workflow_store.root,
                source=request.source,
                instruction=request.instruction,
            )
        except knowledge_build.UnknownSourceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not any(report[key] for key in ("written", "skipped", "collisions", "warnings")):
            raise HTTPException(
                status_code=422,
                detail=(
                    "No knowledge source found in this workflow — no SQL tool "
                    "node names a database, and it mounts no child workflows."
                ),
            )
        return KnowledgeBuildResponse(**report)

    def _knowledge_context(slug: str) -> tuple[Path, dict[str, Any]]:
        """Shared loader for the curation endpoints: the package dir and the
        document (the document is what staleness recomputes briefs from)."""
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            document = workflow_store.load(slug)
            workflow_dir = workflow_store.directory_for(slug)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return workflow_dir, document

    @app.get(
        "/api/workflows/{slug}/knowledge",
        response_model=list[KnowledgeTopicStatusResponse],
    )
    def list_knowledge(slug: str) -> list[KnowledgeTopicStatusResponse]:
        """The curation list: every topic with its hint, ownership state
        (generated vs claimed) and stale badge — the Knowledge card's data."""
        from openstategraph.api import knowledge_curation

        workflow_dir, document = _knowledge_context(slug)
        return [
            KnowledgeTopicStatusResponse(
                name=s.name, hint=s.hint, generated=s.generated, source=s.source, stale=s.stale
            )
            for s in knowledge_curation.list_topics(workflow_dir, document, workflow_store.root)
        ]

    @app.get(
        "/api/workflows/{slug}/knowledge/{topic}",
        response_model=KnowledgeTopicDocResponse,
    )
    def read_knowledge_topic(slug: str, topic: str) -> KnowledgeTopicDocResponse:
        from openstategraph.api import knowledge_curation

        workflow_dir, document = _knowledge_context(slug)
        try:
            body = knowledge_curation.read_topic(workflow_dir, topic)
        except knowledge_curation.UnknownTopicPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No knowledge topic {topic!r}") from exc
        status = next(
            (
                s
                for s in knowledge_curation.list_topics(workflow_dir, document, workflow_store.root)
                if s.name == topic
            ),
            None,
        )
        return KnowledgeTopicDocResponse(
            name=topic,
            body=body,
            generated=status.generated if status else False,
            source=status.source if status else "",
            stale=status.stale if status else False,
        )

    @app.put(
        "/api/workflows/{slug}/knowledge/{topic}",
        response_model=KnowledgeTopicDocResponse,
    )
    def save_knowledge_topic(
        slug: str, topic: str, request: KnowledgeTopicSaveRequest
    ) -> KnowledgeTopicDocResponse:
        """Explicit save with the auto-claim: saving strips the generated
        marker (human touch = human ownership) and records the claim-time
        source hash, so the stale badge outlives the claim. No autosave —
        the file lands in git, diffable."""
        from openstategraph.api import knowledge_curation

        workflow_dir, document = _knowledge_context(slug)
        try:
            status = knowledge_curation.save_topic(
                workflow_dir, topic, request.body, document, workflow_store.root
            )
        except knowledge_curation.UnknownTopicPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return KnowledgeTopicDocResponse(
            name=status.name,
            body=knowledge_curation.read_topic(workflow_dir, status.name),
            generated=status.generated,
            source=status.source,
            stale=status.stale,
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

        document = normalize_document(request.workflow)
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
    def run_workflow_stream(request: RunRequest, http: Request) -> StreamingResponse:
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

        document = normalize_document(request.workflow)
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
                checkpointer=services.checkpointer_for(
                    document.get("settings"), request.workflow_slug
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
            # Wrapped, never passed raw: `stop_when_client_leaves` is the
            # only thing that makes a client's Stop end the run rather than
            # merely stop watching it.
            stop_when_client_leaves(
                _stream_run(
                    graph, graph_input, config, plan, node_ids_by_name, runtime, thread_id
                ),
                http.receive,
            ),
            media_type="text/event-stream",
        )

    @app.post("/api/runs/resume")
    def resume_workflow_stream(request: ResumeRequest, http: Request) -> StreamingResponse:
        """Continues a run a `human.approval` node paused (see `NodeRuntime._human_approval`).

        Same event vocabulary as `/api/runs/stream` (`_stream_run`) — a
        resumed run is not a different kind of thing from the frontend's
        point of view, it is the same stream picking back up, so it reuses
        the identical parsing code on the client rather than needing a
        second one.

        Requires the *same* `thread_id` the original run's `interrupt` event
        carried — this is what tells the shared checkpointer
        (`WorkflowServices.checkpointer`) which paused run to continue. Since
        ticket 05 that saver is durable by default, so the thread survives the
        restart the dev stack performs on every file save; `thread_id` is
        therefore a *persistent* identity, and a client that reuses a fixed
        one across conversations will resume the old one rather than start a
        new one.
        """
        from openstategraph.compile.node_runtime import RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name
        from langgraph.types import Command

        from openstategraph.abc.router import BaseRouter  # noqa: F401  (import cost only)
        from langchain.chat_models import init_chat_model

        document = normalize_document(request.workflow)
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
                checkpointer=services.checkpointer_for(
                    document.get("settings"), request.workflow_slug
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
            stop_when_client_leaves(
                _stream_run(
                    graph,
                    Command(resume=resume_value),
                    config,
                    plan,
                    node_ids_by_name,
                    runtime,
                    request.thread_id,
                ),
                http.receive,
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

# No `__all__` here on purpose. In Python `__all__` reads as "this is the
# public surface", and this module is Tier 3 — internal, no stability
# guarantee (see `openstategraph/api/__init__.py`). The names it exported
# were the ones it hands its own siblings, and a third party would have read
# that as a promise. `openstategraph.__all__` and `openstategraph.abc` are
# the promises.


# --- One origin serves the whole product: editor at /, chat at /chat, API -----
# under /api. Off unless OPENSTATEGRAPH_SERVE_STATIC=1, so a host-run backend
# (scripts/dev.sh, pytest) behaves exactly as before — Vite serves the editor
# there. `openstategraph serve` and the container both set it; where the built
# files come from, and what to serve when nobody built them, is
# `api/editor_assets.py`'s single answer rather than a second serving path.
#
# Mounted LAST, after every route above is declared, so /api/*, /chat and
# /chat/mermaid.js still win — StaticFiles only sees what nothing else claimed.
mount_editor(app)
