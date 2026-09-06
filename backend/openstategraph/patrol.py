"""The in-built patrol — `kanban-patrol/07`'s missing prerequisite.

`07` wrote the async/SSE machinery for "a patrol that outlives the board" on
the assumption a patrol function already existed to run inside it. It did
not — no read-classify-file loop existed at all, sync or async, model or
not. This module is that loop.

**Deterministic, no model, on purpose for this first cut.** `05` ("the
patrol needs a model") is a separate, still-open question about a richer,
judgment-driven classifier; this module proves the *shape* — read once,
classify without asking anyone, skip what's filed, file what's new — works
end to end, so `07`'s durability layer has something real underneath it.

**One classification function, reused by everything that files a card.**
The manual demo earlier in this project's history made these calls by
feel, one at a time — this is that judgment made a rule, so two patrol runs
over the same evidence agree.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from openstategraph.api.audience import Audience
from openstategraph.api.services import WorkflowServices
from openstategraph.api.threads import savers_for
from openstategraph.kanban_store import open_kanban_store
from openstategraph.run_findings import (
    EVERY_TOOL_CALL_FAILED,
    NODE_FAILURE,
    REDUNDANT_TOOL_CALL,
    UNSTABLE_TOOL_RESULT,
    RunFinding,
    run_findings,
)
from openstategraph.run_sinks import read_runs, run_store_path


#: **The self-reference marker** — `kanban-patrol/08`.
#:
#: A patrol that reads every recorded thread eventually reads the threads its
#: own work produced. An agent attending card X asks the workflow a question
#: to reproduce the defect; that question is a run, in a thread, with
#: findings of its own, and `02`'s dedup key does not save it — the thread is
#: genuinely new, so the next patrol files a card about the work done on the
#: last card, and the board fills with its own shadow.
#:
#: The rule names such runs by something the run **already records**:
#: `RunRecord.session_id`, the field that says which *sitting* a run belongs
#: to. No column, no migration, no new schema. `kind` was the other
#: candidate and is wrong: a run an agent made while working a card still
#: cost money and still belongs in `runs list` and in the spend walk, and
#: `kind` is what decides whether a reader sees the row at all.
#:
#: Two prefixes because there are two producers with different lifetimes: a
#: card's work spans however many threads it takes (`card:<task_id>`), and a
#: patrol driver's sitting is its own (`patrol:<whatever>`). Both group
#: several threads, which is the axis `session_id` was settled on — this is
#: not a per-call mint, it is a caller naming the sitting it is in.
PATROL_SESSION_PREFIX = "patrol:"
CARD_SESSION_PREFIX = "card:"
SELF_REFERENTIAL_SESSION_PREFIXES = (PATROL_SESSION_PREFIX, CARD_SESSION_PREFIX)


def card_session_id(task_id: str) -> str:
    """The `session_id` every run made while working `task_id` must carry.

    One function so the CLI, the MCP door, the board's copied instruction and
    the bundled skill file all spell it the same way — a marker with two
    spellings excludes half of what it names.
    """
    return f"{CARD_SESSION_PREFIX}{task_id}"


def is_patrols_own_work(session_id: str) -> bool:
    """Was this run produced by the patrol, or by an agent working a card?

    Matched at the **start** of the value, never anywhere in it: a sitting
    called `wildcard:7` is ordinary traffic, and a substring match would have
    quietly stopped filing its findings.
    """
    return session_id.strip().startswith(SELF_REFERENTIAL_SESSION_PREFIXES)


@dataclass(frozen=True)
class FindingClassification:
    kind: str
    category: str
    priority: str
    #: The evidence, in the classifier's own words — `ticket-forge`'s rule:
    #: cite the finding's own fields, never a plausible elaboration on top.
    reason: str
    #: The symptom, never the fix — `ticket-forge`'s other rule.
    title: str


#: Azure AD's own error code, when the refusal carried one
#: (`osg-agent-experience/73`, which is what made it reachable — the ODBC
#: driver had been swallowing it and hanging instead). `AADSTS7000222` is
#: *the client secret is expired*, and a card that holds it and does not print
#: it has thrown away the one string that ends the investigation.
_AAD_CODE = re.compile(r"\bAADSTS\d+\b")


def refusal_task_id(project_id: str, refusal: str) -> str:
    """The one card forty runs of one refusal share — `osg-agent-experience/74`.

    `02`'s key is the **thread**, which is right for waste: a repeat is a
    property of one conversation. A refusal is not — the try project's
    warehouse refused every call for a day across however many threads
    somebody happened to open, and a per-thread key would have filed a card
    per thread for one expired secret.

    A digest rather than the refusal itself, because a `task_id` is a key in a
    store and appears in a URL, and a driver's message is prose with quotes
    and newlines in it. Twelve characters, the same width and the same reason
    as `run_findings._DIGEST_CHARS`.
    """
    digest = hashlib.sha256(refusal.encode("utf-8")).hexdigest()[:12]
    return f"{project_id}:refusal:{digest}"


def _tool_types(tool: str) -> list[str]:
    """The node types behind the tool names a finding reported.

    Resolved through `process_tool_layer` — the read-only door onto the
    registry the runtime itself binds from — rather than a table here. A
    second table would be a second answer to *what type is `mssql_query`*,
    and this module would be the one holding the stale copy.

    A name nothing in the registry claims resolves to nothing and is simply
    absent from the card, which is the honest answer for a package's own
    `tools/` leaf: the patrol reads a store, not a workspace.
    """
    try:
        from openstategraph.api.registries import process_tool_layer

        builtin, _ = process_tool_layer()
    except Exception:  # pragma: no cover - a registry that will not build
        return []
    names = {part.strip() for part in tool.split(",") if part.strip()}
    return sorted(
        node_type
        for node_type, leaf in builtin.items()
        if str(getattr(leaf, "name", "")) in names
    )


def connection_variables(node_types: list[str]) -> list[str]:
    """The environment variables these tool types read to reach their world.

    **Names, never values** — nothing here touches `os.environ`, and a card is
    a board row that whoever opens the board can read.

    A registry rather than a chain of `if`s, so a second connector is a
    registration and not an edit here (`CLAUDE.md`'s **O**), and every entry
    imports the tuple its own module already owns rather than restating it —
    a variable's name spelled twice is the drift this repository names by
    name.
    """
    found: list[str] = []
    for node_type in node_types:
        supply = _CONNECTION_VARS.get(node_type)
        if supply is None:
            continue
        for name in supply():
            if name not in found:
                found.append(name)
    return found


def _mssql_variables() -> tuple[str, ...]:
    from openstategraph.mssql_connection import AAD_VARS, PART_VARS, SQL_AUTH_VARS
    from openstategraph.prebuilt_mssql import DEFAULT_CONNECTION_ENV

    return (DEFAULT_CONNECTION_ENV, *PART_VARS, *AAD_VARS, *SQL_AUTH_VARS)


#: `node_type -> the names of the variables its connection reads`. Lazy
#: callables because a leaf's module pulls optional drivers in behind it and
#: the patrol must stay a reader of files.
_CONNECTION_VARS: dict[str, Callable[[], tuple[str, ...]]] = {
    "tool.mssql-query": _mssql_variables,
}


def _every_call_failed_classification(finding: RunFinding) -> FindingClassification:
    """`osg-agent-experience/74`'s card, in the finding's own words.

    Four things, in the order somebody standing at a red board needs them:
    what was refused, in the refusal's own text; which tool type it was, so
    the reader knows what to go and configure; which variables that type
    reads, by name; and the AAD code when Azure AD supplied one, because that
    string is the end of the investigation rather than the start of it.
    """
    refusal = finding.arguments.strip() or "no message"
    types = _tool_types(finding.tool)
    reason = (
        f"Every one of this run's {finding.calls} tool "
        f"{'call' if finding.calls == 1 else 'calls'} was refused, all of them "
        f'the same way: "{refusal}". Nothing this run answered rests on a '
        "result, because no result arrived."
    )
    if types:
        reason += f" The tool is {finding.tool} ({', '.join(types)})."
    else:
        reason += f" The tool is {finding.tool}."
    variables = connection_variables(types)
    if variables:
        reason += (
            " Its connection is configured by "
            f"{', '.join(variables)} — check those variables are set and "
            "current; their values are not printed here and must not be."
        )
    code = _AAD_CODE.search(refusal)
    if code:
        reason += (
            f" Azure AD named the cause itself: {code.group(0)} — look that "
            "code up rather than re-running the query."
        )
    return FindingClassification(
        kind="bug",
        category="bug",
        priority="high",
        reason=reason,
        title=f"Every {finding.tool} call in this run was refused the same way",
    )


def _redundant_tool_call_priority(calls: int) -> str:
    if calls >= 5:
        return "high"
    if calls >= 3:
        return "med"
    return "low"


def classify_finding(finding: RunFinding) -> FindingClassification:
    """One deterministic answer per finding — kanban-patrol/07.

    A judgement made once, here, rather than by whoever happens to be
    filing a card that day. `05`'s model-driven classifier, if it ever
    lands, replaces this function's *body*, never its callers.
    """
    if finding.name == EVERY_TOOL_CALL_FAILED:
        return _every_call_failed_classification(finding)
    if finding.name == NODE_FAILURE:
        return FindingClassification(
            kind="bug",
            category="bug",
            priority="high",
            reason=f"Node '{finding.tool}' failed after retries: {finding.arguments}",
            title=f"'{finding.tool}' failed after retries",
        )
    if finding.name == UNSTABLE_TOOL_RESULT:
        return FindingClassification(
            kind="grilling",
            category="gap",
            priority="med",
            reason=(
                f"{finding.tool} answered {finding.distinct_results} different ways across "
                f"{finding.calls} calls in one thread — non-deterministic, or the world moved "
                "between calls."
            ),
            title=f"{finding.tool} gave {finding.distinct_results} different answers to one question",
        )
    if finding.name == REDUNDANT_TOOL_CALL:
        distinct = finding.distinct_namespaces
        calls = finding.calls
        if distinct <= 1:
            # `kanban-patrol/13`'s first bucket: every call the run's own
            # `_findings_in` grouped came from the same namespace — one node
            # asked the same question `calls` times in sequence. Real
            # sequential repetition, and the wording stays close to what
            # shipped before this ticket.
            reason = (
                f"{finding.tool} called {calls} times with an identical result in one "
                "thread — real cost, no error, fix is a tool note."
            )
            title = f"{finding.tool} was asked {calls} times in one thread, same answer every time"
            priority = _redundant_tool_call_priority(calls)
        elif distinct >= calls:
            # The other extreme: every one of the `calls` calls came from its
            # own namespace — pure fan-out, no repetition at all. The run
            # still paid for every one of them (`run_findings.py:99`'s own
            # pooling decision, unchanged), but it is not the same kind of
            # waste a sequential repeat is: nobody wrote a loop, so a tool
            # note fixes nothing here. The remedy, if any, is a lookup shared
            # *across* workers — a different change, in a different place —
            # so this is filed lower than the same call count would be if it
            # were one node repeating itself.
            reason = (
                f"{finding.tool} was called once each by {calls} parallel workers, same "
                "answer every time — fan-out, not repetition. The run still paid for all "
                f"{calls} calls, but there is no loop to fix here; if it's worth avoiding, "
                "the remedy is a lookup shared across workers, not a tool note."
            )
            title = f"{finding.tool} was called by {calls} parallel workers, same answer every time"
            priority = "low"
        else:
            # In between: some fan-out, and some real repetition inside at
            # least one namespace. Neither canned sentence describes this
            # honestly, so it says both counts rather than picking one.
            reason = (
                f"{finding.tool} was called {calls} times across {distinct} namespaces, same "
                "answer every time — some of this is fan-out breadth and some is real "
                "repetition inside at least one of those namespaces; a tool note helps the "
                "repeats, a shared lookup across workers helps the fan-out."
            )
            title = f"{finding.tool} was called {calls} times across {distinct} namespaces, same answer every time"
            priority = _redundant_tool_call_priority(calls)
        return FindingClassification(
            kind="task",
            category="gap",
            priority=priority,
            reason=reason,
            title=title,
        )
    # An unrecognised finding name — `run_findings`'s own tolerant-reader
    # rule, one layer up: a consumer meeting a name it does not know skips
    # it rather than guessing at what it means.
    return FindingClassification(
        kind="grilling",
        category="gap",
        priority="med",
        reason=f"Unrecognised finding type {finding.name!r} — filed for a human to classify.",
        title=f"An unclassified finding on {finding.tool or 'this thread'}",
    )


@dataclass(frozen=True)
class PatrolResult:
    filed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total_findings: int = 0
    #: Threads dropped before reading, because a run in them was marked as the
    #: patrol's own work (`kanban-patrol/08`). Reported rather than silent:
    #: an exclusion nobody can see is indistinguishable from a patrol that
    #: found nothing.
    excluded: list[str] = field(default_factory=list)


def run_patrol(
    *,
    project_id: str,
    workflows_root: Path,
    savers: list[Any] | None = None,
    records: list[Any] | None = None,
    on_card_filed: Callable[[str, str], None] | None = None,
) -> PatrolResult:
    """Read every finding, file whatever is new, skip whatever is already
    filed. kanban-patrol/07's prerequisite, kanban-patrol/02's own rule:
    once a card exists for a `task_id`, a later patrol never touches it
    again, even if the same finding reappears.

    **One card per thread for waste, by construction** (`task_id = project_id
    + thread_id`) — a thread with more than one finding is classified by its
    single most severe finding (`NODE_FAILURE` > `UNSTABLE_TOOL_RESULT` >
    `REDUNDANT_TOOL_CALL`), and the reason names how many others were seen
    rather than silently dropping them.

    **And one card per refusal for `EVERY_TOOL_CALL_FAILED`**
    (`osg-agent-experience/74`), which is the one kind whose unit is not the
    thread: a credential that has stopped working refuses every call in every
    conversation anybody opens, so the thread key would file a card per
    thread for one problem. `refusal_task_id` is that key, and the card
    carries the count across runs.

    `savers`/`records` are the same injection seam `run_findings` itself
    exposes — a test operates on fake checkpoints rather than a real
    checkpointer, the same reasoning `WorkflowStore` and `NodeRuntime`
    already follow. `None` computes the real ones, which is every caller
    outside a test.

    **`on_card_filed`, kanban-patrol/07's async/SSE half.** Called with
    `(task_id, title)` the instant each card is written, so an HTTP route
    running this loop in the background can publish a `patrol.progressed`
    event without this module knowing SSE, a broadcaster, or FastAPI exist —
    the same one-way dependency `run_findings.py` already keeps toward
    `api/`: this module is imported by the route, never the reverse.
    `None` (every caller outside the route, including the CLI's synchronous
    `patrol run`) costs one `is None` check per card and changes nothing
    else about the loop.
    """
    if savers is None or records is None:
        services = WorkflowServices(workflows_root=workflows_root)
        savers = savers_for(services) if savers is None else savers
        records = read_runs(run_store_path(workflows_root)) if records is None else records

    # `kanban-patrol/08`'s self-reference exclusion, applied before the read
    # rather than after it. A thread is one conversation and the message
    # channel is cumulative, so a single marked turn makes every call in that
    # thread part of the same piece of work — a later unmarked turn had the
    # marked turn's tool results in front of it, and a repeat across the two
    # is the agent's own. Excluding the whole thread is the conservative
    # direction: a wrong exclusion costs one card nobody files, a wrong
    # inclusion costs a board that reports itself.
    #
    # Unlike `22`'s already-filed skip, this thread is not read and its
    # findings are not counted. That skip hides a duplicate of real evidence;
    # this one hides a reflection, and counting a reflection puts a number on
    # the board that means nothing.
    excluded = sorted(
        {
            record.thread_id
            for record in records
            if record.thread_id and is_patrols_own_work(record.session_id)
        }
    )
    if excluded:
        records = [record for record in records if record.thread_id not in excluded]

    findings = run_findings(savers, records, audience=Audience.DEVELOPER)

    # Two passes, because this map has two units of "one problem"
    # (`osg-agent-experience/74`). Waste is a property of a conversation, so
    # `02`'s key is the thread. A refusal is not: one expired client secret
    # refused every call for a day across every thread anybody opened, and a
    # per-thread key would have filed a card per thread for it.
    by_refusal: dict[str, list[RunFinding]] = {}
    by_thread: dict[str, list[RunFinding]] = {}
    for finding in findings:
        if finding.name == EVERY_TOOL_CALL_FAILED:
            by_refusal.setdefault(finding.arguments, []).append(finding)
        else:
            by_thread.setdefault(finding.thread_id, []).append(finding)

    severity = {NODE_FAILURE: 0, UNSTABLE_TOOL_RESULT: 1, REDUNDANT_TOOL_CALL: 2}

    store = open_kanban_store(workflows_root)

    filed: list[str] = []
    skipped: list[str] = []

    for refusal, refusal_findings in by_refusal.items():
        task_id = refusal_task_id(project_id, refusal)
        try:
            store.read_card(task_id)
            skipped.append(task_id)
            continue
        except KeyError:
            pass

        classification = classify_finding(refusal_findings[0])
        threads = len({f.thread_id for f in refusal_findings})
        calls = sum(f.calls for f in refusal_findings)
        reason = classification.reason + (
            f" Seen in {threads} run{'' if threads == 1 else 's'}, "
            f"{calls} refused call{'' if calls == 1 else 's'} in total — one "
            "card, because it is one problem."
        )
        store.file_card(
            task_id=task_id,
            board="workflows",
            kind=classification.kind,
            category=classification.category,
            title=classification.title,
            priority=classification.priority,
            area="backend",
            priority_reason=reason,
        )
        filed.append(task_id)
        if on_card_filed is not None:
            on_card_filed(task_id, classification.title)

    for thread_id, thread_findings in by_thread.items():
        task_id = f"{project_id}:{thread_id}"
        try:
            store.read_card(task_id)
            skipped.append(task_id)
            continue
        except KeyError:
            pass

        thread_findings.sort(key=lambda f: severity.get(f.name, 99))
        primary = thread_findings[0]
        classification = classify_finding(primary)
        reason = classification.reason
        if len(thread_findings) > 1:
            reason += f" ({len(thread_findings) - 1} other finding(s) also seen in this thread.)"

        store.file_card(
            task_id=task_id,
            board="workflows",
            kind=classification.kind,
            category=classification.category,
            title=classification.title,
            priority=classification.priority,
            area="backend",
            priority_reason=reason,
        )
        filed.append(task_id)
        if on_card_filed is not None:
            on_card_filed(task_id, classification.title)

    return PatrolResult(
        filed=filed, skipped=skipped, total_findings=len(findings), excluded=excluded
    )
