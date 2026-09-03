"""What a stored run teaches, read back offline and named as data.

`a-run-that-teaches/01`. The owner watched a profiler and wrote one sentence:

> *3.5 mins, 4 tool calls, called 3 same tools -> answers one different ->
> answer correct -> move to next execution step*

It reads as one observation. It is three signals and a label, they have
different costs, and this module is where they stop being one thing.

| | signal | here |
| --- | --- | --- |
| **A** | same tool, same arguments, **identical** result | `REDUNDANT_TOOL_CALL` |
| **B** | same tool, same arguments, **different** result | `UNSTABLE_TOOL_RESULT` |
| **C** | a run took N minutes and M tool calls | a field on the finding, never a finding |
| **D** | *"answer correct"* | nothing in the store carries it — `a-run-that-teaches/02` |

## A and B are two findings because they have two remedies

**A is waste.** The same question asked twice and answered the same way is a
lap the run did not need. It costs tokens and seconds and changes nothing, and
the fix is usually a note the agent already had — `abc/tool_notes` exists for
exactly that.

**B is information, and the more valuable of the two.** The same question
answered differently means either the world moved between the calls — a real
fact about the data source, which belongs in a lens declaration — or the tool
is non-deterministic. Reporting it as waste would lose the interesting case,
so it has its own name and inherits none of A's remedy.

## Why the calls come from the checkpointer and not from `RunRecord.statements`

The ticket named `statements` first, and on this machine it holds nothing.
Measured over both `runs.sqlite` files that exist here — 39 turns across
`stress-review`, `stress-deep`, `stress-parallel-drop`, `stress-bad-*` and
a private NL2SQL package — `statements` was `[]` on **every row**. It is not
a defect in
that column: `executed_statements` admits only an argument some recogniser
accepted as a *statement*, which is `looks_like_sql_query` and nothing else, so
a registry lookup or a policy read is correctly absent from it.

The tool calls a run actually made are in the checkpointer, and
`api/threads._ToolCallReader` already pairs each request with the answer that
landed in the next superstep. So this module reads what already reads them, and
the run store supplies the rows that say which threads to look at and what each
turn cost.

## The unit is the thread, and the honesty that costs

Tool calls are stored per conversation and nothing splits them by turn. A
thread usually holds one, and then a finding is a run's finding. When it holds
more, the calls are still analysed together — the message channel is
cumulative, so a second turn genuinely had the first turn's result in front of
it, and asking again is the same waste — and the finding carries
`thread_tool_calls`, named for the thread rather than for the run, so nobody
reads a conversation's total as a turn's.

**And the read is bounded, so the finding says which of the two it is.**
`run_findings` takes a `limit` and hands it to `read_thread`, which keeps the
newest that many checkpoints. On a real 346-checkpoint thread in this
checkout, the default of 200 saw 89 of the 133 tool calls, emitted 8 findings
instead of 9, and quoted `thread_tool_calls=89` — a third of the evidence
invisible, one finding lost outright, and the only cost figure a card could
have quoted understated by 44. The read *reported* the bound all along, on its
response; the finding never repeated it, so a fifth of a conversation and all
of it arrived at a consumer identically shaped (`kanban-patrol/11`). Now
`RunFinding.truncation` carries the read's own `ThreadTruncation` — whether,
and at what limit — and while it is set `calls` and `thread_tool_calls` are
floors rather than exact figures.

The number itself is untouched, deliberately. Raising the default trades one
silent wrongness for a slower read, and the defect here was never the bound;
it was that the bound's consequence went unsaid.

## What counts as the same call, and what that misses

**Normalised arguments**: parsed as JSON and re-emitted with sorted keys and no
whitespace, so `{"a":1,"b":2}` and `{"b": 2, "a": 1}` are one call. Text that
is not JSON is compared stripped. List order is left alone, because it means
something.

Three things it misses, stated rather than implied:

- **A spelling the model chose.** `{"service": "billing-service"}` and
  `{"service_name": "Billing"}` are one question to a person and two calls
  here. Both shapes are in the real store. Closing it needs the tool's own
  schema, and a normaliser that guessed would accuse a run of repeating itself
  for asking two genuinely different things.
- **Anything past 4,000 characters.** `api/threads` caps a rendered value.
  This line used to end *"though it appends the true length, so two long
  values of different sizes still differ"*, which is true and was doing the
  work of a claim it does not make: two values of the **same** length truncate
  to the same 4,000 characters and the same `(+N chars)` suffix, and were
  reported as a repeat. It bites the largest payloads — a query against a wide
  schema, a document pasted into a call — which are the ones a
  `REDUNDANT_TOOL_CALL` is least helpful about being wrong on. A truncated
  argument is now refused rather than grouped (`grouping_key`), so this is a
  miss and no longer a false finding.
- **Where a call happened.** Two workers of one fan-out that each look the same
  thing up are reported as a repeat, because the run paid for both.

**A call whose arguments we do not know is not a call at all**, and that
rule was bought with evidence. `_ToolCallReader` reports a `ToolMessage` whose
request is gone with no arguments — a truncated history, or a thread joined
mid-run — and grouped on `""` those are "the same call" by construction while
their results differ because they answered different questions. On the two real
stores that produced **three B findings, every one of them false**, and zero
survive the rule. B's true count on real data is nought, which is a result:
this machine's tools are stable, and the detector says so instead of being
tuned until it fires.

## Why there is no C

`launch-readiness/109` measured 97-99% of a turn as model latency the owner
chose — 14.02 s of wall against 0.14 s of ours. A detector reporting *the model
was slow* fires every night and names nothing anybody can act on. The only
honest form is relative to a workflow's own history, and the real store cannot
carry one: `stress-review` spans 7.35 s to 78.40 s across six runs, and
`stress-parallel-drop` 2.20 s to 7.34 s across eleven. An outlier rule over
that spread reports the spread.

And the deeper reason is D. Without an outcome, a long run is not a defect —
it may be the run that got the answer right. So duration stays where the
owner's own sentence put it: **attached to the observation, as the size of what
the waste cost**, and never an alarm of its own.

## Where it runs, and what it may not become

Offline, over the two local sqlite files, opening no model and no socket.
Never inside a run: `109` established that our per-turn overhead is 0.4-1.0%
and this must not be a second thing that can slow a turn down.

A finding quotes tool names and arguments, which is developer content by
`api/audience.py`'s own table, so `audience` is a **required keyword with no
default** — the discipline `read_run_bursts` established in
`the-boundary-nobody-checked/02`, so a reader cannot inherit a refusal
silently. There is no customer-shaped version of a finding, so a customer is
told nothing rather than told less. The result text is never carried at all:
equality is the only thing this module needs from it, a digest proves that, and
the result is the largest and most customer-shaped payload in a run.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, Field

from openstategraph.api.audience import Audience
from openstategraph.api.schemas import ThreadHistoryResponse, ThreadTruncation
from openstategraph.api.threads import read_thread
from openstategraph.compile.workflow_compiler import parse_failure_marker
from openstategraph.run_sinks import RunRecord

__all__ = [
    "REDUNDANT_TOOL_CALL",
    "UNSTABLE_TOOL_RESULT",
    "NODE_FAILURE",
    "FindingRun",
    "RunFinding",
    "grouping_key",
    "normalised_arguments",
    "run_findings",
]

#: A — the same call, answered the same way. Waste.
REDUNDANT_TOOL_CALL = "redundant-tool-call"

#: B — the same call, answered differently. Information.
UNSTABLE_TOOL_RESULT = "unstable-tool-result"

#: C — a node failed. `kanban-patrol/22`: already sitting in the checkpointer,
#: in `outputs[node_id]`, via the same marker `node_failure_warnings` decodes
#: for a live run. Fires on **one** occurrence, not two — unlike A and B, a
#: repeat is not what makes a failure worth reporting.
NODE_FAILURE = "node-failure"

#: The tail `api.threads._cap` appends to a value it had to cut short.
#:
#: Matched rather than imported. The cap is a **display** decision made one
#: layer down for a rendering door, and this module is reading that projection
#: to do analysis — so it recognises the mark by its shape and asks that layer
#: for nothing. `tests/test_the_same_call_twice_is_two_findings.py` pins the
#: shape against `_cap` itself, so a change to the marker is a red test here
#: rather than a detector that silently stops recognising it.
_TRUNCATED = re.compile(r"… \(\+\d+ chars\)\Z")

#: How much of a digest is carried. Long enough that two answers colliding is
#: not a thing that happens, short enough to read in a ticket.
_DIGEST_CHARS = 12


class FindingRun(BaseModel):
    """One turn a finding was seen in, and what that turn cost.

    This is where C lives. The owner's sentence attached the minutes and the
    call count to the observation, not to an alarm, and so does this.
    """

    workflow_slug: str = ""
    thread_id: str = ""
    #: The run row's own wall clock, ISO-8601 with an offset, exactly as
    #: `RunRecord.at` spells it.
    at: str = ""
    seconds: float = 0.0
    #: Grader laps. With `seconds` this is the shape of the run the waste
    #: happened inside.
    attempts: int = 0


class RunFinding(BaseModel):
    """One thing a stored run teaches, as data rather than as a sentence.

    `a-run-that-teaches/03`'s scheduled agent has to act on these without
    re-deriving them from prose, so a finding names itself, cites the
    checkpoints it was read from, and carries the runs it was seen in.
    """

    #: `REDUNDANT_TOOL_CALL` or `UNSTABLE_TOOL_RESULT`. A plain string for
    #: `RunRecord.kind`'s reason: a consumer meeting a name it does not know
    #: must skip it rather than fail to parse the list.
    name: str
    thread_id: str = ""
    #: The package whose namespaces made these calls — `kanban-patrol/12`, and
    #: **never** the thread's first run row. A run row has no namespace column
    #: (`run_sinks.RunRecord`), so it cannot be asked where a call happened; a
    #: checkpoint can, because LangGraph's metadata carries the
    #: `workflow_slug` of whichever graph wrote it.
    #:
    #: `""` when the calls came from namespaces that resolve to more than one
    #: package, and it means *this finding does not claim a package* rather
    #: than *nobody recorded one*. A reader renders it as nothing either way
    #: (`kanban-patrol/02`); 6 of 20 run rows in this checkout carry `""`
    #: outright, so it was always a value a consumer had to handle.
    workflow_slug: str = ""
    tool: str = ""
    #: The normalised arguments every call in this group shared.
    arguments: str = ""
    #: How many times the run made this call.
    calls: int = 0
    #: How many different answers came back. `1` is A; anything more is B.
    distinct_results: int = 0
    #: A digest per distinct answer — never the answer. Ordered as first seen.
    result_digests: list[str] = Field(default_factory=list)
    #: The citation: the checkpoint id of every superstep that made the call,
    #: in the order they were made. A reader can open each one.
    checkpoints: list[str] = Field(default_factory=list)
    #: Every tool call on the conversation, not on one turn — see the module
    #: docstring on why the unit is the thread.
    thread_tool_calls: int = 0
    #: How many distinct `ThreadStep.checkpoint_ns` values the grouped calls
    #: came from — `kanban-patrol/13`. `calls=19` alone cannot tell a reader
    #: whether that was one node called nineteen times in sequence (`1`) or
    #: nineteen parallel fan-out workers each called once (`19`, equal to
    #: `calls`), and the two have different remedies: a tool note for the
    #: first, a shared lookup *across* workers for the second. Pooling itself
    #: is unchanged — a finding still counts what the run paid for
    #: (`run_findings.py:99`'s own recorded decision) — this only adds the
    #: shape a reader needs to tell the two apart.
    distinct_namespaces: int = 0
    runs: list[FindingRun] = Field(default_factory=list)
    #: What the read this finding was assembled from left behind, or `None`
    #: when it left nothing behind (`kanban-patrol/11`).
    #:
    #: `run_findings` takes a `limit` and hands it to `read_thread`, which
    #: keeps the newest that many checkpoints. Until this field existed, a
    #: finding built from a window was shaped exactly like one built from a
    #: whole conversation: on a real 346-checkpoint thread here, the default
    #: of 200 saw 89 of 133 tool calls, emitted 8 findings of 9, and every one
    #: of the 8 quoted `thread_tool_calls=89` with nothing to mark it.
    #:
    #: So `calls` and `thread_tool_calls` are counts over what was *read*, and
    #: whenever this field is set they are floors rather than figures anybody
    #: may publish as exact. A `REDUNDANT_TOOL_CALL` saying `calls=10` when the
    #: true figure is 15 is not a rounding error, it is a false statement.
    #:
    #: **It is the read's own verdict, carried, and never a second opinion
    #: assembled here.** `read_thread` reads one row past its own bound to
    #: decide this; a copy computed from `len(steps)` against `limit` would be
    #: a second answer to a question that has one, and that is how two
    #: computations of one fact come to disagree.
    truncation: ThreadTruncation | None = None


def normalised_arguments(text: str) -> str:
    """One call's arguments in a form two spellings of the same call share.

    JSON re-emitted with sorted keys and no whitespace; anything that will not
    parse, stripped and left alone. See the module docstring for the three
    things this deliberately does not reach.
    """
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return text.strip()
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def grouping_key(name: str, arguments: str) -> tuple[str, str] | None:
    """The key two calls share when they are the same call — or `None`.

    **This is the only place in this module that builds a grouping key, and
    that is the fix rather than an accident of layout** (`the-cost-of-one-more/
    09`). The rule *"a call whose arguments we do not know is not a call"* was
    written at the call site as `if not call.arguments: continue`, one line
    above `key = (call.name, normalised_arguments(call.arguments))`. The guard
    read the raw string and the key read the normalised one, so `'   '` — which
    is truthy, and `''` once normalised — walked straight past a guard that
    existed to refuse exactly that key. A guard beside a key is a guard with a
    door next to it; a guard *inside* the key has none, and
    `test_the_same_call_twice_is_two_findings.py` counts the doors rather than
    trusting this paragraph.

    Three answers, and the module's own rule — tolerant in reading, strict in
    trusting — decides all three:

    - **Nothing left after normalising** (`''`, `'   '`, `'\t\n'`) → `None`.
      Not *"called with nothing"* but *"we do not know what it was called
      with"*, and unknown is not the same as the other unknown. This is the
      rule the three false B findings bought, now spelled over the value that
      is actually compared.
    - **A value the display layer had to cut short** → `None`. Two distinct
      arguments of the same length truncate to the same 4,000 characters and
      the same `(+N chars)` suffix, and the honest answer to *"are these the
      same call?"* over two values we hold only the heads of is **we do not
      know**. Refusing costs a real repeat of a very large argument, which is a
      miss; grouping costs a false accusation, which is a published untruth
      about somebody's run. The narrowness is the safety.
    - **`{}`, `[]`, `null`, and every other value that parsed** → a key.
      `{}` means *this tool takes no arguments and was called twice*, which is
      a known argument and a real repeat. It is the one collapse this module
      performs deliberately and it was nowhere stated, so it is stated here:
      an empty *object* groups; an empty *string* does not.

    What it does **not** do is reach past the cap for the untruncated value.
    That is the deeper fix — the finding path reading the checkpoint itself
    rather than a projection `api/threads` shaped for a display door — and it
    is a change to that module's readers, so it is out of scope here and
    recorded as such in the ticket rather than left as an implication.
    """
    normalised = normalised_arguments(arguments)
    if not normalised:
        return None
    if _TRUNCATED.search(arguments):
        return None
    return (name, normalised)


def run_findings(
    savers: Iterable[Any],
    records: Sequence[RunRecord],
    *,
    audience: Audience | str,
    limit: int = 200,
) -> list[RunFinding]:
    """Every finding in these runs, read back out of the local files.

    `savers` is what `api.threads.savers_for` hands back and `records` is what
    `run_sinks.read_runs` hands back — this composes the two readers rather
    than opening a store of its own, which is what keeps one store one store.

    Nothing is called again: this is a recording being read. A run with nothing
    to teach contributes nothing, and a machine with nothing to teach returns
    an empty list, which is an answer.
    """
    if Audience(audience) is not Audience.DEVELOPER:
        return []

    by_thread: dict[str, list[RunRecord]] = {}
    for record in records:
        if record.thread_id:
            by_thread.setdefault(record.thread_id, []).append(record)

    found: list[RunFinding] = []
    savers = list(savers)
    for thread_id, rows in by_thread.items():
        history = read_thread(
            savers, thread_id, audience=Audience.DEVELOPER, limit=limit
        )
        if history is not None:
            found.extend(_findings_in(history, thread_id, rows))
    return found


def _node_failures(
    history: ThreadHistoryResponse,
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """`{(node, reason): [(checkpoint_id, checkpoint_ns), ...]}` — `kanban-patrol/22`.

    The namespace rides along for `kanban-patrol/12`: a failure inside a
    mounted package belongs to that package, and the only thing that can say
    which package a step came from is the namespace it was checkpointed under.

    Reads `outputs[node_id]` at every step, same channel
    `node_failure_warnings` reads for a live run's own report. `values`
    renders a dict channel as capped JSON (`api/threads._cap`) — a wide
    `outputs` map can truncate mid-object, so a parse failure is skipped, not
    raised: the same "cannot say anything about this" rule `grouping_key`
    already follows for a call this module cannot group.
    """
    failures: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for step in history.steps:
        raw = step.values.get("outputs")
        if not raw:
            continue
        try:
            outputs = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(outputs, dict):
            continue
        for node, value in outputs.items():
            reason = parse_failure_marker(str(value or ""))
            if reason is None:
                continue
            failures.setdefault((str(node), reason), []).append(
                (step.checkpoint_id, step.checkpoint_ns)
            )
    return failures


def _findings_in(
    history: ThreadHistoryResponse, thread_id: str, rows: Sequence[RunRecord]
) -> list[RunFinding]:
    """The findings in one conversation, grouped by the call that was made."""
    # `checkpoint_ns` alongside the checkpoint id and result — `kanban-patrol/13`.
    # It's `step.checkpoint_ns`, the raw namespace, and deliberately not
    # `step.namespace`: that field merges a fan-out's sibling instances into
    # one display name on purpose, which is exactly the shape this needs to
    # keep apart.
    groups: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    total = 0
    for step in history.steps:
        for call in step.tool_calls or []:
            total += 1
            key = grouping_key(call.name, call.arguments)
            if key is None:
                # Not a call this module can say anything about — see
                # `grouping_key` for the three shapes and why each is refused.
                # The call is still counted: `thread_tool_calls` is what the
                # conversation cost, not what was groupable.
                continue
            groups.setdefault(key, []).append(
                (step.checkpoint_id, step.checkpoint_ns, call.result)
            )

    # Which package owns each namespace, off the checkpoints' own metadata —
    # `kanban-patrol/12`. Built from the whole history rather than per group,
    # because a namespace's package is a property of the namespace.
    package_of: dict[str, str] = {}
    for step in history.steps:
        if step.workflow_slug:
            package_of.setdefault(step.checkpoint_ns, step.workflow_slug)

    runs = [
        FindingRun(
            workflow_slug=row.workflow_slug,
            thread_id=row.thread_id,
            at=row.at,
            seconds=row.seconds,
            attempts=row.attempts,
        )
        for row in rows
    ]
    # The thread's own fallback, used only where the checkpoints named no
    # package at all: the run rows agree on one, or nobody claims one. This is
    # deliberately not the old `first non-empty row wins` — that rule is what
    # `kanban-patrol/12` exists to retire.
    thread_slugs = {row.workflow_slug for row in rows if row.workflow_slug}
    thread_slugs |= set(package_of.values())
    fallback = next(iter(thread_slugs)) if len(thread_slugs) == 1 else ""
    # Read once, reused below — `test_the_finding_repeats_the_read_s_verdict`
    # pins this at one call site so a second one is never the stale one.
    truncation = history.truncation

    found: list[RunFinding] = []
    for (tool, arguments), seen in groups.items():
        if len(seen) < 2:
            continue
        digests: list[str] = []
        for _, _, result in seen:
            digest = _digest(result)
            if digest not in digests:
                digests.append(digest)
        found.append(
            RunFinding(
                name=REDUNDANT_TOOL_CALL if len(digests) == 1 else UNSTABLE_TOOL_RESULT,
                thread_id=thread_id,
                workflow_slug=_attributed_slug(
                    (namespace for _, namespace, _ in seen), package_of, fallback
                ),
                tool=tool,
                arguments=arguments,
                calls=len(seen),
                distinct_results=len(digests),
                result_digests=digests,
                checkpoints=[checkpoint for checkpoint, _, _ in seen],
                distinct_namespaces=len({namespace for _, namespace, _ in seen}),
                thread_tool_calls=total,
                runs=runs,
                truncation=truncation,
            )
        )

    # C — a node failure. Fires on one occurrence, not two: unlike A/B, a
    # single failure is already real information, not waste that only
    # matters once repeated.
    for (node, reason), steps in _node_failures(history).items():
        found.append(
            RunFinding(
                name=NODE_FAILURE,
                thread_id=thread_id,
                workflow_slug=_attributed_slug(
                    (namespace for _, namespace in steps), package_of, fallback
                ),
                tool=node,
                arguments=reason,
                calls=len(steps),
                distinct_results=1,
                result_digests=[_digest(reason)],
                checkpoints=[checkpoint for checkpoint, _ in steps],
                thread_tool_calls=total,
                runs=runs,
                truncation=truncation,
            )
        )
    return found


def _attributed_slug(
    namespaces: Iterable[str], package_of: dict[str, str], fallback: str
) -> str:
    """The package these namespaces came from, or `""` when they disagree.

    `kanban-patrol/12`. Strict in both directions, and both are the point:

    - Every namespace in the group must be one we hold a package for, and they
      must all name the **same** package. A group spanning a mount and its
      parent is two packages' calls pooled into one finding, and no single
      name is true of it.
    - A namespace we hold no package for is not assumed to be the parent's.
      It falls to `fallback`, which is a name only when the whole thread named
      exactly one package — on a thread that mounts anything, that is `""`.

    A finding that claims nothing routes a developer nowhere, which is worse
    than useless only if the alternative is right. Claiming the parent when
    the calls came from the mount routes them to the wrong package, which is
    worse still: it is a wrong answer wearing a confident one's clothes.
    """
    seen = set(namespaces)
    resolved = {package_of[namespace] for namespace in seen if namespace in package_of}
    if len(resolved) > 1:
        return ""
    candidate = resolved.pop() if resolved else fallback
    if any(namespace not in package_of for namespace in seen) and candidate != fallback:
        # A namespace nothing named, on a thread that named more than one
        # package. It could be either of them, so it is neither.
        return ""
    return candidate


def _digest(result: str) -> str:
    """A short fingerprint of an answer, standing in for the answer itself."""
    return hashlib.sha256(result.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
