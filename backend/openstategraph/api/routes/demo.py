"""The Chinook demo's own endpoint — deliberately not a general API.

One route, and the only one that needed something other than
`WorkflowServices`: it builds the hand-written NL-to-SQL graph that predates
the canvas, through the `graph_factory` a test can inject into `create_app`.
That is a constructor argument rather than part of the assembly, so it reaches
handlers by its own dependency (reviews-2026-08-14 ticket 15).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from openstategraph.api.deps import GraphFactory
from openstategraph.api.model_resolution import resolve_model
from openstategraph.api.schemas import AskRequest, AskResponse

router = APIRouter()


@router.post(
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
def ask(request: AskRequest, graph_factory: GraphFactory) -> AskResponse:
    model = resolve_model(request.model)
    graph = graph_factory(model)

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
