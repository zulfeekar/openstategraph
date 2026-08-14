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
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from openstategraph.api.editor_assets import mount_editor  # noqa: E402
from openstategraph.api.sse_contract import (  # noqa: E402, F401  (re-exported)
    STREAM_GUIDE,
    sse_responses,
)
from openstategraph.api.routes import chat_ui as chat_ui_routes  # noqa: E402
from openstategraph.api.routes import demo as demo_routes  # noqa: E402
from openstategraph.api.routes import providers as providers_routes  # noqa: E402
from openstategraph.api.routes import runs as runs_routes  # noqa: E402
from openstategraph.api.routes import system as system_routes  # noqa: E402
from openstategraph.api.routes import threads as threads_routes  # noqa: E402
from openstategraph.api.routes import workflows as workflow_routes  # noqa: E402
from openstategraph.api.registries import (  # noqa: E402, F401  (re-exported for tests)
    build_tool_registry,
    runtime_warnings,
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
    # without starting FastAPI.
    #
    # Three of its fields used to be unpacked into locals here —
    # `workflow_store = services.store` and two more — "so every endpoint
    # reads as it did". That was the parameter object being flattened the
    # moment after it was built, and it is what made every handler a closure
    # over this function (reviews-2026-08-14 ticket 15). Handlers reach the
    # same object through `api/deps.Services` now, so the locals are gone and
    # the grouping outlives the call.
    services = WorkflowServices(workflows_root)

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
    #: The demo graph, injectable so a test can stand one up without a model.
    #: On `app.state` for the same reason `services` is: it is what lets the
    #: `/api/workflows/chinook-assistant/ask` handler be a module-level
    #: function rather than a closure over this factory
    #: (reviews-2026-08-14 ticket 15).
    app.state.graph_factory = factory
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

    # Routes that have moved out of this factory live on routers and reach
    # the app's assembly through `api/deps.Services` rather than through a
    # closure (reviews-2026-08-14 ticket 15). Included where they used to be
    # registered — the committed OpenAPI snapshot sorts its keys, so ordering
    # is not load-bearing, but keeping it makes the diff readable.
    app.include_router(chat_ui_routes.router)
    app.include_router(demo_routes.router)
    app.include_router(providers_routes.router)
    app.include_router(runs_routes.router)
    app.include_router(system_routes.router)
    app.include_router(threads_routes.router)
    app.include_router(workflow_routes.router)


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
