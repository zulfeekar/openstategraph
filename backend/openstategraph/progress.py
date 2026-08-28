"""What a running step says about itself while it is still working.

One module, one sentence: a tool that will be busy for a while can say so, and
that sentence reaches the client as a `progress` frame.

**The gap this closes.** Our SSE vocabulary reports a node when it *finishes*
(`update`) and a model while it types (`token`). A tool that spends forty
seconds paging an API produces neither, so the run reads as stopped — which is
why `docs/api.md` has to spend a paragraph explaining that `update` frames only
tell you who *last finished*. LangGraph's answer is the `custom` stream mode
and `get_stream_writer()`, and it is also the documented escape hatch for any
model that is not a LangChain chat model.

**Who calls it.** Not only a developer's own tool: the shipped slow ones do
too — `prebuilt_web` (search, fetch), `prebuilt_youtube`, and every MCP call
through `prebuilt_mcp._wrap_async_tool`. That is deliberate and was missing
until production-ready 50, when this module's only caller in the repository
was the example in `report_progress`'s own docstring — an extension point
described as a solved problem. `knowledge_builders` is the one named slow job
that is **not** here, because a build is not a graph run and there is no
stream for it to write to.

**Why a Pydantic model here and nowhere else in the stream.** The other six
frames are assembled by `api/streaming.py` out of values this process
produced — LangGraph's own chunks, the compiler's name maps, our resolvers.
This one carries *whatever a tool wrote*, which is arbitrary third-party code,
and `custom` is a **shared** channel: deepagents and any middleware may write
to it too. That is a real boundary, so it gets a real one.

**The envelope is not decoration.** Because the channel is shared, a payload
must say that it is ours before anything renders it to a person. Turning a
stranger's internal dict into a user-visible line is precisely the class of
leak this codebase keeps closing — a tool's raw payload in the answer area, a
router's branch name in a customer's prose. Anything on `custom` without
`PROGRESS_KEY` is ignored, deliberately and silently.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = ["PROGRESS_KEY", "Progress", "progress_report", "report_progress"]

#: The envelope key that marks a `custom` payload as one of ours.
#:
#: Dotted and package-qualified because the channel is shared and a bare
#: `"progress"` is a word anyone might reasonably write.
PROGRESS_KEY = "openstategraph.progress"

#: A tool's `metadata` key meaning **this tool reports its own start**, so the
#: `"narration"` slot must not report it a second time.
#:
#: `launch-readiness/145`. Two producers were narrating the same MCP call with
#: the *same sentence* out of the *same table* — `prebuilt_mcp._wrap_async_tool`
#: from inside the tool, and `NarrationMiddleware` from around it — and the
#: duplication was invisible because every surface collapsed a line repeated
#: back to back. `145` stopped the panel doing that (a repeat is evidence:
#: `launch-readiness/146`), and the moment it did, a live `cpl-mcp` run read
#:
#: ```
#: Looking up which views of the data are available.
#: Looking up which views of the data are available.
#: Found 15 views of the data.
#: ```
#:
#: The fix is the DRY one — **one call, one narrator** — and not a filter: a
#: middleware cannot tell a duplicate from a genuine second call, which is the
#: whole reason collapsing was the wrong answer in the view. So the tool
#: *declares* that it speaks for itself and the middleware stands down for the
#: before-line only. The finding afterwards is still the middleware's: it is
#: the one place that holds the result.
#:
#: Declared here rather than in either module because both already import this
#: seam and neither imports the other — a literal in two files is exactly the
#: drift this key exists to prevent. Removing the tool's own line instead was
#: rejected: a subagent's tool stack is assembled by `create_deep_agent` and
#: does not carry our middleware, so the tool's line is the only one there.
NARRATES_ITSELF = "openstategraph.narrates_itself"


class Progress(BaseModel):
    """One thing a step said about itself mid-execution.

    Deliberately small. A progress line is read by a person watching a run,
    beside a spinner — it is not a log record, and everything it could grow
    (timestamps, levels, structured fields) belongs to tracing instead.
    """

    #: What to show. Written by the workflow's own developer, so it is the one
    #: field that reaches a customer's surface as prose.
    message: str

    #: How far along, when a step happens to know. `int | None` with `None`
    #: meaning "no claim" — never `-1`, and never a non-finite float, which
    #: JSON cannot represent and which would not survive its own round trip.
    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)

    #: The graph node that reported, stamped by `report_progress` rather than
    #: supplied by the author: the stream writer is ambient, so a tool cannot
    #: know the node it was called from and should not be asked to.
    node: str = ""

    #: The evidence behind `message`, in the words of whatever produced it —
    #: **developer audience only**, and the one field on this model that is
    #: not safe to speak.
    #:
    #: `launch-readiness/163`. `message` is composed under `143`'s customer
    #: seam, where no value from a result is ever interpolated and only
    #: integers are spoken; that is why a failed query says *"That did not
    #: work."* and nothing else. Correct for a customer, and useless for the
    #: person who can actually fix the workflow: the owner watched six of
    #: those in a row and had to paste the raw payload into a chat before
    #: anybody could see the words `Invalid column name 'loading_time'`, which
    #: had been sitting in the envelope the whole time.
    #:
    #: So the split is made here, in the model, rather than by widening
    #: `message`: `message` keeps crossing to a customer intact and this rides
    #: beside it. `api/streaming.py` drops it for any audience but
    #: `Audience.DEVELOPER` — one gate, at the seam that already redacts per
    #: audience — and `143`'s negative test still proves an ODBC message
    #: cannot reach a customer.
    #:
    #: `None` means "no evidence to add", which is every progress line a tool
    #: author writes by hand.
    detail: str | None = None


def report_progress(
    message: str,
    *,
    current: int | None = None,
    total: int | None = None,
    detail: str | None = None,
) -> bool:
    """Says something about this step, mid-execution. Returns whether it landed.

    Called from inside a tool, a discovered function, or a node body:

        from openstategraph.abc import report_progress

        report_progress("Read 40 of 100 invoices", current=40, total=100)

    **Outside a run this is a no-op, and that is the point.** LangGraph's
    `get_stream_writer()` raises `RuntimeError: Called get_config outside of a
    runnable context` when nothing is running, and CLAUDE.md's whole claim for
    a package's `tools/` and `tests/` — that they are real code, importable
    from a script and testable with pytest — would be false if a progress line
    detonated a unit test. So the failure is swallowed and reported as `False`,
    which is also the honest answer to "did anyone hear that".

    `detail` is the developer-only half (`launch-readiness/163`): evidence in
    somebody else's words, shown to a developer and dropped for a customer at
    the streaming seam. Leave it unset unless you are handing over text you
    did not author.
    """
    try:
        from langgraph.config import get_config, get_stream_writer

        writer = get_stream_writer()
        node = str(((get_config() or {}).get("metadata") or {}).get("langgraph_node") or "")
        writer(
            {
                PROGRESS_KEY: Progress(
                    message=message,
                    current=current,
                    total=total,
                    node=node,
                    detail=detail,
                ).model_dump()
            }
        )
        return True
    except Exception:  # noqa: BLE001 — a step reporting progress must never fail a run
        logger.debug("progress was not delivered: no stream is listening")
        return False


def progress_report(payload: Any) -> Progress | None:
    """The `Progress` a `custom` payload carries, or `None` if it carries none.

    Total by construction. Three things arrive on this channel and only one of
    them is ours: our own envelope, another library's data, and a malformed
    report from a tool somebody is still writing. The last is the reason the
    validation error is swallowed rather than raised — a bad payload from
    third-party code costs its own frame, never the run, and the stream's one
    hard guarantee is that it always reaches a terminal frame.
    """
    if not isinstance(payload, dict):
        return None
    raw = payload.get(PROGRESS_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return Progress.model_validate(raw)
    except Exception:  # noqa: BLE001 — see the docstring
        logger.warning("a step wrote a progress report this version cannot read")
        return None
