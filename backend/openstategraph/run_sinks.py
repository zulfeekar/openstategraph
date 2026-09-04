"""Where a finished run is written down, and who else gets told.

**Tier 1 — semver-public.** `IRunSink` is a contract a third party satisfies
from their own distribution, so it is as irreversible as anything this
framework publishes, and it is designed complete at birth for that reason —
see the Protocol's own docstring.

## The finding this module exists because of

`memory-and-replay/43` and `launch-readiness/99` read as two features and are
one, and the reason is that **capture was never the gap**:

- the checkpointer already holds every question and answer of every run, keyed
  by `thread_id`, in a sqlite file on the machine that ran it, and nothing
  sweeps it;
- `api/threads.py` already reads that back — as a listing, as one thread's
  supersteps, with per-step tokens and per-step tool calls, over CLI *and*
  HTTP, as text *and* as JSON;
- `executed_statements` already publishes what a run executed, scrubbed;
- `abc/tool_notes` already lets a run record facts about itself.

What did not exist is the **socket**: a way for the person installing this to
say *where those rows also go*. And the proof that it was missing is that we
had already answered the question once, for exactly one destination, with no
way to answer it again — `loader._append_trace`, a hardcoded JSON-lines file
behind a `trace_file=` keyword. That is a sink. It was simply the only one, and
it was welded in.

So this module generalises a branch that already existed rather than inventing
a recording that did not. `JsonlRunSink` below **is** `_append_trace`, moved,
byte-for-byte in its output — including its refusal to write the answer text.

## The default goes nowhere, and that is a rule rather than a preference

`CLAUDE.md`: *never send a user's graph to a third party.* It is the reason
`draw_mermaid()` is the only drawing call in this repository — `draw_mermaid_png()`
posts the graph to Mermaid.Ink. A telemetry pipe enabled on install is the same
breach with a different content type, and it is worse in one respect: a diagram
leaks a topology, while a run record carries the question a customer asked.

| sink | where the data goes |
| --- | --- |
| **`SqliteRunSink` (the default, zero-config)** | **nowhere.** A file beside the checkpoints, on the machine that ran the workflow. |
| `JsonlRunSink` | a path the operator named, and only when they named one |
| OpenTelemetry, LangSmith, their own | wherever they point it — **and none of them ships here** |

The last row is the load-bearing one. No network exporter is written in this
module, disabled or otherwise: a disabled exporter is one environment variable
away from being enabled by somebody who has not read this paragraph, and
`guardrails/07` — the only consumer with a concrete need today — needs a local
number, not a collector. Somebody who wants OTel writes twenty lines against
`IRunSink` and registers it, which is the whole point of the seam.

## What a sink may carry, and why it cannot bypass the redaction seam

A `RunRecord` is assembled in exactly one place — `run_journal.run_turn`, the
seam every run door opens (`memory-and-replay/44`); this module stores what it
hands over and never builds a row of its own. It is assembled from what the
doors already publish, and the one field that quotes a customer's own data
through a tool — `statements` — is copied from `executed_statements.statements_executed` and from nowhere else.
That function carries `one-chinook-honest/30`'s two layers: the record holds
the single argument some recogniser accepted as a *statement* and **never the
argument map**, so an MCP tool's `connection_string`, `token` or `password`
argument is not recorded at all rather than recorded and then scrubbed; and a
credential embedded *inside* a statement is replaced by a marker that says
something was removed.

**The reason that holds under a telemetry pipe is structural, not procedural.**
There is no second path to the data. A sink is handed the record and cannot ask
for more, so widening what may leave the machine means widening
`statements_executed`, which is a change to the module the seam is declared in
and which owes that module's own test — the one proving an ordinary statement
is still left byte-for-byte alone.

A record is **developer-audience** by the same reasoning `api/audience.py`
applies to `statements`: it quotes node ids, tool names and literal values. It
is not gated by `Audience` here because a sink is not a response — nobody
receives it by asking over HTTP; an operator receives it by having configured
their own machine to keep it. The gate is *registration*, and it is the
strongest one available, because an unregistered sink is not code that declined
to run, it is code that is not installed.

## The key, settled against what already exists rather than chosen

The owner asked for *session id + something*. This installation already
distinguishes the two, and the distinction is right:

- **`thread_id`** is LangGraph's own key — what the checkpointer stores under,
  what `POST /api/runs/resume` demands back, and what every run door mints when
  a caller does not supply one. It identifies **one conversation**.
- **`session_id`** already exists beside it in `configurable`, is already
  persisted into checkpoint metadata, and is already a filter on
  `GET /api/threads`. Its documented meaning is a browser-tab grouping that
  **spans threads** and deliberately never enters a Store namespace.

So a session is *not* a thread, the difference is already modelled, and this
store needs no new identity — which is the outcome to want, given that *loop*,
*template* and *slug* each cost a session to untangle here. The row's key is
**`(workflow_slug, thread_id)`**, the same pair `149` chose and the same pair
the editor already treats as conversation identity; `session_id` and
`user_email` ride along as recorded columns, exactly as `ThreadSummary` carries
them. All four names are read from `run_identity.RUN_IDENTITY_KEYS` rather than
spelled again here.

That caveat had a sequel and it is now closed (`memory-and-replay/45`). Until
then **nothing populated `session_id`**: declared, carried, persisted,
filterable, and `""` on every real run, because the editor's client never sent
one — a gap in the *writer*, not in this key. The writer is
`src/core/runtime/browserSession.ts`, which mints one per browser tab in
`sessionStorage` and sends it on all three HTTP doors.

Two things about that value are worth knowing here, because this column is
where they surface. It is **the client's to mint**, which is not a breach of
`principal.py`'s refusal of `user_email`: that rule names values which are
client-supplied *and privilege-bearing*, and a session label keys no namespace
and gates nothing. And it is still **empty on the MCP door**, correctly — an
MCP call has no browser tab, and a per-call mint would make the column a
synonym for `thread_id`. So an empty cell means *this run had no sitting*
rather than *nobody wrote one down*.

## A query and JSON, and they are the same rows

The owner asked for both. `SqliteRunSink` writes **columns, not one JSON blob
per run**, which is the difference between `guardrails/07`'s question being a
query and being a program:

    sqlite3 "$(openstategraph runs path)" \\
      "SELECT workflow_slug, count(*), sum(total_tokens) FROM runs GROUP BY 1"

and `read_runs()` hands the identical rows back as `RunRecord` objects, which
`openstategraph runs list --json` and `openstategraph runs export` print for a
model or a script. Two readers over one table — never two stores, which is the
whole claim of ticket 43 and the thing a separately-assembled JSON view would
quietly end.

**SQLite is the store; JSON is the export.** Asked as an exclusive choice the
two answers each lose something: a JSON file is greppable, diffable and needs no
schema, and is also rewritten whole on every append, unsafe when two processes
run at once, and unable to answer *what has this workflow spent* without a
program; sqlite is queryable, concurrent and indexed, and is already the storage
technology under `state_dir()`. Splitting them along *store* versus *export*
keeps both properties and adds no second source of truth, because the export is
generated from the table every time and is never written back.
"""

from __future__ import annotations

import json
import logging
import os
import base64
import sqlite3
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_serializer, field_validator

from openstategraph.readonly_sqlite import readonly_connection
from openstategraph.run_identity import RUN_IDENTITY_KEYS

logger = logging.getLogger(__name__)

__all__ = [
    "IN_MEMORY_RUN_STORE",
    "IRunSink",
    "JsonlRunSink",
    "RUN_STORE_FILE_NAME",
    "RUN_STORE_PATH_ENV",
    "RunBurst",
    "RunRecord",
    "RunSinkRegistry",
    "SqliteRunSink",
    "default_run_sink_registry",
    "now",
    "publish",
    "read_run_bursts",
    "read_runs",
    "reset_run_sink_registry",
    "run_sink_registry",
    "run_store_path",
]

#: Where the local store is written when the deployment does not say. Named and
#: shaped after `OPENSTATEGRAPH_CHECKPOINT_PATH` deliberately: the two files sit
#: in one directory, are opted out of the same way, and a second convention for
#: the second file would be a second thing to explain.
RUN_STORE_PATH_ENV = "OPENSTATEGRAPH_RUN_STORE_PATH"

#: The opt-out, spelled exactly as the checkpointer's is. A test suite and a
#: deliberately stateless deployment both need the default *exercised* rather
#: than switched off, which is what an in-memory store gives and what
#: `OPENSTATEGRAPH_RUN_STORE_PATH=none` would not.
IN_MEMORY_RUN_STORE = "memory"

#: Beside `checkpoints.sqlite` and `memory.sqlite`, under `state_dir()`.
RUN_STORE_FILE_NAME = "runs.sqlite"

# **No entry-point group is reserved here, and that is deliberate.**
#
# `extensions.py` refuses to reserve a group name it does not read, calling an
# unimplemented one "exactly the decorative contract this work exists to
# remove" — a group name is a promise, it goes into a third party's own
# `pyproject.toml`, and renaming one later un-registers every plugin ever
# shipped against it. Discovery is not implemented in this ticket, so the name
# is not claimed in it either.
#
# A stranger is not blocked meanwhile, which is why this is a deferral and not
# a gap: the owner's ask was *an instance of a class our core recognises*, and
# that works today in one line at start-up —
#
#     from openstategraph.run_sinks import run_sink_registry
#     run_sink_registry().register("acme", AcmeOtelSink())
#
# What an entry point would add is registration without a start-up hook, which
# is a convenience for a `pip install`, not the seam itself.


class RunBurst(BaseModel):
    """One contiguous burst of model output, with the cadence it arrived at.

    `memory-and-replay` 47, and the row that lets a play button claim a
    measurement instead of inventing one. A burst is **one node's output of one
    block kind, uninterrupted** — the model's reasoning and its answer are two
    bursts, a tool's result is a third, and a mounted child's is a fourth.

    ## Why the chunks are packed into a row rather than being rows

    The ticket assumed a tradeoff between perfect cadence and disk, and there
    is none. Measured against four real `gpt-oss:120b-cloud` runs, a row per
    chunk costs 26-107 KiB per run and a burst row costs 5-8 KiB for **the same
    information** — because what a per-chunk row pays for is not the cadence,
    it is repeating one node's identity 242 to 1014 times. So the identity is
    paid once here, and `cadence` carries every chunk's own offset and length,
    delta-encoded. `replay()` gives the chunks back exactly as they arrived.

    That matters more than the bytes: a burst spans a node's whole output, and
    inside one the measured inter-chunk gaps run from 0 ms to 555 ms. A record
    holding only a first and last offset would leave a replay interpolating,
    with a measured p99 error of 470 ms — half a second of stall rendered as
    smooth typing, in a surface whose whole claim is *the Truth*.

    ## What it may be asked, and what it may not

    Every field here is measured. `first_ms`/`last_ms` and every offset in
    `replay()` are the same server-side `elapsedMs` the frame carried on the
    wire (`api/frame_clock.py`) — relative to the stream opening, monotonic,
    and saying nothing about *when* the run happened. The wall anchor is the
    run row's `at`, exactly as it is for a live frame; nothing here restates
    it, so nothing here can disagree with it.

    A run with **no** bursts has no cadence — an old row, a workflow with no
    model in it, a store from before this ticket. That is an absence and it is
    an answer; it is never a run that took zero milliseconds.
    """

    #: The graph node whose output this is, and its subgraph namespace.
    #:
    #: **Inside an agent this is LangGraph's own loop node** — `model`,
    #: `tools` — and not the canvas node a reader drew. `active_node` below is
    #: the one that answers that.
    node: str = ""
    namespace: list[str] = Field(default_factory=list)

    #: The canvas node the run said was working — the `token` frame's own
    #: `activeNode` (`memory-and-replay` 74).
    #:
    #: The frame has carried it since the ticket that put it there, for a
    #: reason that applies here word for word: a `token` frame is the only one
    #: that arrives while a node is **still working**, and `updates` fires on
    #: completion, so anything built from completions alone can only ever say
    #: who last finished. `47` read every other field of that frame and dropped
    #: this one, which left eight of a real nine-burst recording unable to say
    #: whose work they were.
    #:
    #: `""` is *this recording did not say* — an old row, or a frame that named
    #: nobody — and never a node inferred after the fact.
    active_node: str = ""

    #: `text` | `reasoning` — which kind of text, exactly as the `token` frame's
    #: `block` says it. Two blocks are never one burst: a reasoning model's
    #: deliberation and its answer arrive interleaved from one content list,
    #: and folding them together is what ticket 23 exists to have separated.
    block: str = "text"

    #: Who produced it — `model`, `tool`. The `token` frame's `kind`.
    kind: str = ""

    #: The customer channel refused this text. **The bytes are not here**, and
    #: not because they were filtered out: the recorder reads the wire, and
    #: `_token_frame` empties a withheld frame's content before the frame is
    #: built. The flag is kept for the reason the frame keeps it — a withheld
    #: burst still says a node was working, so a customer's replay shows the
    #: stall instead of a hole.
    withheld: bool = False

    #: Which audience's stream produced this. Stored so a reader can refuse:
    #: a developer run's bursts carry developer content, and `38` already found
    #: what happens when a replay door forgets to ask.
    audience: str = ""

    #: The frame `seq` of the first and last chunk. The wire's own dense
    #: counter, so a gap here reads as a dropped frame, which a clock cannot
    #: express.
    first_seq: int = 0
    last_seq: int = 0

    #: Milliseconds from the stream opening to the first and last chunk.
    first_ms: int = 0
    last_ms: int = 0

    #: How many chunks, and how many characters they carried. Stored rather
    #: than derived, for `run_sinks`' own stated reason: a person with
    #: `sqlite3` should be able to ask *how chatty was this node* in SQL.
    chunks: int = 0
    chars: int = 0

    #: The burst's text, concatenated. **The same rule as `RunRecord.answer`,
    #: inherited rather than re-decided** — this is a customer's data, the
    #: local store keeps it, and a sink that carries rows off the machine
    #: writes a count instead.
    text: str = ""

    #: Every chunk's own offset and length, delta-encoded. `replay()` is how it
    #: is read; nothing else should decode it.
    cadence: bytes = b""

    #: Recording stopped here — the run produced more bursts than `BURST_CAP`.
    #: True on the last burst kept and nowhere else, so a reader can say *the
    #: recording ends here* rather than *the run ended here*. A bound on
    #: memory during a runaway loop, never a sweep of anything written.
    capped: bool = False

    @field_serializer("cadence")
    def _cadence_out(self, value: bytes) -> str:
        """Base64 on the way out, so a record is JSON.

        Not decoration. `IRunSink` exists so a third party can write these rows
        wherever they like, and the obvious way to do that is
        `json.dumps(record.model_dump())` — which raises on `bytes`. A contract
        that cannot survive its own obvious use is a trap, and this is the same
        `runs export` relies on to carry the cadence out of a store somebody is
        about to truncate.
        """
        return base64.b64encode(value).decode("ascii")

    @field_validator("cadence", mode="before")
    @classmethod
    def _cadence_in(cls, value: Any) -> bytes:
        """And back in, so the round trip closes. A blob this build cannot
        decode costs the per-chunk detail and not the burst — `replay`'s rule,
        applied one layer earlier."""
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            try:
                return base64.b64decode(value, validate=True)
            except (ValueError, TypeError):
                return b""
        return b""

    def duration_ms(self) -> int:
        """How long this burst took. Measured, and `0` genuinely means instant
        — a one-chunk burst arrived at one moment. *Unknown* is the absence of
        the burst, never a zero on it."""
        return max(0, self.last_ms - self.first_ms)

    def replay(self) -> list[tuple[int, str]]:
        """`(elapsedMs, text)` for every chunk, exactly as it arrived.

        The claim this whole record exists to make good. Decoded from
        `cadence`; a blob this build cannot read costs the per-chunk detail and
        not the burst, because a replay that shows the whole burst at its first
        offset is degraded and a replay that raises is gone.
        """
        offsets, lengths = _decode_cadence(self.cadence)
        if not offsets or len(offsets) != len(lengths):
            return [(self.first_ms, self.text)] if self.chunks else []
        out: list[tuple[int, str]] = []
        at = 0
        elapsed = self.first_ms
        for step, length in zip(offsets, lengths):
            elapsed += step
            out.append((elapsed, self.text[at : at + length]))
            at += length
        return out


def _encode_cadence(offsets: list[int], lengths: list[int]) -> bytes:
    """One burst's per-chunk cadence, as compactly as it is worth being.

    A varint count, then that many gap varints, then that many length varints,
    then zlib. Gaps between consecutive chunks rather than absolute offsets,
    because a model streams in single-digit milliseconds and a gap fits in one
    byte where an offset needs three.

    **Counted, never terminated.** A separator byte was the obvious encoding
    and is wrong here for a reason worth keeping written down: a gap of zero
    milliseconds is the *most common* value in a real stream (a measured p50 of
    1 ms, with runs of consecutive zeros), and it encodes as the same `0x00` a
    terminator would. The first burst decoded would have ended at its first
    chunk.
    """
    return zlib.compress(
        _varints([len(offsets)]) + _varints(offsets) + _varints(lengths), 6
    )


def _decode_cadence(blob: bytes) -> tuple[list[int], list[int]]:
    """`_encode_cadence` undone, or two empty lists. Never raises: see
    `replay`."""
    if not blob:
        return [], []
    try:
        values = _read_varints(zlib.decompress(blob))
    except (zlib.error, ValueError, IndexError):
        return [], []
    if not values:
        return [], []
    count = values[0]
    if count < 0 or len(values) < 1 + 2 * count:
        return [], []
    return values[1 : 1 + count], values[1 + count : 1 + 2 * count]


def _varints(values: list[int]) -> bytes:
    out = bytearray()
    for value in values:
        value = max(0, int(value))
        while True:
            piece = value & 0x7F
            value >>= 7
            out.append(piece | (0x80 if value else 0))
            if not value:
                break
    return bytes(out)


def _read_varints(raw: bytes) -> list[int]:
    """Every varint in the blob, in order."""
    values: list[int] = []
    value = shift = 0
    for byte in raw:
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
            continue
        values.append(value)
        value = shift = 0
    return values


class RunRecord(BaseModel):
    """One thing worth writing down about a run — usually a finished turn.

    **The extension point is this model, not the Protocol above it**, and that
    asymmetry is deliberate. A `runtime_checkable` Protocol is a load-bearing
    shape: a member added to it un-satisfies every sink anybody shipped, at the
    next `isinstance`, in their install rather than ours. A *field* added here
    is one every existing sink survives, because a sink reads the fields it
    knows and a reader that does not recognise a `kind` ignores the row.

    That is what makes `43`, `99`, `142` and `guardrails/07` one feature: they
    want the same rows, and the ones they do not share arrive as fields rather
    than as methods.
    """

    #: What this row is. `"run"` is the only kind written today; a human's
    #: verdict on an answer (`launch-readiness/142`) is the next one, and it
    #: needs a field, not a `feedback()` method on every sink in the world.
    #:
    #: A plain string rather than an enum, and read tolerantly: a consumer that
    #: meets a kind it does not know must skip the row, never fail to parse the
    #: file. Narrowing this to a `Literal` would make every future kind a
    #: breaking change for every reader pinned to today's release.
    kind: str = "run"

    #: When, as an ISO-8601 string with an offset — the spelling `_append_trace`
    #: already used, kept so a trace file's `ts` and this column agree.
    at: str = ""

    # -- who the run was for. Never spelled here: see `RUN_IDENTITY_KEYS`. ----
    workflow_slug: str = ""
    thread_id: str = ""
    session_id: str = ""
    user_email: str = ""

    question: str = ""
    #: **The answer text, and only the local store keeps it.**
    #:
    #: This is the field that makes replay and `99`'s pattern store possible,
    #: and it is also the one field in a run that reliably contains a
    #: customer's data. Both facts are true at once, so the resolution is not
    #: to drop it but to keep the default destination local: the record carries
    #: it, `SqliteRunSink` stores it on the machine that produced it, and
    #: `JsonlRunSink` — a file that gets committed, emailed and pasted into
    #: issues — still writes only its length.
    answer: str = ""

    seconds: float = 0.0
    #: How many grader laps the run took. With `decisions`, this is what says
    #: *which way the graph went*, which is what a wrong answer is diagnosed
    #: from.
    attempts: int = 0
    decisions: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    #: A node wrote the failure sentinel. Deliberately not folded into an
    #: absent answer: `silent_node_warnings` records that a workflow may
    #: legitimately answer with nothing at all.
    failed: bool = False

    #: Model name -> what that model reported spending. **Keyed by model, never
    #: summed into one integer** (`workflow-gallery` 35) — "which node cost
    #: what" is only answerable while they are apart. An empty mapping means
    #: nobody reported, which is *unknown* and never zero.
    #:
    #: This is the column `guardrails/07` needs, and the reason it is collected:
    #: a step budget bounds laps, not spend, so a `Send` fan-out to five deep
    #: agents is arbitrarily expensive inside a legal number of supersteps. A
    #: ceiling cannot be argued for, let alone set, against numbers nobody kept.
    usage: dict[str, dict[str, Any]] = Field(default_factory=dict)

    #: What the run executed, exactly as `executed_statements` published it —
    #: `{node, tool, statement, result, truncated}` and nothing else. Copied,
    #: never re-derived: see this module's docstring for why that is what stops
    #: a sink bypassing the redaction seam.
    #:
    #: This is also what `launch-readiness/99` needs and could not have. Its
    #: admission rule is *executed successfully **and** passed the grader*, and
    #: those are two columns of one row here — `statements` and `decisions` —
    #: which is precisely the argument that it is not a second store.
    statements: list[dict[str, Any]] = Field(default_factory=list)

    #: How the run's output actually arrived — `memory-and-replay` 47.
    #:
    #: **A field, not a method on `IRunSink`**, and that is this module's own
    #: rule being used rather than bent: the Protocol is two members and closed
    #: at birth, and the extension point is this model. A sink somebody shipped
    #: against today's Protocol receives the cadence with nothing changed,
    #: reads it if it wants it, and ignores it if it does not.
    #:
    #: Empty is the ordinary case and it is an answer, not a gap: a blocking
    #: door streams nothing, a workflow of function nodes produces no tokens,
    #: and every row written before this ticket has none.
    bursts: list[RunBurst] = Field(default_factory=list)

    def total_tokens(self) -> int:
        """Every model's reported total for this row, added up.

        A convenience for a cost query and **not** a replacement for `usage`:
        the mapping stays keyed by model, because a single integer cannot
        answer which model was expensive. Zero here may mean *free* or may mean
        *nobody reported*; `usage == {}` is how you tell.
        """
        return sum(int(spent.get("total_tokens") or 0) for spent in self.usage.values())


@runtime_checkable
class IRunSink(Protocol):
    """Where a run record goes. **The contract consumers depend on.**

    A `Protocol` rather than an ABC for the reason `ITool` and `IRouter` both
    record: a third party satisfies it from their own distribution without
    inheriting from us, and requiring inheritance to participate is what makes
    a hierarchy closed for extension. It is the owner's *"an instance of a
    class our core recognises and whose public methods it calls"*, literally.

    **Two members, and it is complete at birth.** `runtime_checkable` tests
    member *presence*, so a third member added later un-satisfies every sink
    shipped against this release, silently, at the next `isinstance` — a
    breaking change wearing an addition's clothes. `ITool`, `IRouter`,
    `IGrader`, `IOrchestrator` and `IAgent` were each left untouched for that
    reason and this one is designed not to need it: **new observations arrive
    as fields on `RunRecord`, never as methods here.**

    `close` is not decoration. Every network sink batches, and a batch needs a
    moment to flush; a sink holding a file or a sqlite handle needs one to
    release it. A sink with nothing to do implements it as `pass`, which costs
    one line and is the difference between an operator's last ten runs arriving
    and being lost on shutdown.

    Neither method may raise usefully: `publish` isolates both, because
    diagnostics must never cost the run that produced them.
    """

    def record(self, record: RunRecord) -> None:
        """Write one row down. Called once per finished turn, in-process."""
        ...

    def close(self) -> None:
        """Flush and release. Idempotent — it may be called more than once."""
        ...


class RunSinkRegistry:
    """Which sinks this process writes to. The seventh extension point of its kind.

    Same behaviour as `SearchBackendRegistry`, `NodeTypeRegistry` and the rest,
    because `CLAUDE.md` asks for the behaviour rather than a common address: a
    duplicate id throws, `upsert` is how you say you meant it, `list()`
    enumerates in registration order, and a fresh one is constructible so one
    test's sink cannot reach another test's run.

    The **name is the registrar's, not the sink's** — the one deliberate
    difference from `SearchBackendRegistry`, which reads `backend.name`. A sink
    is often somebody else's object, and requiring a `name` attribute on it
    would be a third member of `IRunSink` in all but spelling, imposed on every
    satisfier so that this class could avoid an argument.
    """

    def __init__(self) -> None:
        self._sinks: dict[str, IRunSink] = {}

    def register(self, name: str, sink: IRunSink) -> None:
        """Add a sink under `name`, refusing to replace one silently."""
        if name in self._sinks:
            raise ValueError(
                f'Run sink "{name}" is already registered. Two claims on one name '
                "is ambiguity, not precedence — use upsert() if you meant to "
                "replace it."
            )
        self._sinks[name] = sink

    def upsert(self, name: str, sink: IRunSink) -> None:
        """Register or replace. Saying you meant it is the whole difference."""
        self._sinks[name] = sink

    def get(self, name: str) -> IRunSink | None:
        return self._sinks.get(name)

    def list(self) -> tuple[tuple[str, IRunSink], ...]:
        """Every sink with its name, in registration order."""
        return tuple(self._sinks.items())

    def close(self) -> None:
        """Release every sink. Never raises — see `publish`'s reasoning."""
        for name, sink in self.list():
            try:
                sink.close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Run sink %r did not close cleanly: %s", name, exc)


def run_store_path(workflows_root_dir: Path | str | None = None) -> Path | None:
    """Where the local run store lives, or `None` for an in-memory one.

    The same shape as `memory.checkpoint_path`, one file along: the environment
    variable wins outright and `memory` is its opt-out, otherwise it is
    `state_dir()/runs.sqlite`. Asking never creates anything — `state_dir`'s own
    rule, and what lets this package be pointed at a read-only mount.
    """
    configured = os.environ.get(RUN_STORE_PATH_ENV, "").strip()
    if configured:
        if configured.lower() in (IN_MEMORY_RUN_STORE, ":memory:"):
            return None
        return Path(configured).expanduser().resolve()

    from openstategraph.state_dir import state_dir

    return state_dir(workflows_root_dir) / RUN_STORE_FILE_NAME


#: The columns of the `runs` table, in order. One list, read by the writer and
#: by the reader, because two spellings of a schema is how a store starts
#: answering a question with a column that no longer means what it did.
_COLUMNS: tuple[str, ...] = (
    "kind",
    "at",
    *RUN_IDENTITY_KEYS,
    "question",
    "answer",
    "seconds",
    "attempts",
    "failed",
    "total_tokens",
    "decisions",
    "warnings",
    "usage",
    "statements",
)

#: The columns stored as JSON text rather than as a scalar.
_JSON_COLUMNS = frozenset({"decisions", "warnings", "usage", "statements"})

#: Anything not named here is `TEXT`. Sqlite would take the rows either way —
#: it is dynamically typed — but a person reading `.schema` at a terminal is
#: one of this store's three readers, and `seconds REAL` tells them something
#: `seconds TEXT` does not.
_COLUMN_TYPES: dict[str, str] = {
    "seconds": "REAL",
    "attempts": "INTEGER",
    "failed": "INTEGER",
    "total_tokens": "INTEGER",
}


#: The columns of the `run_bursts` table, in order — the same one-list rule
#: `_COLUMNS` states for `runs`, and for the same reason.
#:
#: **A second table, argued rather than assumed.** `43` says there is one
#: store and it is right; this is one store with two tables, which is a
#: different claim. A burst is not a run — there are 6 to 30 of them per turn —
#: so it cannot be a column, and a second *file* would mean two things to
#: export, two to delete, and a `runs export` that told half the truth. Ticket
#: 37 priced a frame table once and concluded it was not needed; that was for
#: the profiler it built, which reads finished state. Playback needs cadence,
#: which no finished state holds, so this reverses that conclusion out loud.
#:
#: `run_rowid` is `runs.rowid`, read back from the insert in the same
#: transaction — a join, rather than a column on `runs`, because a run has many
#: bursts. This comment used to end *"no column is added to `runs`,
#: deliberately: this module has no migration machinery"*, which was true of
#: that decision and was the whole statement of the problem for the next one:
#: see `_reconcile` below, which is now the migration machinery, and
#: `the-boundary-nobody-checked/07` for what it does not cover.
_BURST_COLUMNS: tuple[str, ...] = (
    "run_rowid",
    "ord",
    "node",
    "active_node",
    "namespace",
    "block",
    "kind",
    "withheld",
    "audience",
    "first_seq",
    "last_seq",
    "first_ms",
    "last_ms",
    "chunks",
    "chars",
    "text",
    "cadence",
    "capped",
)

_BURST_TYPES: dict[str, str] = {
    "run_rowid": "INTEGER",
    "ord": "INTEGER",
    "withheld": "INTEGER",
    "first_seq": "INTEGER",
    "last_seq": "INTEGER",
    "first_ms": "INTEGER",
    "last_ms": "INTEGER",
    "chunks": "INTEGER",
    "chars": "INTEGER",
    "cadence": "BLOB",
    "capped": "INTEGER",
}


#: `runs.at` read as the instant it names, rather than as the text it is.
#:
#: `now()` stores local wall clock with a numeric offset —
#: `2026-08-30T01:06:29+0200` — and `ORDER BY at DESC` compared that as a
#: **string**, which compares the offset as text. Two rows written either side
#: of a DST fall-back, or by a laptop that crossed a timezone, come back in the
#: order of their local clocks rather than the order they happened
#: (`the-cost-of-one-more/11`):
#:
#: | stored `at` | the instant | text order |
#: | --- | --- | --- |
#: | `2026-10-25T02:50:00+0200` | 00:50Z | second |
#: | `2026-10-25T02:30:00+0100` | 01:30Z | **first** |
#:
#: **Nothing about the stored value changes, and that is the decision.** The
#: three candidates were a new UTC column, re-spelling `now()`, and deriving
#: the key at read time. Re-spelling makes it worse at the boundary — the same
#: instant in two spellings sorts a day apart, so new rows would list among
#: yesterday's, and either every row moves or none does. A new column is a
#: backfill over every row a store has ever held, on the first open after an
#: upgrade, on a file whose only guarantee is that it grows; it is exactly what
#: `_reconcile` records itself as not doing (*"there is no derived value a
#: backfill would have to recompute"*), and an interrupted one leaves a store
#: listing in neither ordering. Deriving costs neither. A row written years ago
#: sorts correctly the moment this expression is used against it, there is no
#: state a migration can be halfway through, and `at` stays what a person reads
#: in `runs list` — local wall clock, which is what they want and which a UTC
#: column would have taken away or duplicated.
#:
#: **And it is still O(limit)**, because sqlite indexes expressions: the
#: indexes in `_open` are built on this text and satisfy the `ORDER BY` that
#: names it. That is the whole reason the derived answer is affordable.
#:
#: Three parses, tried in order, because a store holds every spelling it was
#: ever written in and may not lose the rows it cannot read:
#:
#: 1. `%z`'s offset has no colon (`+0200`) and sqlite's date functions require
#:    one, so the colon is spliced in — `at` is fixed-width to character 22.
#: 2. Anything sqlite parses as it stands: `Z`, `+02:00`, or no offset at all.
#: 3. The raw string, so a value neither parse understands keeps the ordering
#:    it had rather than collapsing to `NULL` alongside every other one.
CHRONOLOGICAL = (
    "COALESCE("
    "strftime('%Y-%m-%dT%H:%M:%SZ',substr(at,1,22)||':'||substr(at,23,2)),"
    "strftime('%Y-%m-%dT%H:%M:%SZ',at),"
    "at)"
)


#: How many run ids one cadence query may name.
#:
#: `_attach_bursts` binds one SQL variable per row id, and sqlite refuses a
#: statement with more than `SQLITE_LIMIT_VARIABLE_NUMBER` of them — 32,766 on
#: the build this checkout links, and **999** on anything older than 3.32.
#: `openstategraph runs export` defaults to `--limit 100000`, so a store that
#: only grows reaches the ceiling on its own and the export lost the cadence it
#: exists to carry (`the-cost-of-one-more/08`). The bound is named rather than
#: written into a loop so that a test can shrink it and reproduce the failure
#: at forty rows instead of thirty-three thousand.
#:
#: Chosen under the oldest ceiling rather than this build's, because the number
#: that matters is the one on the machine the store is read on.
CADENCE_BATCH = 900


class RunCadenceUnavailable(Exception):
    """A cadence read this build could not perform — not *a store with none*.

    The two were one `except` and one `logger.debug`, which is how 33,000 rows
    came back with `bursts = []` and exit code 0. They are different answers:
    a store written before `memory-and-replay/47` has no `run_bursts` table and
    *no cadence* is the truth about it, while a refused query means the file
    holds cadence this read did not get. Only the second raises, and it exists
    so `runs export` can refuse rather than write a file missing the half it
    was run for.
    """


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    """What this file actually holds for `table`, in its own order.

    The one question both halves of the schema answer ask. `table` is a module
    constant at every call site and never a value from anywhere.
    """
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))


def _reconcile(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    types: dict[str, str],
) -> None:
    """Give `table` any column `columns` names and the file lacks. Nothing else.

    **Reflection, not a version ledger** (`the-boundary-nobody-checked/07`).
    `PRAGMA user_version` plus an ordered list of steps is the conventional
    answer and it restates the schema a second time — which is the defect
    `_COLUMNS`' own comment names, *"two spellings of a schema is how a store
    starts answering a question with a column that no longer means what it
    did"*. Reading the file and comparing it against the one declaration cannot
    drift from it, needs no number to be bumped by somebody who remembers, and
    is idempotent, so a downgrade and an upgrade and a fresh install are one
    path. What it costs is history: nothing records *when* a column arrived, so
    no future step can be conditioned on the version a store was written by.
    That is affordable here because this store holds only what a run reported —
    there is no derived value a backfill would have to recompute.

    **What this does not survive, stated rather than implied.** It is additive
    and only additive:

    - a **renamed** column arrives as a new empty one, and the old one keeps the
      data with nothing to move it;
    - a **changed type** is not applied — sqlite does not rewrite a table for
      `ADD COLUMN`, and it is dynamically typed anyway, so old rows keep the
      values they had;
    - a **dropped** column stays, deliberately: the store's standing rule is
      that nothing recorded is ever removed, and a column this build does not
      know may be one a build somebody else is running does;
    - a column that is `NOT NULL` without a default, `UNIQUE`, or a foreign key
      is refused by sqlite's own `ADD COLUMN` and would land in the caller's
      warning.

    Any of those is a change that needs a migration written for it, and this is
    the point at which somebody would have to write one. What it buys is that
    the change the schema has actually made four times in one day — *one more
    column* — costs nothing.
    """
    present = set(_table_columns(connection, table))
    for name in columns:
        if name in present:
            continue
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {name} {types.get(name, 'TEXT')}"
        )


def _tables() -> tuple[tuple[str, tuple[str, ...], dict[str, str]], ...]:
    """Every table this store holds, each with the one declaration of its columns.

    Enumerated rather than written out twice inside `_open`, because the order
    the three phases of `_prepare` run in is load-bearing and a list is the
    only place a third table can be added.

    A function rather than a module constant so that it reads the two column
    tuples *when it is asked*: a constant would capture them at import, and the
    schema-drift tests simulate an older build by shortening `_COLUMNS` — a
    fixture that a tuple would silently stop reaching, which is a second
    spelling of the schema arriving by the back door.

    The cadence table (`memory-and-replay/47`) is created on the same open as
    `runs` so the two cannot exist apart: a burst insert shares the run row's
    transaction, so a mismatch on either would lose both.
    """
    return (
        ("runs", _COLUMNS, _COLUMN_TYPES),
        ("run_bursts", _BURST_COLUMNS, _BURST_TYPES),
    )

#: The four `at`-keyed indexes `the-cost-of-one-more/11` replaced, dropped on
#: sight so a store carries one set rather than two.
#:
#: **That is not the store sweeping.** The standing rule is that no *run* is
#: ever removed; an index holds nothing that is not in the rows and is rebuilt
#: from them, so replacing one loses nothing a reader could ask for. Keeping
#: them beside the four below would have doubled index maintenance on every
#: write, forever, on the one structure this product guarantees only grows —
#: and would have kept the wrong ordering indexed. An older build reopening the
#: file recreates its own; both sets are correct for the build that made them.
_SUPERSEDED_INDEXES: tuple[str, ...] = (
    "runs_thread",
    "runs_workflow_at",
    "runs_at",
    "runs_session_at",
)

#: Every index, as `(name, table, keys)`.
#:
#: The four questions this store is asked — *out of everything*, *this
#: workflow*, *this session*, *this conversation* — each of them **newest
#: first**. Without an index the unfiltered one read and sorted every row ever
#: written to print a page of 25 (`the-cost-of-one-more/08`), and a store that
#: never sweeps makes that a cost that only ever rises. Sqlite carries `rowid`
#: as the last column of every index, so each of these satisfies the trailing
#: `rowid DESC` outright as well. `--thread` gets one where `08` left it with a
#: temp sort on the argument that one conversation is bounded by a person's
#: patience: that was right, and it is now free rather than bought — the index
#: it already needed for the equality search is the same index, one column
#: longer. `run_bursts` is asked one question: *this run, in order*.
#:
#: **Keyed on `CHRONOLOGICAL`, not on `at`.** The column is local wall clock
#: with an offset and sorting it as text is not sorting it by time
#: (`the-cost-of-one-more/11`); an index on `at` made the wrong order fast.
#: Sqlite indexes expressions, so the derived key costs a store no column, no
#: backfill and no state a migration can be halfway through.
#:
#: A name here is also what `_prepare` reads to know which columns must exist
#: before it runs, which is why the keys are data and not four `execute` calls.
_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("runs_at_utc", "runs", CHRONOLOGICAL),
    ("runs_workflow_utc", "runs", f"workflow_slug, {CHRONOLOGICAL}"),
    ("runs_session_utc", "runs", f"session_id, {CHRONOLOGICAL}"),
    ("runs_thread_utc", "runs", f"thread_id, {CHRONOLOGICAL}"),
    ("run_bursts_run", "run_bursts", "run_rowid, ord"),
)


def _holds_the_runs_table(connection: sqlite3.Connection) -> bool:
    """Can this file answer for the table a run is about to be written to?

    The one question that separates *the schema could not be finished* from
    *this is not a database I can use* (`the-cost-of-one-more/12`), asked of
    the file rather than inferred from the exception text — sqlite says `file
    is not a database` for one of those and `no such column` for the other, and
    matching on either would be reading a message rather than a state.
    """
    try:
        return bool(_table_columns(connection, "runs"))
    except sqlite3.Error:
        return False


def _prepare(connection: sqlite3.Connection) -> None:
    """Bring the file up to this build's schema: tables, then columns, then indexes.

    **Three passes, and the order is the ticket** (`the-cost-of-one-more/12`).
    These statements used to be written out one after another with
    `_reconcile` last, and `CREATE TABLE IF NOT EXISTS` is a no-op against a
    table that already exists in an older shape — so a file written before
    `session_id` existed reached `CREATE INDEX … ON runs (session_id, …)` with
    no such column, the whole open failed, `_broken` latched, and every run
    that process recorded afterwards was dropped.

    Moving the two `_reconcile` calls up would have fixed that instance and
    left the class: the next statement somebody wrote above them would reopen
    it, and nothing but a comment would have said not to. So the phases are
    three loops over declarations instead, and an index is added by naming it
    in `_INDEXES`, where it cannot be placed before the columns it names
    exist. `test_a_store_one_column_behind_keeps_its_runs.py` reads `_INDEXES`
    and builds one old-shaped store per column any of them mentions, so a
    fifth index on a sixteenth column is covered on the day it is declared
    rather than on the day somebody remembers this paragraph.

    Nothing in `_reconcile` depends on an index, checked rather than assumed:
    it reads `PRAGMA table_info` and issues `ALTER TABLE … ADD COLUMN`.
    """
    for table, columns, types in _tables():
        declared = ",".join(
            f"{name} {types.get(name, 'TEXT')}" for name in columns
        )
        connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({declared})")
    for table, columns, types in _tables():
        _reconcile(connection, table, columns, types)
    for superseded in _SUPERSEDED_INDEXES:
        connection.execute(f"DROP INDEX IF EXISTS {superseded}")
    for name, table, keys in _INDEXES:
        connection.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({keys})")


class SqliteRunSink:
    """The default sink: a table on the machine that ran the workflow.

    **Columns, not one blob per run.** A store whose rows are opaque JSON makes
    *what has this workflow spent* a program instead of a query, and the point
    of this file is that a developer or a QA engineer opens it with `sqlite3`
    and writes SQL. `total_tokens` is stored rather than derived for the same
    reason — summing a JSON column in SQL is possible and is not something
    anyone should have to work out at a terminal — while `usage` keeps the
    per-model breakdown a single integer cannot express.

    **Zero configuration, on every platform.** A person runs `pip install
    openstategraph`, asks a workflow a question, and the row is on their disk —
    nothing to set, nothing to enable, no account, and it works offline. The
    path comes from `state_dir()`, which already resolves this correctly on all
    three platforms and records its citations: `$XDG_STATE_HOME` (default
    `~/.local/state`) on Linux, and therefore on WSL; `~/Library/Application
    Support` on macOS, which has no separate state directory; `%LOCALAPPDATA%`
    on Windows — *Local* rather than *Roaming*, because a sqlite file must not
    be synchronised between machines behind our back. **No `platformdirs`
    dependency**, then or now: the lean core is four dependencies, and this file
    lands beside `checkpoints.sqlite` in the directory that already answered
    this question.

    **Nothing here sweeps, and that is a decision rather than an omission.**
    `96` is the cautionary case — drafts and snapshots that never shrank — and
    it was settled with a rule worth repeating here: *nothing is dropped for
    being old alone; age is only ever the second condition.* There is no second
    condition for a run. A conversation is the raw material for replay and for
    `99`'s verified patterns, so its value does not decay with age; a store that
    quietly dropped last month's runs would be a store whose most interesting
    rows — the ones somebody finally got round to investigating — are the ones
    most likely to be gone. `149`'s TTL is the *offload* store and a different
    thing entirely.

    So the file grows without bound, and the honest answer to "what do I do when
    it is large" is a documented one rather than a silent one: `openstategraph
    runs export --to runs.json`, then truncate or delete. Deleting is a thing an
    operator can do to a file on their own machine and cannot do to a vendor's
    servers, which is most of the argument for the default being local.

    **Failing to write a row must never fail the run.** Every path here logs
    and returns, including the first one: a read-only state directory is a
    supported install, and `state_dir` says so in its own docstring.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        #: `None` means in-memory: the default *exercised* rather than switched
        #: off, which is what a test suite and a stateless deployment both want.
        self.path = Path(path) if path is not None else None
        self._connection: sqlite3.Connection | None = None
        self._broken = False
        #: Whether a row has already been lost. The first loss and the tenth
        #: are different facts and had one voice between them.
        self._lost_a_row = False

    def record(self, record: RunRecord) -> None:
        connection = self._open()
        if connection is None:
            return
        values = [_column(record, name) for name in _COLUMNS]
        placeholders = ",".join("?" for _ in _COLUMNS)
        try:
            # **One transaction, both tables.** A run row whose bursts are
            # missing would be a run that says it streamed nothing, which is a
            # different and wrong answer rather than a smaller one; so the
            # cadence lands with its row or neither does.
            with connection:
                cursor = connection.execute(
                    f"INSERT INTO runs ({','.join(_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
                if record.bursts:
                    burst_placeholders = ",".join("?" for _ in _BURST_COLUMNS)
                    connection.executemany(
                        f"INSERT INTO run_bursts ({','.join(_BURST_COLUMNS)}) "
                        f"VALUES ({burst_placeholders})",
                        [
                            _burst_row(cursor.lastrowid, order, burst)
                            for order, burst in enumerate(record.bursts)
                        ],
                    )
        except sqlite3.Error as exc:
            self._could_not_write(exc)

    def _could_not_write(self, exc: sqlite3.Error) -> None:
        """Say a row was lost — loudly the first time, and never by raising.

        The broad catch above stays broad and stays a catch: a sink is an
        observer, and `memory-and-replay/44` was careful that a door's turn does
        not depend on one. What was wrong was the volume. *"The trace file is
        unwritable"* is a warning; *"this installation has stopped keeping run
        records"* is not, and the two went through one line, so the surface
        built to make runs visible could go blank behind a log level nobody
        reads at (`the-boundary-nobody-checked/07`).

        So the first loss is an ERROR that names the file and what to do about
        it, and every loss after it is the warning it always was — because the
        failure that produces one of these produces one per run, and a report
        repeated is a log flood, which is `_open`'s own argument for `_broken`.
        """
        if self._lost_a_row:
            logger.warning(
                "Could not write the run record to %s: %s", self.path, exc
            )
            return
        self._lost_a_row = True
        logger.error(
            "Could not write the run record to %s: %s. This run finished and its "
            "answer is unaffected, but it is not in the run store, and neither "
            "will the ones after it be while this lasts — `openstategraph runs "
            "list` will not show them. Check the file is writable and that its "
            "disk is not full; `openstategraph runs export --to runs.json` "
            "takes a copy of what it already holds before you move it aside.",
            self.path,
            exc,
        )

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:  # pragma: no cover - defensive
                pass
            self._connection = None

    def _open(self) -> sqlite3.Connection | None:
        """Connect and prepare the schema, once, on the first row actually written.

        Lazy so that merely *constructing* the default registry — which every
        process does — never touches the disk, and so a workflow that is loaded
        and never run costs nothing.

        **Two failures, two costs** (`the-cost-of-one-more/12`). They were one
        `except` and one `warning`, which is how a file that needed one
        `ALTER TABLE` came to drop every run the process recorded:

        - *This is not a database I can use* — the state directory could not be
          created, or sqlite would not open the file at all. `_broken` latches,
          because a directory that could not be created will not become
          creatable between two runs of one process, and one report is a report
          while one per run is a log flood.
        - *The schema could not be finished* — the file opened, and one
          statement bringing it up to date did not run. That is not a reason to
          refuse every write: the connection is kept and used, so the schema
          work is attempted once and never again, and a row that then names
          something the file does not hold is reported one row at a time by
          `_could_not_write`, the loud-once handler that already says what was
          lost. There is no retry loop here, deliberately: re-running `_prepare`
          on every record would make an unusable file cost a full schema pass
          per run.

        **Which of the two it is, is measured rather than guessed.** Sqlite
        opens lazily, so `connect` succeeds on a file that is not a database at
        all and the truth arrives inside `_prepare` — which would put the worst
        case in the forgiving branch. So a failed `_prepare` asks the file for
        the table it is about to write to, and a file that cannot answer that
        is the first kind after all.
        """
        if self._connection is not None or self._broken:
            return self._connection
        try:
            if self.path is None:
                connection = sqlite3.connect(":memory:", check_same_thread=False)
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, check_same_thread=False)
        except (OSError, sqlite3.Error) as exc:
            self._cannot_open_the_store(exc)
            return None
        try:
            with connection:
                _prepare(connection)
        except sqlite3.Error as exc:
            if not _holds_the_runs_table(connection):
                self._cannot_open_the_store(exc)
                try:
                    connection.close()
                except sqlite3.Error:  # pragma: no cover - defensive
                    pass
                return None
            self._could_not_finish_the_schema(exc)
        self._connection = connection
        return connection

    def _cannot_open_the_store(self, exc: OSError | sqlite3.Error) -> None:
        """Say that runs are being lost, not only that a file would not open.

        `the-boundary-nobody-checked/07` set this shape for one lost row and
        this is the loss of every row, so it cannot be a level quieter: the
        message names the file, says what will be missing, and says it will go
        on being missing. Once, because `_broken` latches.
        """
        self._broken = True
        logger.error(
            "Could not open the run store at %s: %s. No run will be recorded for "
            "the rest of this process — the answers themselves are unaffected, "
            "but `openstategraph runs list` will not show this run or any after "
            "it. Check the path is a sqlite database this user can write, on a "
            "disk that is not full.",
            self.path,
            exc,
        )

    def _could_not_finish_the_schema(self, exc: sqlite3.Error) -> None:
        """The file is a database; this build could not finish bringing it up.

        Said once — `_open` runs once per sink — and it deliberately does not
        latch: a store this build cannot fully prepare may still take most of
        what it is given, and a missing index costs speed rather than rows.
        """
        logger.error(
            "Could not bring the run store at %s up to date: %s. It is still "
            "being written to, and any run it refuses will be reported on its "
            "own; `openstategraph runs export --to runs.json` takes a copy of "
            "what it already holds before you move it aside.",
            self.path,
            exc,
        )


class JsonlRunSink:
    """One JSON line per run, appended to a path the operator named.

    **This is `loader._append_trace`, moved and not rewritten** — `--trace-file`
    behaves exactly as it did, which is the property that makes generalising the
    branch a refactor rather than a feature.

    **The answer text is deliberately not written — only its length.** A trace
    file gets committed, emailed and pasted into issues, and an answer is the
    one field in a run that reliably contains a customer's data. `decisions` and
    `attempts` are what tell you which way the graph went, which is what a wrong
    answer is diagnosed from; the answer itself you already have in front of you.

    That this sink stores *less* than the record it is handed is the point of a
    sink being a projection rather than a mirror, and it is the shape a vendor
    exporter should copy: a record carries what the local store may keep, and
    each destination decides what it is willing to carry off the machine.

    A path that cannot be written **warns and returns.** A trace is diagnostics:
    losing it must never lose the run that produced it.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def record(self, record: RunRecord) -> None:
        line = {
            "ts": record.at,
            "slug": record.workflow_slug,
            "question": record.question,
            "decisions": record.decisions,
            "attempts": record.attempts,
            "warnings": record.warnings,
            "seconds": round(record.seconds, 3),
            "answer_chars": len(record.answer),
            # Tokens, per model — the one number a support ticket about a slow
            # or expensive run always wants and never had. Safe to write where
            # the answer is not: a count carries no customer data.
            "usage": record.usage,
            # How many bursts of output the run produced — a shape, not the
            # words. The cadence table's text is the answer text by another
            # road (`memory-and-replay` 47), so it obeys `answer`'s rule here
            # exactly: a file that gets committed and emailed carries a count.
            "bursts": len(record.bursts),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line) + "\n")
        except OSError as exc:
            logger.warning("Could not write the run trace to %s: %s", self.path, exc)

    def close(self) -> None:
        """Nothing is held open — each row is appended and the handle released."""


def default_run_sink_registry(workflows_root_dir: Path | str | None = None) -> RunSinkRegistry:
    """The shipped registry: one sink, and it writes to this machine.

    **A fresh instance per call, never a module-level singleton** — the same
    property `default_search_registry` has, and for the same reason: one test's
    registration must not reach another test's run.

    Nothing here reaches a network, and no exporter that could is registered and
    disabled. See this module's docstring for why absence rather than a flag.
    """
    registry = RunSinkRegistry()
    registry.register("sqlite", SqliteRunSink(run_store_path(workflows_root_dir)))
    return registry


_process_registry: RunSinkRegistry | None = None


def run_sink_registry() -> RunSinkRegistry:
    """This process's sinks — built once, and where an adopter registers theirs.

    Memoised the way `provider_catalogue()` is, and reset the same way, because
    a sink holds a connection: rebuilding it per run would open a sqlite handle
    per run, which is the leak `CompiledWorkflow.close` exists to have fixed
    once already.
    """
    global _process_registry
    if _process_registry is None:
        _process_registry = default_run_sink_registry()
    return _process_registry


def reset_run_sink_registry() -> None:
    """Drop this process's sinks, closing them. For tests, and for a reload."""
    global _process_registry
    if _process_registry is not None:
        _process_registry.close()
    _process_registry = None


def publish(record: RunRecord, *, registry: RunSinkRegistry | None = None) -> None:
    """Hand one row to every registered sink. **Never raises.**

    The isolation is per sink and it is the whole reason this is a function
    rather than a loop at each call site: a collector being down must cost its
    own row and not the local store's, and neither must cost the run. That is
    `_append_trace`'s rule — *losing a trace must never lose the run that
    produced it* — applied now that there can be more than one trace.
    """
    for name, sink in (registry or run_sink_registry()).list():
        try:
            sink.record(record)
        except Exception as exc:
            logger.warning("Run sink %r did not accept a record: %s", name, exc)


def read_runs(
    path: Path | str | None = None,
    *,
    workflow_slug: str | None = None,
    thread_id: str | None = None,
    session_id: str | None = None,
    user_email: str | None = None,
    kind: str | None = None,
    limit: int = 100,
    with_bursts: bool = False,
    audience: str | None = None,
) -> list[RunRecord]:
    """Rows back out of the local store, newest first. The same rows, as objects.

    This is the *other* half of *"basically a query or JSON"*, and it reads the
    table `SqliteRunSink` writes rather than assembling a view of its own —
    which is what keeps one store one store. A developer with `sqlite3` and a
    model with `--json` are looking at the same bytes.

    `with_bursts` attaches each row's cadence (`memory-and-replay` 47). **Off
    by default, and that is not timidity**: a listing prints a line per run and
    a burst list is 6 to 30 objects per row, so paying for it to render a table
    would make the cheap question expensive. `runs export` asks for it, because
    an export that dropped the cadence would leave a person truncating a store
    on the strength of a file that had not carried everything.

    **And asking for it costs an `audience`** (`memory-and-replay` 71).
    `read_run_bursts` has required that keyword since
    `the-boundary-nobody-checked/02`, for a reason that is a property of the
    *table* and not of that function: `RunBurst.audience` is stored so a reader
    can refuse, and a developer run's bursts carry developer content. This
    reader reaches the same table through `_attach_bursts` and had no such
    parameter, so the two readers of one column disagreed about whether it was
    a gate — and the first HTTP door built on either would have inherited a
    refusal nothing told it about. Nothing leaked: the only caller was
    `openstategraph runs export`, an operator reading their own machine. The
    next caller was a route.

    A raise rather than a default, and the same rule spelled the only way a
    boolean flag allows: `read_run_bursts` makes the question impossible to
    skip because a keyword with no default does not compile, and here it is
    impossible to skip because asking for the cadence without it does not run.
    The listing itself needs no audience — a run's own columns are the run, and
    only the recording quotes what a stream said.

    **A store that was never written is not an error.** A fresh install has no
    runs, and *no runs* is an answer; so is a file this build cannot read, which
    warns and returns nothing rather than taking down the command that asked.
    """
    if with_bursts and audience is None:
        raise ValueError(
            "read_runs(with_bursts=True) needs an audience: a run's cadence is "
            "recorded per stream, and whose stream it was is what decides "
            "whether this reader may have it."
        )
    target = Path(path) if path is not None else run_store_path()
    if target is None or not target.exists():
        return []

    clauses, values = [], []
    for column, wanted in (
        ("workflow_slug", workflow_slug),
        ("thread_id", thread_id),
        ("session_id", session_id),
        ("user_email", user_email),
        ("kind", kind),
    ):
        if wanted:
            clauses.append(f"{column} = ?")
            values.append(wanted)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    try:
        connection = readonly_connection(target)
    except sqlite3.Error as exc:
        logger.warning("Could not open the run store at %s: %s", target, exc)
        return []
    try:
        # **The reader reconciles by asking for less, because it cannot ALTER.**
        # This connection is `mode=ro`, and `openstategraph runs list` is the
        # first thing somebody runs after an upgrade — before any run has
        # reopened the sink for writing. Naming today's columns against a file
        # one column behind is `no such column`, which cost the whole listing
        # rather than the one cell (`the-boundary-nobody-checked/07`). So: the
        # intersection, and the fields the file does not carry keep the
        # record's own defaults.
        known = tuple(
            name for name in _COLUMNS if name in _table_columns(connection, "runs")
        )
        if not known:
            return []
        rows = connection.execute(
            f"SELECT rowid,{','.join(known)} FROM runs{where} "
            f"ORDER BY {CHRONOLOGICAL} DESC, rowid DESC LIMIT ?",
            [*values, max(1, limit)],
        ).fetchall()
        records = [_record(row[1:], known) for row in rows]
        if with_bursts:
            # Keyed by `runs.rowid`, never by `thread_id`: a thread is a
            # conversation and holds many turns, so filtering by it would give
            # every turn the whole conversation's cadence.
            _attach_bursts(
                connection,
                [row[0] for row in rows],
                records,
                target,
                audience=audience or "",
            )
    except sqlite3.Error as exc:
        logger.warning("Could not read the run store at %s: %s", target, exc)
        return []
    finally:
        connection.close()
    return records


@dataclass(frozen=True)
class ModelSpend:
    """What one model has cost, over however many runs reached for it.

    Keyed by model for the reason `RunRecord.usage` already gives — *which
    model was expensive* is only answerable while they are apart — and carrying
    three figures a provider may never report at all.

    **The three details are `int | None`, and the `None` is a fact.** `0` says
    this model was called and nothing came from cache; `None` says no run for
    this model carried the key, which is what a provider that does not publish
    the detail leaves behind. Slice 2 of `stable-beta-public/03` fills the four
    counted figures and leaves all three details at `None`; slice 4 reads
    `input_token_details` / `output_token_details` and fills them. Flattening
    *not reported* into a zero is the one thing a later slice could not undo.
    """

    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_tokens: int | None
    cache_creation_tokens: int | None
    reasoning_tokens: int | None
    runs: int


@dataclass(frozen=True)
class SessionSpend:
    """One sitting, as a row in the list of them.

    `first_at` and `last_at` are the store's own spelling of the two stamps —
    local wall clock with an offset — and **not** the derived key they are
    found by. The ordering is the server's (`the-cost-of-one-more/11`); the
    text is what a person reads.
    """

    session_id: str
    first_at: str
    last_at: str
    runs: int
    total_tokens: int


@dataclass(frozen=True)
class SpendSummary:
    """Everything one status bar and one modal need, in one answer.

    Four questions rather than four calls, because the surface reading it is
    one strip: a client making four requests would draw four cells measured at
    four different instants.
    """

    grand_total: int
    cached_total: int | None
    #: All time, largest total first.
    by_model: tuple[ModelSpend, ...]
    #: The asked-about sitting. `()` until slice 3 of `stable-beta-public/03`.
    session_by_model: tuple[ModelSpend, ...]
    session_total: int
    #: Every sitting this store knows, newest `last_at` first.
    sessions: tuple[SessionSpend, ...]


#: What a store with nothing to say answers.
#:
#: A fresh install has no file, and *no runs* is an answer rather than an
#: error — the same judgement `read_runs` makes one function up, for the same
#: reason: the first caller of this is a status bar that paints on every load,
#: and a raise here would put an error on the screen of every machine that has
#: not run anything yet. `grand_total` is `0` because a store with no runs
#: really has spent nothing; `cached_total` is `None` because nobody has said
#: anything about caching either way.
_SPENT_NOTHING = SpendSummary(
    grand_total=0,
    cached_total=None,
    by_model=(),
    session_by_model=(),
    session_total=0,
    sessions=(),
)

#: Every sitting, with its span, its count and its total — one statement.
#:
#: **The two stamps are found by the derived key and returned as stored.**
#: `min(at)` and `max(at)` would be a text comparison over a column that
#: carries an offset, which is not a comparison of instants
#: (`the-cost-of-one-more/11`) — so the span is read by a correlated seek
#: ordered on `CHRONOLOGICAL`, which is exactly the expression
#: `runs_session_utc` is built on. Sqlite's bare-column rule would have given
#: the same thing for free with one aggregate; a span needs two, so it does
#: not apply.
_SESSION_SPEND = f"""
SELECT r.session_id,
       (SELECT s.at FROM runs AS s
         WHERE s.session_id = r.session_id AND s.kind = 'run'
         ORDER BY {CHRONOLOGICAL} ASC, s.rowid ASC LIMIT 1),
       (SELECT s.at FROM runs AS s
         WHERE s.session_id = r.session_id AND s.kind = 'run'
         ORDER BY {CHRONOLOGICAL} DESC, s.rowid DESC LIMIT 1),
       count(*),
       COALESCE(sum(r.total_tokens), 0)
  FROM runs AS r
 WHERE r.kind = 'run'
 GROUP BY r.session_id
 ORDER BY max({CHRONOLOGICAL}) DESC, max(r.rowid) DESC
"""


def spend_summary(
    path: Path | str | None = None, *, session_id: str | None = None
) -> SpendSummary:
    """What the runs this store kept have cost, in tokens.

    `stable-beta-public/03`. The third reader of the same table, beside
    `read_runs` and `read_run_bursts`, and a query over it rather than a view
    of its own — which is what keeps one store one store.

    Two passes, because the store keeps the answer in two shapes and neither
    is wrong. The grand total and the sittings are `sum` and `GROUP BY` over
    the `total_tokens` column, which the sink derives on write; the by-model
    table is a walk over every row's `usage` JSON, because sqlite cannot group
    by a key inside a document. That walk is O(runs) and deliberately so: the
    alternative is a second table of per-model rows, which is a schema for a
    figure a status bar reads once a minute.

    **A run that reported nothing is a run.** `usage == {}` is *nobody said*,
    not *nothing was spent*, so it is counted in its sitting and adds no model
    row — a nameless row in a by-model table would be inventing a model.

    `session_id` is accepted and not yet used: slice 3 of the plan fills
    `session_by_model` and `session_total`. It is on the signature from here
    because the route and the client already pass it.

    **A store that cannot be read is not an error either**, for the reason
    `read_runs` gives: this answer decorates a screen, and a file one build
    cannot open must not take the screen down with it.
    """
    target = Path(path) if path is not None else run_store_path()
    if target is None or not target.exists():
        return _SPENT_NOTHING
    try:
        connection = readonly_connection(target)
    except sqlite3.Error as exc:
        logger.warning("Could not open the run store at %s: %s", target, exc)
        return _SPENT_NOTHING
    try:
        # The same reconciliation `read_runs` makes and for the same reason:
        # this connection is `mode=ro` and cannot ALTER, so a file one column
        # behind must answer what it can rather than raise `no such column`.
        held = _table_columns(connection, "runs")
        if not {"kind", "at", "session_id", "total_tokens", "usage"} <= set(held):
            return _SPENT_NOTHING
        grand_total = int(
            connection.execute(
                "SELECT COALESCE(sum(total_tokens), 0) FROM runs WHERE kind = 'run'"
            ).fetchone()[0]
            or 0
        )
        sessions = tuple(
            SessionSpend(
                session_id=str(row[0] or ""),
                first_at=str(row[1] or ""),
                last_at=str(row[2] or ""),
                runs=int(row[3] or 0),
                total_tokens=int(row[4] or 0),
            )
            for row in connection.execute(_SESSION_SPEND)
        )
        by_model = _by_model(
            connection.execute("SELECT usage FROM runs WHERE kind = 'run'")
        )
    except sqlite3.Error as exc:
        logger.warning("Could not read the run store at %s: %s", target, exc)
        return _SPENT_NOTHING
    finally:
        connection.close()
    return SpendSummary(
        grand_total=grand_total,
        cached_total=None,
        by_model=by_model,
        session_by_model=(),
        session_total=0,
        sessions=sessions,
    )


def _by_model(rows: Any) -> tuple[ModelSpend, ...]:
    """One pass over the `usage` documents, added up per model, dearest first.

    Read tolerantly and trusted strictly, the way this codebase reads anything
    a model wrote: a row whose `usage` is not a JSON object, or whose value for
    a model is not a mapping, is skipped rather than raised on — the column
    holds whatever the build that wrote it put there, and one unreadable row
    may not cost the other twenty-four.
    """
    totals: dict[str, list[int]] = {}
    for row in rows:
        try:
            usage = json.loads(row[0]) if row[0] else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(usage, dict):
            continue
        for model, spent in usage.items():
            if not isinstance(spent, dict):
                continue
            entry = totals.setdefault(str(model), [0, 0, 0, 0])
            entry[0] += int(spent.get("input_tokens") or 0)
            entry[1] += int(spent.get("output_tokens") or 0)
            entry[2] += int(spent.get("total_tokens") or 0)
            entry[3] += 1
    return tuple(
        sorted(
            (
                ModelSpend(
                    model=model,
                    input_tokens=counted[0],
                    output_tokens=counted[1],
                    total_tokens=counted[2],
                    cached_tokens=None,
                    cache_creation_tokens=None,
                    reasoning_tokens=None,
                    runs=counted[3],
                )
                for model, counted in totals.items()
            ),
            # Dearest first, and by name where two cost the same — an order a
            # test can assert without depending on dictionary insertion.
            key=lambda row: (-row.total_tokens, row.model),
        )
    )


def _attach_bursts(
    connection: sqlite3.Connection,
    rowids: list[Any],
    records: list[RunRecord],
    target: Path,
    *,
    audience: str,
) -> None:
    """Each row's cadence onto the record that produced it, a batch at a time.

    A store written before `memory-and-replay` 47 has no `run_bursts` table,
    and every row in every store has runs that predate capture. Both are *no
    cadence*, which is an answer — so this leaves the records alone rather than
    failing the listing that asked.

    **`CADENCE_BATCH` ids per statement, rather than all of them.** One
    variable per row id met sqlite's own ceiling at 32,766 runs and the whole
    listing's cadence was lost in a `logger.debug`. Batching was chosen over
    driving the burst read off the run read's own `WHERE`, because the reason
    written at the call site — keyed on `runs.rowid`, never on `thread_id`,
    since a thread holds many turns and would give each of them the whole
    conversation's cadence — is a property of the id list, and a second query
    shape would have had to re-derive it from filters that do not carry it.
    Batching keeps the key and removes only the ceiling.

    **A refused read raises.** It is not *no cadence*; it is cadence this read
    did not get, and the caller that asked for it is the export somebody runs
    before truncating.

    `audience` is read exactly as `read_run_bursts` reads it and the clause is
    the same one: `"developer"` takes everything, anything else takes only what
    a **customer's own stream** produced — never a developer run's, and never a
    row whose provenance was not recorded, because unknown is not a customer's.
    A run whose recording is refused keeps its row and loses its cadence, which
    is the absence an old store already answers with.
    """
    if not rowids:
        return
    try:
        known = _known_burst_columns(connection)
        if not known:
            return
        refusal = "" if audience == "developer" else " AND audience = ?"
        refused: list[Any] = [] if audience == "developer" else ["customer"]
        rows: list[Any] = []
        for start in range(0, len(rowids), CADENCE_BATCH):
            batch = rowids[start : start + CADENCE_BATCH]
            placeholders = ",".join("?" for _ in batch)
            rows.extend(
                connection.execute(
                    f"SELECT run_rowid,{','.join(known)} FROM run_bursts "
                    f"WHERE run_rowid IN ({placeholders}){refusal} "
                    "ORDER BY run_rowid, ord",
                    [*batch, *refused],
                ).fetchall()
            )
    except sqlite3.Error as exc:
        logger.error(
            "Could not read the run cadence out of %s: %s. The %d run(s) this "
            "read returned will carry no cadence — the answers are there and "
            "how they arrived is not — so a file written from them is not a "
            "complete copy of the store and must not be truncated against. "
            "Check the file with `sqlite3 \"$(openstategraph runs path)\" "
            "\"PRAGMA integrity_check\"`.",
            target,
            exc,
            len(records),
        )
        raise RunCadenceUnavailable(str(exc)) from exc
    by_run: dict[Any, list[RunBurst]] = {}
    for row in rows:
        by_run.setdefault(row[0], []).append(_burst(row[1:], known))
    for rowid, record in zip(rowids, records):
        record.bursts = by_run.get(rowid, [])


def _column(record: RunRecord, name: str) -> Any:
    """One field, as the table stores it."""
    if name == "total_tokens":
        return record.total_tokens()
    value = getattr(record, name)
    if name in _JSON_COLUMNS:
        return json.dumps(value)
    if name == "failed":
        return int(value)
    return value


def _burst_row(run_rowid: int | None, order: int, burst: RunBurst) -> tuple[Any, ...]:
    """One burst, as the table stores it. `_column`'s counterpart, and kept
    beside it for the same reason the two column lists are kept beside each
    other."""
    return (
        run_rowid,
        order,
        burst.node,
        burst.active_node,
        json.dumps(burst.namespace),
        burst.block,
        burst.kind,
        int(burst.withheld),
        burst.audience,
        burst.first_seq,
        burst.last_seq,
        burst.first_ms,
        burst.last_ms,
        burst.chunks,
        burst.chars,
        burst.text,
        burst.cadence,
        int(burst.capped),
    )


def _known_burst_columns(connection: sqlite3.Connection) -> tuple[str, ...]:
    """The burst columns this build wants that this file actually has.

    `_BURST_COLUMNS[2:]` because the key and the ordinal are the join, not the
    burst. Empty means no `run_bursts` table at all, which is every store
    written before `memory-and-replay/47` and is an answer rather than a fault.
    """
    present = set(_table_columns(connection, "run_bursts"))
    return tuple(name for name in _BURST_COLUMNS[2:] if name in present)


def _burst(row: tuple[Any, ...], names: tuple[str, ...] = _BURST_COLUMNS[2:]) -> RunBurst:
    """One stored row, back as the object that wrote it. Tolerant in exactly
    the way `_record` is: a namespace that will not parse costs the namespace,
    never the burst — and a column the file predates costs that field and not
    the burst either, which is `names` rather than `_BURST_COLUMNS[2:]`."""
    fields: dict[str, Any] = {}
    for name, value in zip(names, row):
        if name == "namespace":
            try:
                fields[name] = json.loads(value) if value else []
            except (TypeError, ValueError):
                fields[name] = []
            continue
        if name in ("withheld", "capped"):
            fields[name] = bool(value)
            continue
        if name == "cadence":
            fields[name] = bytes(value) if value else b""
            continue
        if value is not None:
            fields[name] = value
    return RunBurst(**fields)


def read_run_bursts(
    path: Path | str | None = None,
    *,
    audience: str,
    thread_id: str | None = None,
    workflow_slug: str | None = None,
    session_id: str | None = None,
    limit: int = 200,
) -> list[RunBurst]:
    """How a stored run's output arrived, oldest first — `read_runs`' other half.

    Joined back through `runs.rowid`, so the filters are the ones a caller
    already knows: a thread, a workflow, a session. Ordered by the run row and
    then by position within it, which is the order the chunks were produced in.

    **`audience` is required, and it is the refusal `RunBurst.audience` was
    stored for** (`the-boundary-nobody-checked/02`). That column says *"a
    developer run's bursts carry developer content"* and this reader had no
    parameter to act on it and no caller in `openstategraph/` to notice — so
    the first replay door built on it would have inherited a refusal nothing
    told it about. A keyword with no default is what makes that impossible:
    the question is asked at the call site or the call does not compile.

    `"developer"` reads everything, exactly as the ceiling model does
    elsewhere. Anything else is read as a customer and takes only bursts a
    **customer's own stream** produced — never a developer run's, and never a
    row whose audience was not recorded at all, because an unknown provenance
    is not a customer's. That last clause costs a customer the cadence of runs
    stored before the column existed, which is the direction a boundary has to
    fail in.

    **A store with no cadence is not an error and not a zero.** A fresh
    install, a workflow with no model in it, and every run recorded before this
    ticket all return `[]` — an absence a caller must render as *unknown*
    rather than as an instant run. So must a file this build cannot read, which
    warns and returns nothing rather than taking down the panel that asked.
    """
    target = Path(path) if path is not None else run_store_path()
    if target is None or not target.exists():
        return []

    clauses, values = [], []
    for column, wanted in (
        ("thread_id", thread_id),
        ("workflow_slug", workflow_slug),
        ("session_id", session_id),
    ):
        if wanted:
            clauses.append(f"runs.{column} = ?")
            values.append(wanted)
    if audience != "developer":
        clauses.append("run_bursts.audience = ?")
        values.append("customer")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    try:
        connection = readonly_connection(target)
    except sqlite3.Error as exc:
        logger.warning("Could not open the run store at %s: %s", target, exc)
        return []
    try:
        known = _known_burst_columns(connection)
        if not known:
            return []
        rows = connection.execute(
            f"SELECT {','.join('run_bursts.' + name for name in known)} "
            "FROM run_bursts JOIN runs ON runs.rowid = run_bursts.run_rowid"
            f"{where} ORDER BY run_bursts.run_rowid, run_bursts.ord LIMIT ?",
            [*values, max(1, limit)],
        ).fetchall()
    except sqlite3.Error as exc:
        # A store written before this ticket has no `run_bursts` table at all.
        # No cadence is the answer there, exactly as it is for a run that
        # streamed nothing.
        logger.debug("No run cadence available in %s: %s", target, exc)
        return []
    finally:
        connection.close()
    return [_burst(row, known) for row in rows]


def _record(row: tuple[Any, ...], names: tuple[str, ...] = _COLUMNS) -> RunRecord:
    """One stored row, back as the object that wrote it.

    Read tolerantly: a column whose JSON will not parse costs that field and not
    the row, because a history that refuses to list anything at all is worse to
    a person diagnosing a run than a history with one blank cell. `names` is the
    same rule one level up — the columns the *file* has, which on a store this
    build is newer than is fewer than `_COLUMNS`, and the difference is the
    record's own defaults rather than an empty listing.
    """
    fields: dict[str, Any] = {}
    for name, value in zip(names, row):
        if name == "total_tokens":
            continue  # derived on write; `usage` is the truth on read
        if name in _JSON_COLUMNS:
            try:
                fields[name] = json.loads(value) if value else None
            except (TypeError, ValueError):
                fields[name] = None
            if fields[name] is None:
                fields.pop(name)
            continue
        if name == "failed":
            fields[name] = bool(value)
            continue
        if value is not None:
            fields[name] = value
    return RunRecord(**fields)


def now() -> str:
    """The timestamp spelling `_append_trace` already used, kept identical.

    Kept identical **again** in `the-cost-of-one-more/11`, deliberately. Local
    wall clock with an offset does not sort as text, and the temptation was to
    re-spell it as UTC — which fixes nothing a store already holds and breaks
    the boundary it is aimed at, because the same instant in two spellings
    sorts a day apart. The ordering is derived instead (`CHRONOLOGICAL`), so
    this stays the thing a person reads in `runs list`: their own clock, and
    the offset that says which one it was.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
