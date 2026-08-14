"""Past runs, read back out of the checkpointer that stored them.

Two routes, and the simplest case in the split: they captured nothing from
`create_app` except `services` itself (reviews-2026-08-14 ticket 15).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from openstategraph.api.deps import Services
from openstategraph.api.schemas import ThreadHistoryResponse, ThreadListResponse

router = APIRouter()


@router.get(
    "/api/threads",
    response_model=ThreadListResponse,
    summary="Past runs — the threads this deployment has stored",
    tags=["Runs"],
)
def list_threads_endpoint(
    services: Services,
    workflow_slug: str | None = None,
    user_email: str | None = None,
    session_id: str | None = None,
    limit: int = 25,
) -> ThreadListResponse:
    """Which runs happened, under whose identity, and which are still paused.

    Read straight out of the checkpointer that stored them — there is no
    second index of runs to drift from the checkpoints it would describe.
    `session_id` and `user_email` come back from checkpoint metadata,
    where LangGraph persists the `configurable` block the *transport*
    supplied; nothing a model said about itself can appear here.

    The filters narrow a list, they do not authorize one: this deployment
    authenticates a single shared token, so anyone who can call this can
    call it without `user_email` too. Per-user history needs per-user
    auth, and this endpoint does not pretend to be it.
    """
    from openstategraph.api import threads as thread_queries

    rows = thread_queries.list_threads(
        thread_queries.savers_for(services, workflow_slug),
        workflow_slug=workflow_slug,
        user_email=user_email,
        session_id=session_id,
        limit=max(1, min(limit, 200)),
    )
    return ThreadListResponse(threads=rows)

@router.get(
    "/api/threads/{thread_id}",
    response_model=ThreadHistoryResponse,
    summary="View one past run, checkpoint by checkpoint",
    tags=["Runs"],
)
def read_thread_endpoint(
    services: Services, thread_id: str, workflow_slug: str | None = None
) -> ThreadHistoryResponse:
    """A recorded run played back as text. **Nothing is re-executed.**

    Every value here was written while the run happened; reading it calls
    no model and no tool, so viewing a run that sent an email does not
    send it again. The endpoint that *does* execute is
    `POST /api/runs/resume`, which continues a `paused` thread from its
    interrupt — a different verb on purpose.
    """
    from openstategraph.api import threads as thread_queries

    history = thread_queries.read_thread(
        thread_queries.savers_for(services, workflow_slug), thread_id
    )
    if history is None:
        raise HTTPException(
            status_code=404, detail=f"No stored run for thread {thread_id!r}."
        )
    return history
