"""The tollbooth's ledger: a named, retention-bounded record of what crossed.

One collaborator, no ladder. `compile/node_runtime.py`'s `_memory_segment`
plumbs state into it and state out of it; everything about *what a segment is*
is here, and it is testable with `InMemoryStore` and no graph.

## Why a collaborator and not an `I…` → `Abstract…` → `Base…` → concrete family

CLAUDE.md declares the ladder for every entity family and then says the thing
that matters here: **inheritance must earn itself.** The only axis a second
member could vary along is *where the ledger lives*, and that is already
expressed as data — a namespace tuple — rather than as behaviour. A hierarchy
whose subclasses would differ by one value is the "exists only to share two
fields" case the rule names, so this is one frozen dataclass and says so.

## Three jobs at one position

Every crossing **furnishes**, **records** and is **shown**, in that order, and
the order is load-bearing:

- **Furnish first.** What flows onward carries the entries *as they stood on
  arrival*, then the crossing's own content. Recording first would hand the
  next node its own input back inside the context block it is reading, which
  looks like a duplicate and is really a lie about when it was written.
- **Record second**, verbatim. No model is reachable from this module — see
  `TestNoModelIsReachableFromHere`, which asserts it rather than promising it —
  so the card's "zero tokens" is true by construction, not by discipline.
- **Show** is the card's job and is deliberately the smallest of the three:
  the segment name and the retention, both true before any run. A live entry
  count is not available to a card without a round trip to the server, and
  parsing one back out of the text below would hand-mirror this renderer
  across the TypeScript seam with nothing pinning the two together.

## The context block is machinery

It is a **Context** section in the prompt-composition sense — generated, not
authored — so there is no field for its heading, its numbering or its wording,
and `TestTheContextBlockIsMachinery` asserts that no field can reach it. That
is the `RouterNode` lesson applied before the bug rather than after it.

## It is not the facts namespace, and it is not episodic memory

`save_memory` writes facts to `("workflow-memory", slug)` and searches that
namespace by prefix, so a ledger of crossings rooted there would come back out
of `search_memory` as though every crossing were a fact somebody chose to
remember. Different root, therefore, and a test pins the difference.

Nor is this the episodic memory `memory.py` records as deliberately absent.
Episodic memory selects past *experiences* and replays them as few-shot
examples, which needs a trajectory selector and a relevance policy — a runtime,
and we are a compiler. A segment selects nothing and abstracts nothing: it is
the last N things that crossed one drawn position, furnished verbatim.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

#: Root of every segment namespace. Deliberately not `"workflow-memory"` —
#: see the module docstring's namespace argument.
SEGMENT_ROOT = "workflow-segments"

#: The default a placed tollbooth carries, and the answer to the interview's
#: "what is the biggest this can get?". Visible on the card rather than
#: constant here, because an unbounded ledger becomes a context-window failure
#: three months later, at which point the number nobody can see is the one
#: that needs changing.
DEFAULT_RETENTION = 20

#: The most entries one crossing will read. Only an unbounded segment can
#: reach it — a segment with a retention limit is pruned to that limit on
#: every append — and reaching it is reported rather than silently truncated.
SEGMENT_CEILING = 500

#: The fixed lead-in of the furnished block. Machinery: nothing configurable
#: reaches it.
CONTEXT_HEADING = "## Memory"

# --- The six sentences. -----------------------------------------------------
#
# Each is read by a *model*, not by a log. Two that said the same thing would
# be one failure, and `TestSixConditionsSaySixThings` fails if any two
# collapse.

#: The machinery is absent. Said in a way that cannot be mistaken for a report
#: about the workflow, because an empty context block is exactly what a model
#: would otherwise read as "nothing has ever happened here".
NO_STORE = (
    '[memory: segment "{name}" neither recalled nor appended anything — this run has no '
    "memory store, so this is a gap in the machinery and not a gap in the workflow.]"
)

#: A tollbooth with no name has no ledger. Never invents one: a default name
#: would quietly merge every unnamed segment in the document into one.
NO_NAME = (
    "[memory: this memory segment has no name, so there is no ledger for it to read or "
    "append to. Name the segment on its card.]"
)

#: The one that would otherwise be reported as success — the youtube atom's
#: lesson at a different door. It does **not** contain the word for the thing
#: it denies: a model reading "empty" inside the sentence that exists to say
#: "we do not know" is the whole failure the sentence prevents.
READ_FAILED = (
    '[memory: segment "{name}" could not be read ({error}). Treat its contents as '
    "unknown — this is not a report about what has crossed it.]"
)

#: Distinct from the read failure on purpose: the entries above are real and
#: usable, and only this crossing is missing from them.
WRITE_FAILED = (
    '[memory: segment "{name}" was read, but this crossing was not appended to it '
    "({error}).]"
)

#: A blank entry is not free. Under a retention limit it pushes a real entry
#: out, so an empty crossing is refused rather than recorded.
NOTHING_CROSSED = (
    '[memory: nothing arrived at segment "{name}", so nothing was appended and its '
    "contents are as they were.]"
)

#: Only an unbounded segment can get here. Says what was read and what to do,
#: rather than presenting a partial ledger as the whole one.
CEILING_REACHED = (
    '[memory: segment "{name}" holds at least {ceiling} entries and only {ceiling} were '
    "read. Set a retention limit on its card so the segment stays bounded.]"
)


def parse_retention(raw: object) -> int | None:
    """What the card can hold, as `int | None` — `None` meaning unbounded.

    Honesty gate 3 in its smallest form. The field is a `text` box with an
    empty-string default because `FieldValue` has no numeric "unset" and a
    slider would force a number, making *unbounded* unsayable; `Infinity` is
    not an option, since `JSON.stringify(Infinity)` is `"null"` and the value
    would not survive its own round trip.

    Everything unparseable becomes unbounded rather than zero. A ledger
    retaining zero entries is a node whose entire card is a lie, and a typo in
    a text box is not a decision to build one.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text.isdigit():
            return None
        value = int(text)
        return value if value > 0 else None
    return None


@dataclass(frozen=True)
class SegmentEntry:
    """One thing that crossed, and which tollbooth it crossed at.

    `node` is recorded because a named segment may sit at several positions —
    the interview's volunteered answer, and the thing that makes the ledger's
    identity the name rather than the node.
    """

    key: str
    text: str
    node: str


@dataclass(frozen=True)
class Crossing:
    """What one crossing produced.

    `text` is what flows onward; `entries` is what the ledger held on arrival;
    `notes` is every exception report the crossing raised, already interleaved
    into `text` and kept separately so a test can assert a healthy crossing
    raised none.
    """

    text: str
    entries: tuple[SegmentEntry, ...]
    recorded: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class MemorySegment:
    """A named ledger in one workflow's durable Store scope."""

    name: str
    retention: int | None = DEFAULT_RETENTION

    def namespace(self, slug: str) -> tuple[str, ...]:
        """Where this segment's entries live.

        The workflow slug comes from the run config rather than the
        environment (`memory.workflow_scope_slug`), so a mounted child writing
        to a segment writes to its *own* workflow's ledger — which is what
        isolation means one level down.
        """
        return (SEGMENT_ROOT, slug, self.name.strip())

    def entries(self, store: Any, slug: str) -> tuple[tuple[SegmentEntry, ...], str | None]:
        """Everything in the ledger, oldest first, plus one note or `None`.

        Order comes from the key, which is a zero-padded nanosecond timestamp,
        so it is ours rather than the backend's — `InMemoryStore` and the
        sqlite store need not agree about the order `search` returns.
        """
        try:
            items = store.search(self.namespace(slug), limit=SEGMENT_CEILING)
        except Exception as exc:
            return (), READ_FAILED.format(name=self.name.strip(), error=exc)

        found = tuple(
            SegmentEntry(
                key=str(item.key),
                text=str((item.value or {}).get("text", "")),
                node=str((item.value or {}).get("node", "")),
            )
            for item in sorted(items, key=lambda item: str(item.key))
        )
        note = (
            CEILING_REACHED.format(name=self.name.strip(), ceiling=SEGMENT_CEILING)
            if len(found) >= SEGMENT_CEILING
            else None
        )
        return found, note

    def record(self, store: Any, slug: str, *, text: str, node: str) -> str | None:
        """Append one crossing, then prune to the retention limit.

        Returns a sentence when it could not, `None` when it did. Pruning
        happens here rather than on read so that the stored ledger is the
        bounded thing: a retention limit honoured only at render time would
        leave the Store growing forever behind a card that says it does not.
        """
        namespace = self.namespace(slug)
        key = f"{_stamp()}-{uuid.uuid4().hex[:8]}"
        try:
            store.put(namespace, key, {"text": text, "node": node})
        except Exception as exc:
            return WRITE_FAILED.format(name=self.name.strip(), error=exc)

        if self.retention is None:
            return None
        existing, _ = self.entries(store, slug)
        for stale in existing[: max(0, len(existing) - self.retention)]:
            try:
                store.delete(namespace, stale.key)
            except Exception:
                # A prune that fails leaves the ledger longer than the card
                # promises, which is a smaller lie than reporting a crossing
                # that was in fact appended as having failed. The next
                # crossing tries again.
                break
        return None

    def furnish(self, entries: tuple[SegmentEntry, ...]) -> str:
        """The context block, exactly as a downstream node receives it."""
        label = self.name.strip()
        if not entries:
            return f"{CONTEXT_HEADING} · {label} — nothing has crossed yet"
        count = f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}"
        body = "\n".join(
            f"{index}. {entry.text}" for index, entry in enumerate(entries, start=1)
        )
        return f"{CONTEXT_HEADING} · {label} — {count}\n{body}"

    def cross(self, store: Any, slug: str, *, text: str, node: str) -> Crossing:
        """Furnish, then record. The whole node, minus the state plumbing."""
        label = self.name.strip()
        if not label:
            return Crossing(text=_join(NO_NAME, text), entries=(), recorded=False, notes=(NO_NAME,))
        if store is None:
            sentence = NO_STORE.format(name=label)
            return Crossing(
                text=_join(sentence, text), entries=(), recorded=False, notes=(sentence,)
            )

        entries, read_note = self.entries(store, slug)
        notes: list[str] = []
        block = self.furnish(entries) if read_note is None else ""
        if read_note is not None:
            notes.append(read_note)

        recorded = False
        if not text.strip():
            notes.append(NOTHING_CROSSED.format(name=label))
        else:
            write_note = self.record(store, slug, text=text, node=node)
            if write_note is None:
                recorded = True
            else:
                notes.append(write_note)

        return Crossing(
            text=_join(block, *notes, text),
            entries=entries,
            recorded=recorded,
            notes=tuple(notes),
        )


def _stamp() -> str:
    """A sortable, zero-padded nanosecond timestamp.

    Imported here rather than at module scope for no reason other than
    symmetry with the rest of this module's lazy edges; the padding is the
    point, because keys sort as strings.
    """
    import time

    return f"{time.time_ns():020d}"


def _join(*parts: str) -> str:
    """Blocks separated by a blank line, empties dropped."""
    return "\n\n".join(part for part in parts if part and part.strip())
