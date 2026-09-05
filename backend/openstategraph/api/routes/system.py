"""What this server is, what it can build with, and what changed.

The four routes that are about the *deployment* rather than about any one
workflow: the node vocabulary a client composes against, the catalogue event
stream, the health probe, and the starting templates.

`/api/events` is the only one that needs the app's assembly — it subscribes to
the broadcaster (reviews-2026-08-14 ticket 15), and since
`osg-agent-experience/71` to as many as four of them at once: it is the single
long-lived connection an editor tab can afford, so every live subject rides it.
`live_stream.py` is the table of what those subjects are.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from openstategraph.api.broadcast import DEFAULT_BACKLOG_LIMIT, Subscriber
from openstategraph.api.catalogue_events import KEEPALIVE_SECONDS
from openstategraph.api.deps import Services
from openstategraph.api.live_stream import (
    LIVE_EVENT_NAMES,
    live_frame_fields,
    live_frame_name,
)
from openstategraph.api.schemas import (
    HealthResponse,
    NodeContractResponse,
    TemplateResponse,
)
from openstategraph.api.sse_contract import sse_responses
from openstategraph.api.streaming import _sse, stop_when_client_leaves_async
from openstategraph.api.workflow_events import WorkflowChangedEvent

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
    summary="Live changes on one connection (SSE)",
    response_class=StreamingResponse,
    responses=sse_responses(
        LIVE_EVENT_NAMES,
        "One frame per change, on whichever subjects this connection asked for.",
        # The names and the fields, both passed rather than typed —
        # `kanban-patrol/34`, now from the one registry that also decides what
        # this route attaches, so the published contract cannot name a frame
        # the stream does not send or omit one it does.
        live_frame_fields(),
    ),
    tags=["Catalogue"],
)
async def catalogue_events(
    http: Request,
    services: Services,
    slug: str | None = Query(
        default=None,
        description="Also carry `workflow.changed` for this package's document.",
    ),
    patrol: bool = Query(default=False, description="Also carry `patrol.status`."),
    kanban: bool = Query(default=False, description="Also carry `kanban.changed`."),
) -> StreamingResponse:
    """Every live subject this surface asked for, on **one** connection.

    Not expressible in OpenAPI beyond its media type; the frame shapes and the
    reconnect behaviour are in `docs/api.md`.

    Why this exists at all: `/chat` fetched its picker once, on load, so a
    customer sitting on the page never saw a newly published workflow until
    they reloaded, and the editor's Workflows panel had the same blind spot
    with respect to a second tab.

    **Why it carries four subjects rather than one**
    (`osg-agent-experience/71`). A browser allows six concurrent HTTP/1.1
    connections per origin. An editor tab spent two of them on long-lived
    streams — this one and `/api/kanban/patrol/events` — before `69` added a
    third for the per-package watcher, and with two tabs on one workflow the
    budget was gone: the last stream opened sat at `readyState 0` for minutes
    and ordinary `fetch` calls in that tab stopped completing. HTTP/2 raises
    the limit and is a property of somebody's proxy, not of this project, so
    it must not be the answer. A subject is a frame here, not a socket.

    **Opt-in, and that is the cost model rather than a nicety.** The catalogue
    is always carried, because that is what every existing caller opens this
    endpoint for. `patrol=1`, `kanban=1` and `slug=<slug>` each attach one
    more fan-out, and the last two own **poll tasks whose lifetime is the set
    of subscribers** — so a connection that does not ask for the board does
    not start the store poll, which is exactly the property `kanban_events.py`
    gave as its reason for being a sibling stream. A plain `GET /api/events`
    sees and costs what it always did.

    **No frame is renamed.** Each subject keeps its own `event:` name, so the
    sibling endpoints and this one speak one vocabulary; `live_stream.py` is
    the single table saying which name belongs to which payload. Framed by
    `_sse` — the one framer.

    A connection that named a slug is handed frames about **that** slug only,
    filtered here rather than in the client: one watcher serves every open
    package, and handing a connection traffic about packages it never named
    would make this endpoint's own contract a half-truth.

    The payloads are **hints, never documents**: a client refetches
    `/api/workflows`, `/api/kanban/cards` or `/api/workflows/{slug}` on them,
    so there is exactly one spelling of each thing and no cache built from
    events that could disagree with it. **No replay**, on every subject: a
    subscriber sees what happens while it is connected, and its refetch on
    open is what recovers the rest.

    Limits, stated rather than discovered (full reasoning in
    `catalogue_events`): the fan-out is **in-process**, so it covers one
    worker — the documented ceiling (`uvicorn --workers 1`, for sqlite's
    per-instance write lock); a multi-worker deployment needs Redis pub/sub or
    Postgres LISTEN/NOTIFY behind the same publish/subscribe pair. And the
    catalogue subject still only emits for writes **through this API**: a
    `workflow.json` hand-edited on disk or arriving by `git pull` produces no
    `workflows.changed`. The `slug` subject is the one that covers those
    writers, because it watches the file (`osg-agent-experience/69`).
    """

    async def frames() -> Any:
        # One subscriber, several fan-outs — the whole ticket in three lines.
        # It is built here rather than by each broadcaster's own `subscribe()`
        # because this connection owns it: `attach` deliberately does not
        # close a subscriber it did not make, so the first detach cannot end
        # the other three subjects mid-sentence.
        subscriber: Subscriber[Any] = Subscriber(
            asyncio.get_running_loop(), DEFAULT_BACKLOG_LIMIT
        )
        # The subscription's lifetime IS this generator's: the stack unwinds on
        # a normal end, on a disconnect (the wrapper closes this generator) and
        # on a raise alike. Nothing has to remember to.
        async with AsyncExitStack() as stack:
            # Registered first so it runs last: the fan-outs let go of the
            # subscriber before the subscriber is ended.
            stack.callback(subscriber.close)
            stack.enter_context(services.events.attach(subscriber))
            if patrol:
                stack.enter_context(services.patrol_events.attach(subscriber))
            if kanban:
                await stack.enter_async_context(services.kanban_events.attach(subscriber))
            if slug:
                await stack.enter_async_context(
                    services.workflow_events.attach(slug, subscriber)
                )
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
                    continue
                if isinstance(event, WorkflowChangedEvent) and event.slug != slug:
                    continue
                yield _sse(live_frame_name(event), event.as_dict())

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
