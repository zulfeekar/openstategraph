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
def resolve_log_level(raw: str | None) -> int:
    """A logging level from a variable a person wrote by hand.

    This was `logging.basicConfig(level=os.getenv(...))`, which raises
    `ValueError: Unknown level: \'\'` on an **empty** assignment — and
    `OPENSTATEGRAPH_LOG_LEVEL=` is exactly what `.env.example` ships, so
    copying it to `.env` and running `serve` killed the server. It died
    *after* printing its URLs, so it read as a server that had started.

    Lowercase failed the same way, which is the more likely thing to type.

    Unrecognised falls back to the documented default rather than raising: a
    log level is not worth refusing to start over, and a server that will not
    boot tells you far less than one that boots at INFO.
    """
    level = (raw or "").strip().upper()
    if not level:
        return logging.INFO
    resolved = logging.getLevelName(level)
    return resolved if isinstance(resolved, int) else logging.INFO


logging.basicConfig(level=resolve_log_level(os.getenv("OPENSTATEGRAPH_LOG_LEVEL")))
logger = logging.getLogger(__name__)

#: Where the editor dev server runs. Explicit, not `*` — the API will hold keys.
ALLOWED_ORIGINS = ["http://localhost:5273", "http://127.0.0.1:5273"]

#: How a third-party browser client is let in (scale-and-adopt ticket 05).
#: Comma-separated origins, ADDED to the two above.
ALLOWED_ORIGINS_ENV = "OPENSTATEGRAPH_ALLOWED_ORIGINS"


class WildcardOriginError(ValueError):
    """`*` was asked for on an API that holds provider credentials."""


def allowed_origins(env: Any = None) -> list[str]:
    """The CORS allowlist for this process.

    "Build your own UI" was true for a server-side client and only
    accidentally true for a browser one: the list above is the editor's Vite
    dev origin, so anybody else's page was blocked with no way to say
    otherwise short of editing this file. `OPENSTATEGRAPH_ALLOWED_ORIGINS`
    is that way.

    Three properties, each deliberate:

    - **Additive.** A developer letting their own page in must not silently
      lock the editor out of the same server.
    - **Explicit, never `*`.** This process holds provider keys; a wildcard
      allowlist on a credential-holding API is how one key becomes
      everyone's. Asking for it *raises* rather than being dropped, because
      a silently ignored `*` leaves the developer believing their client is
      allowed until the browser says otherwise.
    - **Order preserved, duplicates dropped**, so the resulting list reads
      like what was configured.
    """
    raw = (env if env is not None else os.environ).get(ALLOWED_ORIGINS_ENV, "")
    origins = list(ALLOWED_ORIGINS)
    for candidate in (piece.strip() for piece in str(raw).split(",")):
        if not candidate:
            continue
        if candidate == "*":
            raise WildcardOriginError(
                f"{ALLOWED_ORIGINS_ENV} may not contain '*'. This process holds "
                "provider credentials, so every origin is named explicitly. "
                "List the origins your client is served from instead."
            )
        if candidate not in origins:
            origins.append(candidate)
    return origins

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
from openstategraph.api import auth  # noqa: E402
from openstategraph.api.audience import (  # noqa: E402
    resolve as resolve_audience,
)
from openstategraph.api.customer_graph import customer_mermaid
from openstategraph.api.audience import (
    Audience,
)
from openstategraph.api.editor_assets import mount_editor  # noqa: E402
from openstategraph.api.sse_contract import (  # noqa: E402, F401  (re-exported)
    STREAM_GUIDE,
    sse_responses,
)
from openstategraph.api.routes import providers as providers_routes  # noqa: E402
from openstategraph.api.routes import runs as runs_routes  # noqa: E402
from openstategraph.api.routes import threads as threads_routes  # noqa: E402
from openstategraph.api.registries import (  # noqa: E402, F401  (re-exported for tests)
    build_tool_registry,
    runtime_warnings,
)
from openstategraph.sql_reach import reachable_schema  # noqa: E402
from openstategraph.api.schemas import (  # noqa: E402
    AskRequest,
    AskResponse,
    CapabilitiesResponse,
    CompiledGraphResponse,
    FunctionCapabilityResponse,
    HealthResponse,
    NodeContractResponse,
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeTopicDocResponse,
    KnowledgeTopicSaveRequest,
    KnowledgeTopicStatusResponse,
    MountDocumentResponse,
    PluginExportResponse,
    DuplicateWorkflowRequest,
    DuplicateWorkflowResponse,
    PublishWorkflowRequest,
    PublishWorkflowResponse,
    SaveWorkflowRequest,
    SqlSchemaResponse,
    SqlSourceResponse,
    SqlTableResponse,
    TemplateResponse,
    PluginToolCapabilityResponse,
    ToolCapabilityResponse,
    ToolFieldResponse,
    ValidateRequest,
    ValidateResponse,
    WorkflowDocumentResponse,
    WorkflowSummaryResponse,
)
from openstategraph.api.catalogue_events import (  # noqa: E402
    CATALOGUE_EVENT,
    KEEPALIVE_SECONDS,
    CatalogueEvent,
    ChangeReason,
)
from openstategraph.api.workflow_store import (  # noqa: E402
    WorkflowSummary,
    validate_package,
)
from openstategraph.api.streaming import (  # noqa: E402, F401  (underscored names re-exported for tests)
    RUN_EVENTS,
    TERMINAL_EVENTS,
    _coerce_update,
    _sse,
    _stream_run,
    stop_when_client_leaves,
    stop_when_client_leaves_async,
)


# `STREAM_GUIDE` and `sse_responses` moved to `api/sse_contract.py` when the
# route handlers moved out of this factory: a router module has to decorate
# its own SSE endpoints, and importing them back from here would make the
# dependency a cycle (reviews-2026-08-14 ticket 15). Re-exported below because
# both names are read by tests and by `openapi_document`.


def _default_factory(model: str) -> Any:
    from graph import build_live_graph

    return build_live_graph(model)



def single_server_lifespan(services: Any) -> Any:
    """The startup guard that makes "one worker" true instead of documented.

    An exclusive lock on this deployment's state directory, taken when the app
    is actually *served* rather than when it is constructed — `create_app()` in
    a test or an embedder is not a second server, but a second uvicorn worker
    running lifespan is. `AnotherServerIsRunning` propagates: a worker that
    cannot have the state must not start with it, and uvicorn's own failure is
    louder than any log line we could write.

    See `openstategraph.deployment` for why the answer is refusal.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> Any:
        from openstategraph.deployment import SingleServerLock
        from openstategraph.state_dir import state_dir

        lock = SingleServerLock(state_dir(services.store.root))
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    return lifespan


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

    app = FastAPI(
        title="OpenStateGraph runtime",
        version="0.1.0",
        # Ticket 06: one process may serve one state directory, and this is
        # where that is enforced against `uvicorn --workers N` — the launcher
        # that leaves no trace in the environment for the CLI to refuse.
        lifespan=single_server_lifespan(services),
        summary="The HTTP surface both shipped UIs are built on.",
        description=(
            "Everything the canvas editor and `/chat` do goes through the "
            "endpoints below — there is no private API, so a third client is "
            "a supported thing to build rather than a reverse-engineering "
            "exercise.\n\n"
            "**Two parts of the contract are not in this document, and cannot "
            "be.** `POST /api/runs/stream`, `POST /api/runs/resume` and "
            f"`GET /api/events` are Server-Sent Event streams; OpenAPI has no "
            "vocabulary for a frame sequence, an event-name union, or the "
            "guarantee that exactly one of `done`/`interrupt`/`error` is the "
            f"last frame. Those are written out in `{STREAM_GUIDE}`, which is "
            "also where the five calls a custom chat actually needs are shown "
            "end to end.\n\n"
            "This document is generated from the app and committed at "
            "`docs/openapi.json`; the live one is served at `/openapi.json`."
        ),
    )
    #: The assembly point, reachable for ops and tests. Not a second wiring
    #: path — every endpoint below still goes through the local names above.
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        # `authorization` since ticket 06: with `OPENSTATEGRAPH_API_TOKEN` set,
        # a cross-origin client (the Vite dev editor on :5273, a custom UI on
        # its own host) sends the token in that header, and a preflight that
        # does not list it strips the only thing that gets the request in.
        allow_headers=["content-type", "authorization"],
    )
    # Added after CORS and therefore *outside* it (Starlette wraps the last
    # middleware added around everything before it), so a cross-origin request
    # is refused by the gate rather than allowed by a browser convention. CORS
    # is not an access control and must never be the outermost one.
    if auth.install(app):
        logger.info("authentication: on — shared token from %s", auth.API_TOKEN_ENV)
    else:
        logger.info(
            "authentication: off — every caller that can reach this port has full "
            "access. Set %s, or put a reverse proxy in front (docs/deploying.md).",
            auth.API_TOKEN_ENV,
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

    @app.get(
        "/api/node-contracts",
        response_model=dict[str, NodeContractResponse],
        summary="The locked prompt sections, per model-driven node type",
        tags=["Authoring"],
    )
    def node_contracts() -> dict[str, NodeContractResponse]:
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
            "agent.llm": NodeContractResponse(
                preamble=BaseAgentNode.PREAMBLE,
                contract=BaseAgentNode.OUTPUT_CONTRACT,
            ),
            "route.classifier": NodeContractResponse(
                preamble=BaseRouter.PREAMBLE, contract=BaseRouter.OUTPUT_CONTRACT
            ),
            "route.grader": NodeContractResponse(
                preamble=BaseGrader.PREAMBLE, contract=BaseGrader.OUTPUT_CONTRACT
            ),
            "orchestrate.supervisor": NodeContractResponse(
                preamble=BaseOrchestrator.PREAMBLE,
                contract=BaseOrchestrator.OUTPUT_CONTRACT,
            ),
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

    @app.get(
        "/api/events",
        summary="Catalogue changes, live (SSE)",
        response_class=StreamingResponse,
        responses=sse_responses((CATALOGUE_EVENT,), "One frame per catalogue change."),
        tags=["Catalogue"],
    )
    async def catalogue_events(http: Request) -> StreamingResponse:
        """Catalogue changes, live — `event: workflows.changed`.

        Not expressible in OpenAPI beyond its media type; the frame shape and
        the reconnect behaviour are in `docs/api.md`.

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
                        yield _sse(CATALOGUE_EVENT, event.as_dict())

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

    @app.get(
        "/api/health",
        response_model=HealthResponse,
        summary="Liveness, and whether a model name can be resolved",
        tags=["Operations"],
    )
    def health() -> HealthResponse:
        """Answers "is this process up?" and nothing more expensive.

        `model_configured` asks whether **any** registered provider has the
        environment it needs. It used to be the literal `True`, on the
        reasoning that Ollama was always available — which was itself the
        defect: Ollama reached the cloud through an ambient local daemon, so
        this reported ready on a machine with nothing configured and no daemon
        listening (providers-and-credentials ticket 02).

        Still cheap, and still not a reachability check: it reads environment
        variables and never opens a socket. A configured provider that is down
        is a different question, and one this endpoint has never answered.
        """
        from openstategraph.providers import provider_catalogue

        configured = any(spec.is_configured() for spec in provider_catalogue().list())
        return HealthResponse(ok=True, model_configured=configured)

    @app.get(
        "/api/templates",
        response_model=list[TemplateResponse],
        summary="The starting points a new workflow can be created from",
        tags=["Authoring"],
    )
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

    @app.get(
        "/api/workflows",
        response_model=list[WorkflowSummaryResponse],
        summary="List workflows — the first call any client makes",
        tags=["Catalogue"],
    )
    def list_workflows(surface: Literal["editor", "chat"] = "editor") -> list[WorkflowSummaryResponse]:
        """Ticket 04 (launch-readiness): the listing is surface-aware.

        - ``surface=editor`` (default): everything the developer owns —
          drafts AND hidden packages included, each row carrying its
          ``published`` and ``hidden`` flags so the editor can mark a hidden
          package rather than pretend it does not exist.
        - ``surface=chat``: the customer surface — published AND not hidden
          only (hidden trumps published, enforced in the store).

        **This answers visibility, never existence** (ticket 21). A slug's
        absence here means "no surface advertises it" — it may be hidden, or
        unreadable, and either way the file is still on disk and still served
        200 by `GET /api/workflows/{slug}`. Ask
        `GET /api/workflows/{slug}/summary` when the question is whether a
        package exists.
        """
        # The editor is the *developer's* surface, so it sees everything it
        # owns — hidden packages included, each row carrying `hidden` so the
        # UI can mark them rather than pretend they are not there. `hidden`
        # remains absolute for `surface="chat"`, which is the customer's.
        return [
            _summary_response(s)
            for s in workflow_store.list(
                published_only=surface == "chat",
                include_hidden=surface == "editor",
            )
        ]

    def _summary_response(s: WorkflowSummary) -> WorkflowSummaryResponse:
        return WorkflowSummaryResponse(
            slug=s.slug, name=s.name, saved_at=s.saved_at,
            node_count=s.node_count, edge_count=s.edge_count,
            findings=validate_package(workflow_store.directory_for(s.slug)),
            published=s.published, hidden=s.hidden,
        )

    @app.get(
        "/api/workflows/{slug}/summary",
        response_model=WorkflowSummaryResponse,
        summary="Does this workflow exist, and when was it last saved?",
        tags=["Catalogue"],
    )
    def get_workflow_summary(slug: str) -> WorkflowSummaryResponse:
        """One package's row — **the existence question** (ticket 21).

        `GET /api/workflows` is a *surface*: it omits hidden packages and
        unreadable ones by design, so a client that scans it for its own slug
        and concludes "deleted" on a miss is reading a visibility answer as an
        existence answer. That is exactly what the editor's file watch did, and
        why opening `concierge` (`hidden: true`, served 200) raised "This
        workflow was deleted on disk" while the file sat right there.

        This reports every package the store can name, hidden included, with
        `hidden` saying which. **404 is the only "it is gone"** — and it is
        real, so a stale open copy still gets its warning.
        """
        from openstategraph.api.workflow_store import InvalidSlugError

        try:
            summary = workflow_store.describe(slug)
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if summary is None:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}")
        return _summary_response(summary)

    @app.post(
        "/api/workflows/{slug}/duplicate",
        response_model=DuplicateWorkflowResponse,
        summary="Copy a workflow package to a new slug",
        tags=["Catalogue"],
    )
    def duplicate_workflow(slug: str, request: DuplicateWorkflowRequest) -> DuplicateWorkflowResponse:
        """Copy the whole package — `tools/`, `tests/`, `knowledge/`, all of it.

        **On the backend because the client cannot do it.** A browser can only
        load the document and create a new workflow from it, which copies
        `workflow.json` and leaves the nodes bound to tools that do not exist
        in the copy — a failure that surfaces at run time, long after the copy
        looked successful.

        The copy is a **draft** whatever the original was, and gets a minted
        slug it did not choose; see `WorkflowStore.duplicate` for why each.
        """
        from datetime import datetime, timezone

        from openstategraph.api.workflow_store import (
            InvalidSlugError,
            SlugMintingError,
            WorkflowNotFoundError,
        )

        try:
            existing = workflow_store.describe(slug)
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if existing is None:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}")

        # Defaulted here rather than in the client: the obvious name depends on
        # the original's, and a browser would have to fetch it first to say the
        # same thing.
        name = request.name or f"{existing.name} (copy)"
        try:
            created = workflow_store.duplicate(slug, name=name, saved_at=datetime.now(timezone.utc).isoformat())
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SlugMintingError as exc:
            raise HTTPException(status_code=507, detail=str(exc)) from exc

        # A new package exists, so the catalogue moved — same reason a create
        # announces. Announced for the *copy*: the original did not change.
        announce("saved", created)
        return DuplicateWorkflowResponse(slug=created, name=name, source=slug)

    @app.post(
        "/api/workflows/{slug}/publish",
        response_model=PublishWorkflowResponse,
        summary="Publish or unpublish a workflow",
        tags=["Catalogue"],
    )
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

    @app.get(
        "/api/workflows/{slug}",
        response_model=WorkflowDocumentResponse,
        summary="Fetch one workflow.json document",
        tags=["Catalogue"],
    )
    def get_workflow(slug: str) -> WorkflowDocumentResponse:
        """The vendor-neutral document itself — the thing a run takes as input.

        A client fetches this and posts it back to `/api/runs/stream`: the
        compile seam is one-directional and stateless per call, so the
        workflow that executes is the one the caller can read.
        """
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            document = workflow_store.load(slug)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return WorkflowDocumentResponse(slug=slug, document=document)

    @app.get(
        "/api/workflows/{root}/mounts/{path:path}",
        response_model=MountDocumentResponse,
        summary="Fetch the document one mounted instance actually runs",
        tags=["Catalogue"],
    )
    def get_mount_document(root: str, path: str, inherited: bool = False) -> MountDocumentResponse:
        """The effective document for one **instance** of a mounted workflow.

        A package is a class and a mount node is an instance of it, carrying
        its own `data.overrides`. `GET /api/workflows/concierge` returns the
        shared definition; this returns what the mount at `wf-music` runs,
        with that mount's overrides merged in — and `.../mounts/wf-music/wf-inner`
        walks on to a grandchild, applying each level in turn.

        Served rather than merged client-side on purpose: the merge has one
        owner (`apply_mount_overrides`), and a second implementation of it
        would be duplicated knowledge buying only a round trip.

        `?inherited=true` answers the neighbouring question: what this instance
        would run if it overrode nothing. That is what an inspector shows
        beside an overridden field, and what a revert restores — and it cannot
        be computed by the caller, because the override has already replaced
        the inherited value in the document above.

        The package on disk is never written — the merge exists only in the
        copy returned here, so the compile seam stays one-directional.
        """
        from openstategraph.api.mount_resolution import (
            MountResolutionError,
            resolve_mount_document,
        )
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        segments = path.split("/")
        if any(not segment for segment in segments):
            # **Refuse rather than repair**, because `MountAddress` does.
            # This used to filter empties out, so `parent//wf-music` resolved
            # happily over HTTP while `parseMountAddress` returned null for the
            # same string — one address grammar with two parsers and two
            # answers. The moment a mount id contains a character the two treat
            # differently, a link resolves to different instances by transport.
            #
            # 422 and not 404: this endpoint reserves 404 for an address that
            # is well-formed and names something absent ("this link is stale").
            # An empty segment is not stale, it is not an address.
            raise HTTPException(
                status_code=422,
                detail=f"{root}/{path} is not a mount address — a segment is empty",
            )
        try:
            resolved = resolve_mount_document(
                workflow_store, root, segments, inherited=inherited
            )
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {exc}") from exc
        except MountResolutionError as exc:
            # 404, not 422: the address is well-formed and simply names an
            # instance that is not there — the same answer a deleted workflow
            # gets, because a client renders both as "this link is stale".
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return MountDocumentResponse(
            root=root,
            slug=resolved.slug,
            mount_path=resolved.mount_path,
            document=resolved.document,
            warnings=resolved.warnings,
        )

    @app.post(
        "/api/workflows",
        response_model=WorkflowDocumentResponse,
        status_code=201,
        summary="Create a workflow — the backend mints its slug",
        tags=["Catalogue"],
    )
    def create_workflow(request: SaveWorkflowRequest) -> WorkflowDocumentResponse:
        """Bring a new workflow into existence and be **told which slug it got**.

        Ticket 20. A name is not unique, so a client that slugifies one and
        PUTs to the result is guessing: two workflows named "My Workflow" both
        guessed `my-workflow`, and the second overwrote the first with a 200.
        Only the process holding the workflows directory can mint an identity,
        so it does — the first of a name keeps the clean slug, a colliding one
        gets a short random disambiguator (`my-workflow-k7m3qp`), and the
        response's `slug` is the answer, never something to recompute.

        Use `PUT /api/workflows/{slug}` afterwards to save changes: that
        endpoint addresses a slug you already hold, and this one is how you
        come to hold it.
        """
        from datetime import datetime, timezone

        from openstategraph.api.workflow_store import SlugMintingError

        try:
            slug = workflow_store.create(
                name=request.name,
                document=request.document,
                saved_at=datetime.now(timezone.utc).isoformat(),
            )
        except SlugMintingError as exc:
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        announce("saved", slug)
        return WorkflowDocumentResponse(slug=slug, document=request.document)

    @app.put(
        "/api/workflows/{slug}",
        response_model=WorkflowDocumentResponse,
        summary="Overwrite the workflow document at a slug you already hold",
        tags=["Catalogue"],
    )
    def save_workflow(slug: str, request: SaveWorkflowRequest) -> WorkflowDocumentResponse:
        """Writes the package's `workflow.json` and stamps `saved_at`.

        The slug is the path parameter and is frozen at creation; the body
        carries the display name and the document, never the slug. Announces
        the change on `/api/events` **after** the write succeeded.

        **Addresses an existing package.** It still creates one if the slug is
        free — naming a directory explicitly is how the CLI and a test write a
        package they intend to own — but a client that does not yet have a
        slug must `POST /api/workflows` and be given one, because a slug it
        invented from a name may already belong to somebody else's workflow
        (ticket 20).
        """
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

    @app.delete(
        "/api/workflows/{slug}",
        status_code=204,
        summary="Delete a workflow package",
        tags=["Catalogue"],
    )
    def delete_workflow(slug: str) -> None:
        """Removes the package directory and announces it on `/api/events`.

        Returns 204 with no body — there is nothing left to describe. A
        deleted slug simply stops appearing in the listing.
        """
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            workflow_store.delete(slug)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
        except InvalidSlugError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        announce("deleted", slug)

    @app.get(
        "/api/workflows/{slug}/capabilities",
        response_model=CapabilitiesResponse,
        summary="Tools and functions this workflow may put on a canvas",
        tags=["Authoring"],
    )
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

    @app.get(
        "/api/workflows/{slug}/plugin-export",
        response_model=PluginExportResponse,
        summary="Preview this package as an Agent Plugins v1 plugin",
        tags=["Authoring"],
    )
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

    @app.post(
        "/api/workflows/{slug}/knowledge/build",
        response_model=KnowledgeBuildResponse,
        summary="Generate this workflow's knowledge docs",
        tags=["Knowledge"],
    )
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
                    "node names a database, it mounts no child workflows, and "
                    "it wires no platform tool that can see the project."
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
        summary="List this workflow's knowledge topics",
        tags=["Knowledge"],
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
        summary="Read one knowledge topic",
        tags=["Knowledge"],
    )
    def read_knowledge_topic(slug: str, topic: str) -> KnowledgeTopicDocResponse:
        """The raw Markdown of one topic, with its ownership and stale flags.

        `generated` says the builder still owns it; the first saved edit
        strips that marker forever (the auto-claim), and `stale` says the
        source it describes has changed since.
        """
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
        summary="Save one knowledge topic, claiming it from the builder",
        tags=["Knowledge"],
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

    @app.get(
        "/api/workflows/{slug}/sql-schema",
        response_model=SqlSchemaResponse,
        summary="The tables this workflow's SQL tools can actually reach",
        tags=["Workflows"],
    )
    def sql_schema(slug: str) -> SqlSchemaResponse:
        """The agent's field of view over the wired databases.

        The schema tools take their table as a *model* argument — the agent
        sees every table and picks one — so the editor shows the whole set,
        read from the same file the tool opens, instead of a per-node table
        control that never reached the runtime.

        A read, and a total one: a database that is missing, unreadable or
        whose driver is absent comes back as a warning on its source (or, for
        a path that does not resolve inside `workflows/`, as no source at
        all). Never a 500 — a card must not break because a file moved.
        """
        _, document = _knowledge_context(slug)
        return SqlSchemaResponse(
            sources=[
                SqlSourceResponse(
                    database=source.database,
                    engine=source.engine,
                    tables=[
                        SqlTableResponse(name=t.name, detail=t.detail) for t in source.tables
                    ],
                    warning=source.warning,
                )
                for source in reachable_schema(document, workflow_store.root)
            ]
        )

    @app.post(
        "/api/workflows/validate",
        response_model=ValidateResponse,
        summary="Can this document compile, and if not, why",
        tags=["Authoring"],
    )
    def validate_workflow(request: ValidateRequest) -> ValidateResponse:
        """The compile-check, without running anything.

        Validation existed only as an MCP tool, so the two clients were not
        equal: an LLM client had its document checked before every run and the
        editor could not check one at all. That asymmetry is what let a
        document containing an unregistered node type reach a run and answer
        with the user's own question — the skipped node forwards its input, so
        the run looks like it worked.

        Cheap and credential-free on purpose: `ValidateWorkflowTool` plans the
        graph in memory and throws it away, so this reaches no provider and a
        developer can call it long before they have a key configured.

        **A `valid: false` verdict is not a refusal.** The run endpoints report
        an unknown node type on the developer channel and continue, per
        `errors.py`'s "degrade loud, never silent" rule; the MCP door refuses.
        One validator, two policies — see `openstategraph.validation`.
        """
        from openstategraph.validation import validate_document

        valid, findings = validate_document(request.workflow)
        return ValidateResponse(valid=valid, findings=findings)

    @app.get(
        "/api/workflows/{slug}/graph",
        response_model=CompiledGraphResponse,
        summary="The compiled topology, as Mermaid text",
        tags=["Runs"],
    )
    def compiled_graph(
        slug: str, audience: Literal["developer", "customer"] = "developer"
    ) -> CompiledGraphResponse:
        """The COMPILED topology as Mermaid text (ticket 54) — what the
        compiler actually produced, not a hand-drawn approximation.

        `xray=True` expands subgraph internals (a concierge shows its routed
        children; a Team shows its members), which is also the cheap half of
        the editor's dual-view ask (ticket 68). Text, never a PNG —
        `draw_mermaid_png()` posts the graph to a third-party API.

        `audience=customer` hides the compiler's own vocabulary — `__start__`,
        `__default_error_handler__`, `safe_name`d ids, branch ids — and labels
        each node with the name its author gave it. The default is
        **developer**, deliberately: an existing caller keeps the ids, which
        are what a mount bug gets reported under, and only the customer page
        opts out (reviews-2026-08-14 ticket 04).
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
        if resolve_audience(audience) is Audience.CUSTOMER:
            mermaid_text = customer_mermaid(mermaid_text, document)
        return CompiledGraphResponse(mermaid=mermaid_text)

    # Routes that have moved out of this factory live on routers and reach
    # the app's assembly through `api/deps.Services` rather than through a
    # closure (reviews-2026-08-14 ticket 15). Included where they used to be
    # registered — the committed OpenAPI snapshot sorts its keys, so ordering
    # is not load-bearing, but keeping it makes the diff readable.
    app.include_router(providers_routes.router)
    app.include_router(runs_routes.router)
    app.include_router(threads_routes.router)

    @app.post(
        "/api/workflows/chinook-assistant/ask",
        response_model=AskResponse,
        summary="The Chinook demo's own endpoint (not a general API)",
        tags=["Demo"],
        description=(
            "A fixed, hand-built demo graph — the NL-to-SQL loop that is now "
            "the assistant's `data_query` branch — kept as its own endpoint "
            "because it predates the canvas and returns the SQL and rows "
            "alongside the prose so an answer can be audited. It answers "
            "database questions only, and has no router in front of it: the "
            "path shares this workflow's slug, not its document. It does not "
            "generalise: a client of your own wants `/api/runs/stream`."
        ),
    )
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
