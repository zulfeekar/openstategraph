"""What a tool says about the call it just made — as fact, not as prose.

`launch-readiness/117` (a corrective `next_step` on a tool result) and
`launch-readiness/127` (an answer must say what it substituted for your word,
and how it knew) were handed over together with one instruction: **check
whether a single mechanism serves both before building two.** It does, and the
argument is worth writing down because a fifth ticket of this shape is coming.

## Why one carrier

Four tickets look like "per-tool text" and only three of them are the same
knowledge:

| Ticket | Keyed on | Held by | Authored |
| --- | --- | --- | --- |
| `launch-readiness/117` — a corrective | **this call's result** | the tool | at call time |
| `launch-readiness/127` — a substitution | **this call's result** | the resolver | at call time |
| `one-chinook-honest/30` — the executed statement | **this call's result** | the tool | at call time |
| `launch-readiness/112` — a narration line | the tool **name** | the platform | in advance |

The first three share a key (*this call*), a holder (*the tool, at the one
moment it knows*), a lifecycle (*constructed with the result, travels with
it*) and a reason to change (*what a tool is able to say about itself*). Three
independent side-channels hung on `ToolResult` and keyed on the same call is
duplication of **knowledge**, which is the kind DRY actually forbids — and the
third one would have been built by somebody who never read the first two.

`112` is deliberately **not** here, and refusing it is half the decision. It is
keyed on the tool's *name*, has no result in hand, is authored in advance by
the platform rather than at call time by the tool, and is consumed by a live
progress panel rather than by the run's record. Folding it in would force a
static table into a per-call envelope and make every note carry a tool identity
it does not need — the "one envelope for four unrelated concerns" failure the
tickets warn about as loudly as they warn about duplication. `112` shares
nothing with these but the word "per-tool".

So: **one carrier (`ToolResult.notes`), several note kinds, and a per-kind
rendering.** A fourth kind (`one-chinook-honest/30`'s executed statement) is an
addition to the union here, not a second field on `ToolResult`.

## Two rails, and why the reader's is not the model's

A note is addressed to somebody, and the two audiences want opposite things.

- **The model rail** — `notes_for_model`, appended to the string the
  `ToolMessage` carries. This is the whole of `117`: a corrective riding on
  the result *arrives with the data*, in the same message, unavoidably. It is
  not a rule issued earlier and hoped for, which is the shape this map has
  declined six times. A subagent's result comes back as a `ToolMessage` too,
  and nothing here implies a subagent sees parent state: a note travels
  **outward with a result**, never inward.
- **The reader rail** — `notes_for_reader`, rendered by the output node off
  what the *run recorded*. This is the whole of `127`. A model told about a
  substitution will disclose it most of the time, and "most of the time" is
  the failure mode the ticket exists to close. So the disclosure is not the
  model's to forget: `BaseTool.run`/`arun` record every note against the run,
  and `compile/node_runtime._output` renders them whether the model mentioned
  the substitution or not.

## Silence by default

Both tickets name the same failure: a field that fires on every call becomes
noise a model learns to skip, and a disclosure on every answer trains a reader
to skip disclosures. So:

- a tool that attaches nothing renders nothing, on either rail;
- a `Substitution` renders to a reader **only** where the user's word and the
  canonical value actually differ (case- and space-insensitively — a spelling
  difference is not a substitution);
- a `Correction` never renders to a reader at all. It is addressed to the
  model, and putting a tool's instruction to itself in front of a person is
  the scratchpad leak `abc/narration.py` closed.

## `how_matched` is the honest field, and it has no default

`exact`, `declared_synonym` and `model_inference` are three different
epistemic states, and the third is the one `127` was filed about: the Persian
Gulf run that returned 67 of 68 correct ports and the run that invented an
81-country set were, for all a reader could tell, the same kind of answer.
The field is required — a substitution that cannot say how it knew is exactly
the record this must be unable to make — and `model_inference` is labelled in
the rendered sentence rather than merely stored.
"""

from __future__ import annotations

import logging
import threading
from typing import Literal, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: The three epistemic states a resolution can be in, and no fourth.
#:
#: Named here as well as in the annotation so a tool author, a test and a
#: document can enumerate them without re-deriving the `Literal`.
HOW_MATCHED: tuple[str, ...] = ("exact", "declared_synonym", "model_inference")


class Correction(BaseModel):
    """`launch-readiness/117`: what to do given this result, said by the tool.

    Free text and not a structured vocabulary, deliberately. The open question
    the ticket set was *"structured is enforceable but invents a vocabulary the
    model must be taught"* — and the vocabulary would have to cover "your join
    could not have matched", "this page is a sample", "that statement was
    rejected because the column is versioned" and everything nobody has met
    yet. A closed set that cannot say the true thing gets used to say the
    nearest wrong one. What is enforced here is *when* a corrective appears,
    not what it may say: nothing is emitted unless a tool builds one.

    Addressed to the model. It never reaches a reader.
    """

    kind: Literal["next_step"] = "next_step"
    #: The sentence, in the tool author's own words.
    text: str


class Substitution(BaseModel):
    """`launch-readiness/127`: a user's word, resolved to a value that exists.

    The five fields the ticket named, and no sixth. `axis` is the one that
    stops this being a synonym list: *"Persian Gulf"* is genuinely live on two
    axes in the same warehouse — `shipping_region_v2` answers *located in* and
    a chokepoint token answers *transited through* — and a record that named
    the value without the axis would hide the choice that produced a 9×
    overcount (`launch-readiness/125`).
    """

    kind: Literal["substitution"] = "substitution"
    #: What the user actually typed.
    user_term: str
    #: The column, dimension or field the canonical value lives on.
    axis: str
    #: What the run used instead.
    canonical_value: str
    #: How the bridge was made. Required — see the module docstring.
    how_matched: Literal["exact", "declared_synonym", "model_inference"]
    #: `None` means "no claim", never `-1` and never a non-finite float: a
    #: value that cannot survive its own JSON round trip is refused where it
    #: is written rather than lost later.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    def changed_the_question(self) -> bool:
        """Whether this actually put a different word in the user's mouth.

        Case and surrounding space do not count. A user who typed
        `middle east gulf (meg)` and got `Middle East Gulf (MEG)` was not
        substituted for; telling them so would be the noise both tickets
        warn against.
        """
        return _normalise(self.user_term) != _normalise(self.canonical_value)


#: The carrier's payload. A fourth kind (`one-chinook-honest/30`'s executed
#: statement) is an addition here, never a second field on `ToolResult`.
#:
#: A plain union rather than an `Annotated[..., Field(discriminator="kind")]`
#: one. Each member's `kind` is a `Literal` with a default, which is what
#: makes the round trip unambiguous — pinned by a test rather than assumed —
#: and the explicit discriminator bought nothing except a `FieldInfo` repr
#: inside `ToolResult`'s signature, which is the line
#: `backend/tests/public_api.txt` pins across three interpreters.
ToolNote = Union[Correction, Substitution]


def _normalise(value: str) -> str:
    return " ".join(value.split()).casefold()


def notes_for_model(notes: tuple[ToolNote, ...] | list[ToolNote]) -> str:
    """The model rail: what to append to the `ToolMessage`, or `""`.

    Empty for an empty sequence — a tool that says nothing must behave exactly
    as it did before this field existed, all the way down to the bytes the
    model receives.
    """
    lines: list[str] = []
    for note in notes:
        if isinstance(note, Correction):
            text = note.text.strip()
            if text:
                lines.append(f"Next step: {text}")
        elif isinstance(note, Substitution) and note.changed_the_question():
            lines.append(
                f'Substituted: "{note.user_term}" is not a value in this data; '
                f"this result is for {note.canonical_value} on {note.axis} "
                f"({_HOW_MATCHED_FOR_MODEL[note.how_matched]})."
            )
    return "\n".join(lines)


_HOW_MATCHED_FOR_MODEL: dict[str, str] = {
    "exact": "exact match",
    "declared_synonym": "a synonym declared in this data",
    "model_inference": "inferred, not declared anywhere",
}


def notes_for_reader(notes: tuple[ToolNote, ...] | list[ToolNote]) -> str:
    """The reader rail: the disclosure paragraph, or `""`.

    Only substitutions, only where the word actually changed, and always
    carrying `how_matched` in words — the property `127`'s "done when" turns
    on. A `Correction` is silently skipped rather than reworded: it is the
    tool talking to the model.
    """
    lines: list[str] = []
    for note in notes:
        if not isinstance(note, Substitution) or not note.changed_the_question():
            continue
        lines.append(
            f'You asked for "{note.user_term}". This data holds no such value, so '
            f"the answer above is for {note.canonical_value} on {note.axis} — "
            f"{_HOW_MATCHED_FOR_READER[note.how_matched]}."
        )
    return "\n".join(_dedup(lines))


_HOW_MATCHED_FOR_READER: dict[str, str] = {
    "exact": "the same value under another spelling",
    "declared_synonym": "a synonym this data declares for it",
    # The sentence `127` exists to make impossible to omit.
    "model_inference": (
        "a mapping the model worked out for itself, which nothing in this data "
        "states. Check it before relying on the answer"
    ),
}


def _dedup(lines: list[str]) -> list[str]:
    """One sentence per distinct substitution.

    A resolver called twice for one word — a retry, a fan-out, a mount — is
    the ordinary case, and a reader who is told the same thing three times
    learns to stop reading disclosures.
    """
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


# --------------------------------------------------------------------------
# The run rail's store.
#
# A tool runs inside the agent's own compiled graph and cannot write the
# parent's state; the output node reads state and cannot see a `ToolResult`.
# The one thing both can name is the run, through
# `openstategraph.run_identity` — the single accessor for `thread_id` this
# codebase already insists on. So notes are recorded against the thread and
# taken by the node that renders them.
#
# Bounded and taken-once on purpose. `take_notes` empties the bucket, so the
# window in which anything is held is one node's worth of a live run; the caps
# below stop a run with no output node (a mount used as a library, an
# interrupted stream) from growing the store without limit. Dropping the
# *oldest* note rather than refusing the newest keeps the most recent
# resolution — the one an answer was most likely built on.
#
# `NarrationMiddleware` holds a thread-keyed store for the same reason one
# layer up. The difference is that its writer and reader are the same object,
# and here they are two graph nodes, so the store cannot be instance state.
# --------------------------------------------------------------------------

_MAX_THREADS = 64
_MAX_NOTES_PER_THREAD = 64

_lock = threading.Lock()
_recorded: dict[str, list[ToolNote]] = {}


def _current_thread() -> str:
    """This run's thread id, or `""` when there is no run.

    Read through `run_identity` rather than a second `configurable.get(...)`
    — a second reading of one identity is exactly the drift that accessor
    exists to make impossible.
    """
    from openstategraph.run_identity import run_identity

    return run_identity().get("thread_id", "")


def record_notes(
    notes: tuple[ToolNote, ...] | list[ToolNote], *, thread_id: str | None = None
) -> bool:
    """Put this call's notes on the run. Returns whether they landed.

    `False` outside a run, and that is not an error: a package's `tools/` and
    `tests/` are real code called from scripts, and a note that detonated a
    unit test would make that claim false. Same contract, and same reason, as
    `report_progress`.
    """
    keepable = [note for note in notes if isinstance(note, Substitution)]
    if not keepable:
        return False
    thread = thread_id if thread_id is not None else _current_thread()
    if not thread:
        return False
    with _lock:
        if thread not in _recorded and len(_recorded) >= _MAX_THREADS:
            _recorded.pop(next(iter(_recorded)))
        bucket = _recorded.setdefault(thread, [])
        bucket.extend(keepable)
        if len(bucket) > _MAX_NOTES_PER_THREAD:
            del bucket[: len(bucket) - _MAX_NOTES_PER_THREAD]
    return True


def take_notes(thread_id: str | None = None) -> tuple[ToolNote, ...]:
    """Everything this run recorded, and empty the bucket.

    Taken rather than read so that a second output node — a mount's, a second
    turn on one thread — cannot repeat a disclosure the reader has already
    been given.
    """
    thread = thread_id if thread_id is not None else _current_thread()
    if not thread:
        return ()
    with _lock:
        return tuple(_recorded.pop(thread, ()))


__all__ = [
    "HOW_MATCHED",
    "Correction",
    "Substitution",
    "ToolNote",
    "notes_for_model",
    "notes_for_reader",
    "record_notes",
    "take_notes",
]
