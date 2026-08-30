"""The recordings, read back out of the run store that kept them.

`memory-and-replay` 72. Two routes over one table, and the table is
`runs.sqlite` — **not** the checkpointer. `api/routes/threads.py` next door
reads the other store and answers a different question about the same runs:
*which supersteps ran, under whose identity, and which are paused*. This
answers *how the output arrived*, which is the only one of the two a playhead
can be honest about, because only this store kept the offsets
(`memory-and-replay` 47) that `52`'s transport moves between.

**Reads only, and there is no verb here that could be anything else.** Opening
a recording calls no model, opens no stream and touches no checkpoint. That is
the lexicon's distinction between *replay* — reading a recording back, a
profiler — and *re-run*, which is not built. The store is the only thing these
routes can reach and it has no execution in it.

**The audience is the same parameter the run doors take, capped by the same
`resolve()`.** It defaults to `customer`, so a client written before this
route existed reads a customer's recordings; the editor asks for `developer`
because the editor is the workflow's author. The gate is not applied here — it
is passed to `read_runs`, which applies the clause `RunBurst.audience` was
stored for (`memory-and-replay` 71).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from openstategraph.api.audience import Audience, resolve, run_usage
from openstategraph.api.deps import Services
from openstategraph.api.schemas import (
    RecordedBurst,
    RecordedRun,
    RecordedRunsResponse,
    RecordedThreadResponse,
    RecordedUsage,
)
from openstategraph.run_sinks import RunRecord, read_runs, run_store_path

router = APIRouter()

#: How many rows one listing may return. The same ceiling `GET /api/threads`
#: applies, for the same reason: this store never sweeps, so an unbounded
#: listing is a cost that only ever rises.
MAX_LISTING = 200

#: How many turns of one conversation open at once. A turn's recording is 6-30
#: bursts, so this is the bound that keeps *open a thread* a bounded response
#: rather than one that grows with how long somebody talked.
MAX_TURNS = 50


def _on_the_wire(record: RunRecord, audience: Audience) -> RecordedRun:
    """One stored row as the door publishes it.

    Named fields rather than a spread: `RunRecord` is the store's extension
    point and gains a field whenever a sink needs one, and a response that
    republished whatever it found would put the next one on the wire before
    anybody had decided it belonged there. `statements` is the field that makes
    that concrete — it quotes a customer's own data through a tool, and it is
    absent here because no surface asked for it.
    """
    return RecordedRun(
        at=record.at,
        workflowSlug=record.workflow_slug,
        threadId=record.thread_id,
        sessionId=record.session_id,
        question=record.question,
        answer=record.answer,
        seconds=record.seconds,
        attempts=record.attempts,
        failed=record.failed,
        usage=_spend(record, audience),
        bursts=[
            RecordedBurst(
                node=burst.node,
                activeNode=burst.active_node,
                namespace=list(burst.namespace),
                block=burst.block,
                kind=burst.kind,
                withheld=burst.withheld,
                firstMs=burst.first_ms,
                lastMs=burst.last_ms,
                chunks=burst.chunks,
                chars=burst.chars,
                text=burst.text,
                capped=burst.capped,
            )
            for burst in record.bursts
        ],
    )


def _spend(record: RunRecord, audience: Audience) -> list[RecordedUsage] | None:
    """What the run cost, through the function that already owns the boundary.

    `audience.run_usage` is where `56` put the rule — rows for a developer,
    `None` for a customer, `[]` for a run that called no model — and calling it
    is what keeps this door from becoming a second place that decides.
    """
    rows = run_usage(record.usage, audience)
    return None if rows is None else [RecordedUsage(**row) for row in rows]


@router.get(
    "/api/runs/recorded",
    response_model=RecordedRunsResponse,
    summary="Recorded runs — every run this deployment's run store kept",
    tags=["Runs"],
)
def list_recorded_runs_endpoint(
    services: Services,
    workflow_slug: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    audience: Audience = Audience.CUSTOMER,
    limit: int = 100,
) -> RecordedRunsResponse:
    """Every recorded run, newest first, with no cadence attached.

    The listing is rows and a **thread** is what opens, because a burst list is
    5-8 KiB per run and paying for it to render a table would make the cheap
    question expensive — `read_runs`' own argument, applied to a door.

    Newest first is the store's indexed order and is not re-sorted here.
    `the-cost-of-one-more/11` made that ordering a derived sort key precisely
    because `at` is local wall clock with an offset and sorting it as text
    sorts the same instant a day apart; a route that re-ordered the rows it was
    handed would put the wrong order back.

    **A store that was never written is not an error.** A fresh install has no
    runs, and *no runs* is an answer.
    """
    seen = resolve(audience)
    return RecordedRunsResponse(
        runs=[
            _on_the_wire(record, seen)
            for record in read_runs(
                run_store_path(services.store.root),
                workflow_slug=workflow_slug,
                session_id=session_id,
                thread_id=thread_id,
                kind="run",
                limit=max(1, min(limit, MAX_LISTING)),
            )
        ]
    )


@router.get(
    "/api/runs/recorded/{thread_id}",
    response_model=RecordedThreadResponse,
    summary="One conversation's recordings, turn by turn",
    tags=["Runs"],
)
def read_recorded_thread_endpoint(
    services: Services,
    thread_id: str,
    audience: Audience = Audience.CUSTOMER,
) -> RecordedThreadResponse:
    """A conversation's turns, each with the cadence its output arrived at.

    **Nothing is re-executed.** Every offset here was measured while the run
    happened; reading them calls no model and no tool.

    A turn has no id of its own and none is minted. The store's own name for a
    row is a sqlite `rowid` — storage, not a fact about the run, and meaningless
    to the other sink writing the same record — and `at` is second precision, so
    two turns can share it. A turn is *the thread it is in and its position in
    that thread*, which is what a conversation is, and this response is that
    position: oldest first, so reading top to bottom is the conversation
    happening.

    `audience` decides whether the recordings come back at all, never whether
    the turns do. A refused recording leaves the turn listed with no bursts —
    the same absence a run recorded before `47`, a workflow with no model in it,
    and a fresh install all answer with.
    """
    seen = resolve(audience)
    records = read_runs(
        run_store_path(services.store.root),
        thread_id=thread_id,
        kind="run",
        limit=MAX_TURNS,
        with_bursts=True,
        audience=seen.value,
    )
    if not records:
        raise HTTPException(
            status_code=404, detail=f"No recorded run for thread {thread_id!r}."
        )
    # `read_runs` hands back newest first, which is the listing's order and the
    # wrong one for a conversation. Reversed rather than re-sorted: the index
    # already decided what *newest* means, and a second opinion about it here is
    # the text sort `the-cost-of-one-more/11` removed.
    return RecordedThreadResponse(
        threadId=thread_id,
        runs=[_on_the_wire(record, seen) for record in reversed(records)],
    )
