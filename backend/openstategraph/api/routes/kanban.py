"""`GET /api/kanban/cards` — the board's read door onto real rows.

`kanban-patrol/19`'s two write paths (CLI, MCP) already exist and share one
function (`kanban_store.set_stage`); this route adds no third writer, only a
reader, so the frontend can show real state without a fourth place the claim
logic could drift out of sync.

**Live, as of `kanban-patrol/07`.** `POST /api/kanban/patrol/run` used to run
`patrol.run_patrol` synchronously and answer with its result
(`kanban-patrol/27`) — correct while the patrol stayed sub-second, wrong on
purpose from here: a patrol must survive the board closing and the tab that
started it going away, so this route now launches the loop in the background
and returns the instant it has (`202`). `GET /api/kanban/patrol/status` is
the refetch half of "refetch plus subscribe" — a client that opens the board
mid-patrol, or was never listening when one started, asks this once — and
`GET /api/kanban/patrol/events` is the push half, an SSE stream carrying
`patrol.started` / `patrol.progressed` / `patrol.finished` / `patrol.failed`
with no replay: `catalogue_events.py`'s own rule applies here too, the store
(this route, and the registry) is the source of truth, an event is a hint to
go and look.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from openstategraph.api.deps import Services
from openstategraph.api.patrol_events import (
    KEEPALIVE_SECONDS,
    PATROL_EVENT,
    PATROL_FRAME_FIELDS,
    PatrolBroadcaster,
    PatrolEvent,
)
from openstategraph.api.patrol_registry import PatrolJobRegistry
from openstategraph.api.schemas import (
    KanbanCardResponse,
    KanbanReleaseResponse,
    PatrolRunAcceptedResponse,
    PatrolStatusResponse,
)
from openstategraph.api.sse_contract import sse_responses
from openstategraph.api.streaming import _sse, stop_when_client_leaves_async
from openstategraph.kanban_store import (
    STALE_THRESHOLD_SECONDS,
    card_row,
    flagged_stale,
    kanban_store_path,
    list_cards,
    release_card,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: Re-exported rather than declared — `kanban-patrol/16`. The hour
#: `kanban-patrol/19` locked now lives on `kanban_store`, beside the
#: `flagged_stale` that answers with it, so this route and the MCP door read
#: one number instead of each spelling their own.
__all__ = ["router", "STALE_THRESHOLD_SECONDS"]

#: A reference to every patrol task currently in flight, kept for one reason
#: only: `asyncio.create_task`'s own documentation warns that a task with no
#: strong reference held anywhere can be garbage-collected mid-run, silently,
#: before it completes — the exact "task nobody can query" `07` names as a
#: defect, with an extra twist (it would not even finish). A done task
#: removes itself; nothing here ever iterates the set for any other reason.
_PATROL_TASKS: set["asyncio.Task[None]"] = set()


async def _run_patrol_in_background(
    *,
    patrol_events: PatrolBroadcaster,
    patrol_jobs: PatrolJobRegistry,
    project_id: str,
    workflows_root: Any,
) -> None:
    """Drives `patrol.run_patrol` to completion off the event loop, and
    narrates it — kanban-patrol/07.

    **`run_in_executor`, not a bare coroutine.** `run_patrol` is a plain
    blocking function — it opens sqlite, reads checkpoints off disk — and
    running it directly inside this coroutine would stall every other
    request this process is serving for as long as the patrol takes. This is
    the same reason `RunLoop` (`run_doors.py`) exists at all: a blocking body
    needs a thread of its own, never the loop everything else shares.

    **The one dependency direction, kept.** `patrol.run_patrol` accepts an
    `on_card_filed` hook and calls it with plain strings; it does not import
    `patrol_events`, `PatrolBroadcaster`, or anything that knows SSE exists.
    The closure below is where the two meet — in the route layer, which is
    allowed to know about both.
    """
    from openstategraph.patrol import run_patrol

    loop = asyncio.get_running_loop()

    def on_card_filed(task_id: str, title: str) -> None:
        # Called from the executor thread `run_in_executor` dispatches to —
        # `publish()` documents that it is safe from exactly that thread.
        patrol_events.publish(PatrolEvent(kind="progressed", task_id=task_id, title=title))

    def run() -> Any:
        return run_patrol(
            project_id=project_id,
            workflows_root=workflows_root,
            on_card_filed=on_card_filed,
        )

    try:
        result = await loop.run_in_executor(None, run)
    except Exception as exc:  # noqa: BLE001 - reported to every subscriber, never swallowed
        reason = str(exc) or exc.__class__.__name__
        logger.exception("patrol failed")
        patrol_jobs.failed(reason)
        patrol_events.publish(PatrolEvent(kind="failed", reason=reason))
        return

    patrol_jobs.finished(
        filed=len(result.filed), skipped=len(result.skipped), total_findings=result.total_findings
    )
    patrol_events.publish(
        PatrolEvent(
            kind="finished",
            filed=len(result.filed),
            skipped=len(result.skipped),
            total_findings=result.total_findings,
        )
    )


@router.get(
    "/api/kanban/cards",
    response_model=list[KanbanCardResponse],
    summary="Every card in this project's kanban store, current stage included",
    tags=["Kanban"],
)
def list_kanban_cards(services: Services) -> list[KanbanCardResponse]:
    """An empty list, never an error, when nothing has been filed yet —
    `kanban-patrol/19`'s own rule for an unattended-nothing board: a patrol
    that ran and found nothing is a different claim from a patrol that
    cannot run, and this route only ever makes the first one.

    **Independently correct regardless of event history** (`kanban-patrol
    /07`'s own "done when"): this is a plain SQL read of the store, with no
    memory of which SSE frames were sent or missed. A client that connects
    mid-patrol, refetches here, and sees a card the patrol filed while it was
    disconnected — that is this route doing exactly what it always did,
    which is the whole reason "refetch plus subscribe" is a correct answer
    and not a workaround.
    """
    db = kanban_store_path(services.store.root)
    stale_ids = set(flagged_stale(db, threshold_seconds=STALE_THRESHOLD_SECONDS))
    return [
        # One row shape, built once — `kanban-patrol/16`. `card_row` is the
        # same function the MCP `kanban_list_cards` answers with, so a board
        # and an agent cannot come to read different cards.
        KanbanCardResponse(**card_row(card, stale=card.task_id in stale_ids))
        for card in list_cards(db)
    ]


@router.post(
    "/api/kanban/cards/{task_id}/release",
    response_model=KanbanReleaseResponse,
    summary="Release an abandoned claim — refuses unless the card is already flagged stale",
    tags=["Kanban"],
)
def release_kanban_card(task_id: str, services: Services) -> KanbanReleaseResponse:
    """The board's Release button — `kanban-patrol/19`'s "a human presses an
    explicit Release themselves", made real.

    A thin door onto `kanban_store.release_card`, which does the only two
    things that matter: refuses any card not already named by `flagged_stale`
    (an active claim, or one nobody has attended, is never releasable by
    accident), and otherwise resets the row to a fresh, unattended state.
    A refusal is a clean `400` naming why — same pattern this route already
    uses for `run_patrol_once`'s own refusal, never a 200 with a false claim
    of success inside it.
    """
    db = kanban_store_path(services.store.root)
    result = release_card(db, task_id, threshold_seconds=STALE_THRESHOLD_SECONDS)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.reason)
    return KanbanReleaseResponse(ok=True)


@router.post(
    "/api/kanban/patrol/run",
    response_model=PatrolRunAcceptedResponse,
    status_code=202,
    summary="Start the in-built patrol in the background — refuses if one is already running",
    tags=["Kanban"],
)
async def run_patrol_once(services: Services) -> PatrolRunAcceptedResponse:
    """The door the board's "Run Patrol" button calls — `kanban-patrol/27`,
    made durable by `kanban-patrol/07`.

    **No longer waits for the loop.** It claims the one job slot
    (`services.patrol_jobs.try_start()`), publishes `patrol.started` to every
    connected subscriber, launches `patrol.run_patrol` on a background task,
    and returns `202` — the loop keeps running after this response is sent
    and after the tab that sent the request closes.

    **`409`, not a queue, when one is already running.** `07` asks for a
    clean refusal specifically so a second click cannot start a second
    patrol racing the first over the same sqlite rows; `try_start` makes the
    check-and-claim atomic, so this is a refusal on a genuine race, not a
    best-effort guess.

    `project_id` comes from the project's own committed config, same source
    the CLI reads. A project made **before that field existed** is adopted
    here rather than refused (`kanban-patrol/23`): the line is appended to
    that project's own `openstategraph.yaml`, logged, and the request
    proceeds normally. It was a 400 until then, which meant the board was
    permanently unusable for every project older than the field. A config
    this cannot safely append to (a `pyproject.toml` table, a JSON carrier),
    or none at all, is still a clear 400 naming the reason.
    """
    from openstategraph.config_file import active_config
    from openstategraph.project_identity import (
        ProjectIdentityError,
        adopt_for_active_config,
        project_id_line,
    )

    config = active_config()
    project_id = config.project_id if config else None
    if not project_id:
        try:
            adopted = adopt_for_active_config()
        except (ProjectIdentityError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if adopted is None or not adopted.project_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "no project_id and no config file to put one in — "
                    "run `openstategraph init` in this project."
                ),
            )
        project_id = adopted.project_id
        logger.info("%s", project_id_line(project_id))

    if not services.patrol_jobs.try_start():
        raise HTTPException(status_code=409, detail="A patrol is already running.")

    services.patrol_events.publish(PatrolEvent(kind="started"))
    task = asyncio.ensure_future(
        _run_patrol_in_background(
            patrol_events=services.patrol_events,
            patrol_jobs=services.patrol_jobs,
            project_id=project_id,
            workflows_root=services.store.root,
        )
    )
    _PATROL_TASKS.add(task)
    task.add_done_callback(_PATROL_TASKS.discard)
    return PatrolRunAcceptedResponse(status="started")


@router.get(
    "/api/kanban/patrol/status",
    response_model=PatrolStatusResponse,
    summary="What the one patrol this process can run is doing right now",
    tags=["Kanban"],
)
def patrol_status(services: Services) -> PatrolStatusResponse:
    """The refetch half of "refetch plus subscribe" — kanban-patrol/07.

    A client that opens the board mid-patrol, or that connects to
    `GET /api/kanban/patrol/events` after `patrol.started` already went out,
    asks this once on open and learns "one is running" without having seen a
    single event — `catalogue_events.py`'s own rule, applied here: the
    registry is the source of truth, an event is a hint to go and look.
    """
    state = services.patrol_jobs.snapshot()
    return PatrolStatusResponse(
        status=state.status,
        started_at=state.started_at,
        finished_at=state.finished_at,
        error=state.error,
        filed=state.filed,
        skipped=state.skipped,
        total_findings=state.total_findings,
    )


@router.get(
    "/api/kanban/patrol/events",
    summary="Patrol progress, live (SSE)",
    response_class=StreamingResponse,
    responses=sse_responses(
        (PATROL_EVENT,),
        "One frame per patrol event.",
        # The fields as well as the name — `kanban-patrol/31`. Passed rather
        # than typed, so the published contract cannot disagree with what
        # `PatrolEvent.as_dict()` puts on the wire.
        {PATROL_EVENT: PATROL_FRAME_FIELDS},
    ),
    tags=["Kanban"],
)
async def patrol_events_stream(http: Request, services: Services) -> StreamingResponse:
    """Patrol progress, live — `event: patrol.status`, `kind` inside it.

    The same shape as `GET /api/events`, on a sibling broadcaster rather than
    that endpoint's own — see `patrol_events.py`'s module docstring for why a
    patrol event does not ride the catalogue's fan-out. Framed by `_sse`, the
    one framer this codebase has; no second SSE format is introduced here.

    **No replay**, exactly as `/api/events` has none: a subscriber sees what
    happens while connected. `GET /api/kanban/patrol/status` is how a late
    subscriber learns what it missed.
    """
    broadcaster = services.patrol_events

    async def frames() -> Any:
        with broadcaster.subscribe() as subscriber:
            yield ": connected\n\n"
            async for event in subscriber.events(idle_timeout=KEEPALIVE_SECONDS):
                if event is None:
                    yield ": keepalive\n\n"
                else:
                    yield _sse(PATROL_EVENT, event.as_dict())

    return StreamingResponse(
        stop_when_client_leaves_async(frames(), http.receive),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
