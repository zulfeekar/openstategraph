"""What this server is, what it can build with, and what changed.

The four routes that are about the *deployment* rather than about any one
workflow: the node vocabulary a client composes against, the catalogue event
stream, the health probe, and the starting templates.

`/api/events` is the only one that needs the app's assembly — it subscribes to
the broadcaster (reviews-2026-08-14 ticket 15).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from openstategraph.api.catalogue_events import CATALOGUE_EVENT, KEEPALIVE_SECONDS
from openstategraph.api.deps import Services
from openstategraph.api.schemas import (
    HealthResponse,
    NodeContractResponse,
    TemplateResponse,
)
from openstategraph.api.sse_contract import sse_responses
from openstategraph.api.streaming import _sse, stop_when_client_leaves_async

router = APIRouter()


@router.get(
    "/api/node-contracts",
    response_model=dict[str, NodeContractResponse],
    summary="The prompt layers a developer does not type, per model-driven node type",
    tags=["Authoring"],
)
def node_contracts() -> dict[str, NodeContractResponse]:
    """Every prompt layer a developer does **not** type (tickets 31, 39).

    Served from the Python ladder classes — the single source of truth —
    so the editor can show a developer what the machinery already says
    (read-only, beside their editable rules) instead of letting them
    duplicate or contradict it. The original RouterNode bug this
    prevents: an editable field pre-filled with the output contract,
    cleared by the first person who wrote their own rules.

    **Three layers, not two, and the docstring above was false for a quarter
    of the families until it was** (ticket 39). `agent.llm` locks no preamble
    and no output contract — it answers free-form, deliberately — so a payload
    of those two fields alone published nothing for it, and the read-only panel
    disappeared for the most-placed node in the product while its
    `default_rules` went on being prepended to every prompt. `default_rules` is
    published as its own field because it is *replaceable*: the developer's
    rules extend it unless they choose replace mode, and calling that "locked"
    would be a second untruth in place of the first.
    """
    from openstategraph.abc.agent import BaseAgentNode
    from openstategraph.abc.grader import BaseGrader
    from openstategraph.abc.orchestrator import BaseOrchestrator
    from openstategraph.abc.router import BaseRouter

    def sections(ladder: Any) -> NodeContractResponse:
        """Every layer of this family's prompt that the developer does not type.

        `default_rules` is here because of ticket 39: for `agent.llm` it is the
        *only* such layer — preamble and contract are empty by design — so a
        two-field payload published nothing for the most-placed node in the
        product, and the panel that exists to stop a developer duplicating the
        machinery showed them an empty space instead.
        """
        return NodeContractResponse(
            preamble=ladder.PROMPT.preamble,
            contract=ladder.PROMPT.output_contract,
            default_rules=ladder.PROMPT.default_rules,
        )

    return {
        "agent.llm": sections(BaseAgentNode),
        "route.classifier": sections(BaseRouter),
        "route.grader": sections(BaseGrader),
        "orchestrate.supervisor": sections(BaseOrchestrator),
    }


@router.get(
    "/api/events",
    summary="Catalogue changes, live (SSE)",
    response_class=StreamingResponse,
    responses=sse_responses((CATALOGUE_EVENT,), "One frame per catalogue change."),
    tags=["Catalogue"],
)
async def catalogue_events(http: Request, services: Services) -> StreamingResponse:
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


@router.get(
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
    from openstategraph.editor_freshness import editor_is_stale
    from openstategraph.providers import ProviderEnvironment, provider_catalogue

    configured = any(
        ProviderEnvironment(spec).is_configured() for spec in provider_catalogue().list()
    )
    # Still cheap: two `stat` walks over a directory the process already sits
    # in, and `None` the moment there is no source tree to compare against —
    # which is every installed wheel.
    return HealthResponse(
        ok=True, model_configured=configured, editor_stale=editor_is_stale()
    )


@router.get(
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
