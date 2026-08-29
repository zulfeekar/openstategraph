"""Which worker a deep agent's delegation actually reached — `launch-readiness/178`.

One reason to change: *how a delegation is named on the run's own record*.

`compile/subagents.py` goes to real trouble to make a declaration honest
**before** the run — a row on a `react` tier is refused at validate time, a row
missing one of its three strings is refused by name. All of that is about what
*will* exist. Nothing said what **did** run: a deep agent's delegation reached
`tool_use[node]["ran"]` as the single entry ``task`` however many workers it
delegated to and whichever ones they were, so a run that used both declared
workers and a run that used the anonymous built-in ``general-purpose`` left the
identical record.

Two defects in one entry, and this module answers both:

- **the record could not name the worker**, which is the one fact
  `subagents.py` exists to be strict about;
- ``task`` is `deepagents`' own tool name (`deepagents/middleware/subagents.py`,
  ``name="task"``), and portability guardrail 4 says our own vocabulary goes on
  our own records. It is not only a record: `silent_node_warnings` prints
  ``ran`` back to a reader — *"Node "deep" ran task and then ended its turn"* —
  so a vendor's internal spelling was reaching a user surface.

**The name is reachable without touching a `deepagents` internal**, and that
was measured rather than assumed (live, `ollama:gpt-oss:120b-cloud`,
`.scratch/stress-2026-08-29/workflows/stress-deep`): the delegating `AIMessage`
carries ``{"name": "task", "args": {"description": …, "subagent_type":
"data-classifier"}}`` and the worker's answer comes back as a ``ToolMessage``
named ``task`` with that call's id. Both are already in the list `tool_report`
walks; nothing here imports `deepagents` or reaches past the message rail.

**Tolerant in reading, strict in trusting.** The arguments alone are a *request*
— `deepagents` answers an unknown ``subagent_type`` with the plain sentence
below and no worker runs at all — so a name is only recorded once the paired
answer shows it was accepted. A run whose only delegation was refused therefore
records nothing under `ran`, exactly as `production-ready/98` settled for a tool
name the runtime refused: it reached nothing, so it is not a use. And a
delegation that *did* answer but whose worker cannot be named still records
`DELEGATION_UNNAMED` — the fact is not dropped just because the name is
missing, and no name is invented to carry it.
"""

from __future__ import annotations

import re
from typing import Any

#: `deepagents`' own delegation tool. **The one place this repository spells
#: it**, so the vendor's vocabulary stops here and never reaches a record, a
#: warning sentence or a reader.
DELEGATION_TOOL = "task"

#: The argument that names the worker, on both the sync and the async form of
#: that tool (`deepagents/middleware/subagents.py`, `task` and `atask`).
WORKER_ARGUMENT = "subagent_type"

#: Our own vocabulary for a delegation, on `tool_use[node]["ran"]` beside the
#: ordinary tool names. Prefixed rather than bare so a reader can tell a worker
#: from a tool without a second key, and so a worker sharing a tool's name
#: cannot be read as that tool having run.
DELEGATION_PREFIX = "delegate:"

#: A delegation that answered and whose worker could not be named — a `task`
#: answer with no call to pair it to, or a call carrying no `subagent_type`.
#: Recorded rather than dropped: *that* a worker ran is a fact, and losing it
#: would tell `used_no_tools` a node did nothing.
DELEGATION_UNNAMED = "delegate"

#: `deepagents`' answer when the model names a worker that was never declared.
#: It arrives as an ordinary successful `ToolMessage`, so nothing else would
#: separate it from a worker's real report.
_NO_SUCH_WORKER = re.compile(
    r"^\s*We cannot invoke subagent .* because it does not exist", re.IGNORECASE
)


def delegation_record(worker: str) -> str:
    """How one worker's name appears on the record."""
    return f"{DELEGATION_PREFIX}{worker}"


def _requested_workers(messages: Any) -> dict[str, str]:
    """`tool_call_id -> the worker the model asked for`, from the calls alone.

    A request, and never yet a fact: `delegations_by_call` is what turns one of
    these into a record, and only for the ones an answer bears out.
    """
    requests: dict[str, str] = {}
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            if not isinstance(call, dict):
                continue
            if str(call.get("name") or "") != DELEGATION_TOOL:
                continue
            call_id = str(call.get("id") or "")
            args = call.get("args")
            worker = ""
            if isinstance(args, dict):
                worker = str(args.get(WORKER_ARGUMENT) or "").strip()
            if call_id:
                requests[call_id] = worker
    return requests


def delegations_by_call(messages: Any) -> dict[str, str]:
    """`tool_call_id -> our record name`, for the delegations that reached a worker.

    Keyed by call id rather than by worker name because the same worker is
    routinely handed two different tasks in one turn, and each answer has to be
    resolvable on its own.

    A call with no answer is a request the loop never got back — omitted, for
    the reason the module docstring gives about a refusal.
    """
    requests = _requested_workers(messages)
    resolved: dict[str, str] = {}
    for message in messages or []:
        if getattr(message, "type", None) != "tool":
            continue
        if str(getattr(message, "name", "") or "") != DELEGATION_TOOL:
            continue
        if getattr(message, "status", None) == "error":
            continue
        content = str(getattr(message, "content", "") or "")
        if _NO_SUCH_WORKER.match(content):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if not call_id:
            continue
        worker = requests.get(call_id, "")
        resolved[call_id] = delegation_record(worker) if worker else DELEGATION_UNNAMED
    return resolved


def is_delegation(name: Any) -> bool:
    """Whether a `ran` entry names a delegation rather than a tool."""
    text = str(name or "")
    return text == DELEGATION_UNNAMED or text.startswith(DELEGATION_PREFIX)
