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

A `RunRecord` is assembled from what the run doors already publish, and the one
field that quotes a customer's own data through a tool — `statements` — is
copied from `executed_statements.statements_executed` and from nowhere else.
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

One honest caveat, recorded because it will otherwise be rediscovered as a bug:
**nothing populates `session_id` today.** It is declared on `RunRequest`,
carried into `configurable`, persisted, and filterable — and the MCP door
hardcodes `""` while the editor never sends one. The column is therefore
usually empty, and that is a gap in the *writer*, not in this key.

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
import sqlite3
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openstategraph.run_identity import RUN_IDENTITY_KEYS

logger = logging.getLogger(__name__)

__all__ = [
    "IN_MEMORY_RUN_STORE",
    "IRunSink",
    "JsonlRunSink",
    "RUN_STORE_FILE_NAME",
    "RUN_STORE_PATH_ENV",
    "RunRecord",
    "RunSinkRegistry",
    "SqliteRunSink",
    "default_run_sink_registry",
    "now",
    "publish",
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

    def record(self, record: RunRecord) -> None:
        connection = self._open()
        if connection is None:
            return
        values = [_column(record, name) for name in _COLUMNS]
        placeholders = ",".join("?" for _ in _COLUMNS)
        try:
            with connection:
                connection.execute(
                    f"INSERT INTO runs ({','.join(_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
        except sqlite3.Error as exc:
            logger.warning("Could not write the run record to %s: %s", self.path, exc)

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:  # pragma: no cover - defensive
                pass
            self._connection = None

    def _open(self) -> sqlite3.Connection | None:
        """Connect and create the table, once, on the first row actually written.

        Lazy so that merely *constructing* the default registry — which every
        process does — never touches the disk, and so a workflow that is loaded
        and never run costs nothing. `_broken` latches, because a state
        directory that could not be created will not become creatable between
        two runs of one process, and one warning is a report while one per run
        is a log flood.
        """
        if self._connection is not None or self._broken:
            return self._connection
        try:
            if self.path is None:
                connection = sqlite3.connect(":memory:", check_same_thread=False)
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, check_same_thread=False)
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS runs ("
                    + ",".join(
                        f"{name} {_COLUMN_TYPES.get(name, 'TEXT')}" for name in _COLUMNS
                    )
                    + ")"
                )
                # The two questions this store is asked: *this conversation*,
                # and *this workflow, newest first*. Both would otherwise scan.
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS runs_thread ON runs (thread_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS runs_workflow_at ON runs (workflow_slug, at)"
                )
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Could not open the run store at %s: %s", self.path, exc)
            self._broken = True
            return None
        self._connection = connection
        return connection


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
) -> list[RunRecord]:
    """Rows back out of the local store, newest first. The same rows, as objects.

    This is the *other* half of *"basically a query or JSON"*, and it reads the
    table `SqliteRunSink` writes rather than assembling a view of its own —
    which is what keeps one store one store. A developer with `sqlite3` and a
    model with `--json` are looking at the same bytes.

    **A store that was never written is not an error.** A fresh install has no
    runs, and *no runs* is an answer; so is a file this build cannot read, which
    warns and returns nothing rather than taking down the command that asked.
    """
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
        connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        logger.warning("Could not open the run store at %s: %s", target, exc)
        return []
    try:
        rows = connection.execute(
            f"SELECT {','.join(_COLUMNS)} FROM runs{where} ORDER BY at DESC, rowid DESC LIMIT ?",
            [*values, max(1, limit)],
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Could not read the run store at %s: %s", target, exc)
        return []
    finally:
        connection.close()
    return [_record(row) for row in rows]


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


def _record(row: tuple[Any, ...]) -> RunRecord:
    """One stored row, back as the object that wrote it.

    Read tolerantly: a column whose JSON will not parse costs that field and not
    the row, because a history that refuses to list anything at all is worse to
    a person diagnosing a run than a history with one blank cell.
    """
    fields: dict[str, Any] = {}
    for name, value in zip(_COLUMNS, row):
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
    """The timestamp spelling `_append_trace` already used, kept identical."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
