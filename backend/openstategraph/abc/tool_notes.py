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
rendering.** A further kind (`one-chinook-honest/30`'s executed statement) is an
addition to the union here, not a second field on `ToolResult`.

`SourceChoice` (`launch-readiness/150`) is the third, and it is the worked
example of when a *new kind* is right rather than a wider old one. It shares
the key, the holder and the lifecycle — it is minted at the one moment the run
knows which store answered — so it belongs on this carrier. It is not a
`Substitution`, because that tuple is **one term mapping to another** and this
is **one choice among several declared alternatives**, where the alternatives
not taken are the whole payload. Bending `Substitution` around it would have
made `axis`/`canonical_value` mean something different depending on `kind`,
which is the "one envelope for unrelated concerns" failure refused two
paragraphs down.

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

#: The three ways a system of record can be settled *before* the model runs,
#: and no fourth. Every one of them is a fact somebody else stated — the user
#: named it, the catalogue declared it the default, or it was the only one
#: there was. "The model preferred it" is deliberately absent: that is the
#: state `launch-readiness/150` exists to make unrecordable.
HOW_CHOSEN: tuple[str, ...] = ("named_in_question", "declared_default", "only_source")


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


class SourceChoice(BaseModel):
    """`launch-readiness/150`: which store answered, and what else could have.

    A `Substitution` is **one term mapping to another**. This is **one choice
    among several declared alternatives**, and the alternatives are the
    payload — so it is a sibling note kind rather than a field bent onto that
    tuple. A reader told *"1664 comes from BAV"* has been given lineage; a
    reader told *"…and this warehouse also holds JODI and the plant tracker,
    which disagree"* has been given the thing they actually asked for, which
    is somewhere to go next.

    `quantity` is what the figures are, in the developer's words, because
    *"which source"* is only answerable about something: the same warehouse
    answers supply from one system of record and outages from another.

    Unlike a `Substitution`, this always renders to a reader when it exists —
    a source is never implied by the user's own words the way a canonical
    spelling can be, so there is no "nothing actually changed" case to stay
    silent about. Silence by default is preserved where it belongs instead:
    where nothing was chosen, no note is minted at all.
    """

    kind: Literal["source_choice"] = "source_choice"
    #: What the figures are — *"Russian gasoline supply"*.
    quantity: str
    #: The system of record this run used.
    chosen: str
    #: The declared systems of record it did **not** use. The payload.
    alternatives: tuple[str, ...] = ()
    #: How it was settled. Required — see the module docstring on `how_matched`.
    how_chosen: Literal["named_in_question", "declared_default", "only_source"]


class ToolFailure(BaseModel):
    """`launch-readiness/156`: a call that was refused and never ran.

    The fourth kind, and the one that arrives from the platform rather than
    from a tool author. It shares the key, the holder and the lifecycle every
    other note has — *this call*, known at the one moment it is known,
    travelling with the result — so it belongs on this carrier rather than on a
    channel of its own.

    **Why the run records this at all**, when the model is already handed the
    error as content: because the model's account of its own silence is exactly
    what may not be relied on. Live, `cpl-mcp` answered *"an authentication
    issue with the data source"* for a call the server had rejected on an
    argument name, and sent the owner to check a credential that was never
    wrong. `127` made that argument about a substitution; this is the same
    argument about a failure.

    **`looked_like_authorisation` is measured, not asserted.** Saying "this was
    not an access problem" would be a guess in the one case where it matters
    most, so the claim is read off the service's own message. Two situations
    rendering identically is this map's standing theme, and it has two
    directions.
    """

    kind: Literal["tool_failure"] = "tool_failure"
    #: Which capability was refused. Internal: `abc/narration.py`'s rule is
    #: that a tool is never named aloud, so this is for the record and for a
    #: grader, never for the sentence a reader gets.
    tool: str = ""
    #: The service's own words. Never rendered to a reader — a result payload
    #: is the richest leak surface there is (a driver message, a request id, a
    #: user's own search term), which is why `tool_findings` speaks only
    #: integers.
    detail: str = ""
    #: Whether the service said this was about credentials or access.
    looked_like_authorisation: bool = False


#: The carrier's payload. A fourth kind (`one-chinook-honest/30`'s executed
#: statement) is an addition here, never a second field on `ToolResult`.
#:
#: A plain union rather than an `Annotated[..., Field(discriminator="kind")]`
#: one. Each member's `kind` is a `Literal` with a default, which is what
#: makes the round trip unambiguous — pinned by a test rather than assumed —
#: and the explicit discriminator bought nothing except a `FieldInfo` repr
#: inside `ToolResult`'s signature, which is the line
#: `backend/tests/public_api.txt` pins across three interpreters.
ToolNote = Union[Correction, Substitution, SourceChoice, ToolFailure]


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
        elif isinstance(note, SourceChoice):
            lines.append(_source_choice_for_model(note))
        elif isinstance(note, Substitution) and note.changed_the_question():
            lines.append(
                f'Substituted: "{note.user_term}" is not a value in this data; '
                f"this result is for {note.canonical_value} on {note.axis} "
                f"({_HOW_MATCHED_FOR_MODEL[note.how_matched]})."
            )
    return "\n".join(lines)


def _source_choice_for_model(note: SourceChoice) -> str:
    """Told to the model as a constraint on the query, not as a preference.

    The step already made the choice deterministically, so what the model
    needs is the filter, not an invitation to reconsider it.
    """
    quantity = note.quantity.strip()
    subject = f"the figures for {quantity}" if quantity else "these figures"
    line = (
        f"Source settled before this call: {subject} come from {note.chosen} "
        f"({_HOW_CHOSEN_FOR_MODEL[note.how_chosen]}). Query that source and no other."
    )
    if note.alternatives:
        line += (
            " This store also holds " + _english_list(note.alternatives) + " for the same "
            "figures; do not mix them into one number."
        )
    return line


_HOW_CHOSEN_FOR_MODEL: dict[str, str] = {
    "named_in_question": "the user named it",
    "declared_default": "this store declares it the default",
    "only_source": "the only system of record declared here",
}


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
        if isinstance(note, SourceChoice):
            lines.append(_source_choice_for_reader(note))
            continue
        if isinstance(note, ToolFailure):
            lines.append(_tool_failure_for_reader(note))
            continue
        if not isinstance(note, Substitution) or not note.changed_the_question():
            continue
        lines.append(
            f'You asked for "{note.user_term}". This data holds no such value, so '
            f"the answer above is for {note.canonical_value} on {note.axis} — "
            f"{_HOW_MATCHED_FOR_READER[note.how_matched]}."
        )
    return "\n".join(_dedup(lines))


def _tool_failure_for_reader(note: ToolFailure) -> str:
    """Two sentences, and which one is said is a measurement.

    Neither names the tool, the service or the message — the reader is told
    that a request was refused, never in whose words. The clause that carries
    the whole ticket is the second half of the first sentence: it is what the
    owner needed and did not get, and it is only ever said when the service's
    own message supports it.
    """
    if note.looked_like_authorisation:
        return (
            "One request to a connected service was refused as unauthorised, so the answer "
            "above was produced without it."
        )
    return (
        "One request to a connected service was rejected before it ran, so the answer above "
        "was produced without it. The service's own message says nothing about credentials "
        "or access."
    )


def _source_choice_for_reader(note: SourceChoice) -> str:
    """The sentence `launch-readiness/150` was filed to make unforgettable.

    *"I do not understand where this number comes from."* — so it names the
    store, says how that was settled, lists what else could have answered,
    and tells the reader that asking for another is a thing they may do. The
    last clause is not decoration: without it a reader learns there was a
    choice and not that it is theirs.
    """
    quantity = note.quantity.strip()
    subject = f"The figures for {quantity}" if quantity else "These figures"
    head = f"{subject} come from {note.chosen} — {_HOW_CHOSEN_FOR_READER[note.how_chosen]}."
    if not note.alternatives:
        return head + (
            " It is the only system of record this data declares for them, so there was "
            "nothing to choose between."
        )
    return head + (
        " This data also holds " + _english_list(note.alternatives) + " for the same figures, "
        "and they can disagree. Ask for one by name and it will be re-run against that source."
    )


_HOW_CHOSEN_FOR_READER: dict[str, str] = {
    "named_in_question": "the source you named",
    "declared_default": "the source this data declares as its default",
    "only_source": "the only source this data declares",
}


def _english_list(values: tuple[str, ...] | list[str]) -> str:
    items = [v for v in values if v]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


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
    keepable = [
        note for note in notes if isinstance(note, (Substitution, SourceChoice, ToolFailure))
    ]
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
    "HOW_CHOSEN",
    "HOW_MATCHED",
    "Correction",
    "SourceChoice",
    "Substitution",
    "ToolFailure",
    "ToolNote",
    "notes_for_model",
    "notes_for_reader",
    "record_notes",
    "take_notes",
]
