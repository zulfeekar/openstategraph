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
import re
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


class DeclaredUnit(BaseModel):
    """`osg-agent-experience/75`: what a column's numbers are measured in.

    The third instance of the shape `Substitution` and `SourceChoice` already
    carry — *the honest state and the wrong state render identically* — and a
    sibling kind rather than a field bent onto either. A `Substitution` maps a
    word to a value; a `SourceChoice` picks one store among several; this is a
    property of a **column**, true of every number read from it and of no
    particular question.

    It is minted only where a vocabulary row says so. A row that declares
    nothing mints nothing, because silence by default is this module's rule and
    a unit nobody wrote down is not one this run may assert.

    `unit` empty means **declared unknown**, which is a different sentence from
    a missing note and not a missing value: somebody was asked and said they do
    not know. That is what makes a unit the model supplied refusable
    (`openstategraph.units.unit_discipline`) rather than merely unverified.
    """

    kind: Literal["declared_unit"] = "declared_unit"
    #: The column, dimension or field the figures live on — the same `axis`
    #: `Substitution` names, and for the same reason: a unit with no column is
    #: a claim about a table rather than about a number.
    axis: str
    #: What its numbers are measured in, in the declaring row's own words.
    #: Empty means *declared unknown*; see the class docstring.
    unit: str = ""
    #: Units this row declares a conversion to. Empty is the ordinary case —
    #: barrels to tonnes needs a density, which is a property of the cargo and
    #: not of the row, so a table that carries one has to say so.
    convertible_to: tuple[str, ...] = ()


class ToolFailure(BaseModel):
    """`launch-readiness/156`: a call that was refused and never ran.

    The fourth kind, and the one that arrives from the platform rather than
    from a tool author. It shares the key, the holder and the lifecycle every
    other note has — *this call*, known at the one moment it is known,
    travelling with the result — so it belongs on this carrier rather than on a
    channel of its own.

    **Why the run records this at all**, when the model is already handed the
    error as content: because the model's account of its own silence is exactly
    what may not be relied on. Live, an MCP-backed agent answered *"an authentication
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


class UncoveredWindow(BaseModel):
    """`launch-readiness/166`: a zero the data could not have contradicted.

    The fifth kind, and the second that arrives from the platform rather than
    from a tool author. It shares the key, the holder and the lifecycle every
    other note has — *this run's statements*, known at the one moment a check
    holds both the window asked about and what the table says it covers — so it
    belongs on this carrier rather than on a channel of its own.

    **Why a reader is told this and a model is not asked to fix it.** Where the
    window lies entirely outside a *declared* coverage, the answer is repairable
    in one lap and `table_coverage.check_zero_outside_coverage` sends it back.
    These two states are not repairable by anybody: no revision makes a table
    declare a window it has never declared, and none moves the last date it
    holds. A guard that objected forever and then published anyway is
    `launch-readiness/167` in person, so this travels the rail that renders
    whether or not the model mentions it.

    Measured, never asserted — the same property `ToolFailure` carries.
    `declared_max` is a date somebody wrote down; empty means nobody did, and
    the two render as different sentences with no toggle between them.
    """

    kind: Literal["uncovered_window"] = "uncovered_window"
    #: What the answer reported none of, in the answer's own word — *"vessels"*.
    subject: str = ""
    #: Which table. Internal, for the record and for a grader: `abc/narration.py`'s
    #: rule is that the machinery is never named aloud.
    table: str = ""
    #: The last date the table **declares** it holds, ISO. Empty when the table
    #: declares nothing, which is a different sentence and not a missing value.
    declared_max: str = ""


class UnverifiedAnswer(BaseModel):
    """`launch-readiness/167`: the run published what its own check refused.

    A guard has two ceilings and both are right — `maxAttempts` and the step
    budget floor, either of which forces `pass` so a cycle can always end. When
    the ceiling arrives while an objection is still standing, the candidate is
    published **with the check's own rejection of it sitting in the run's state,
    unread**. Measured live on 2026-08-28: lap 2's guard said *"the answer
    reports 1,454,449 vessels…"* and the output node published *"…there are
    1,454,449 dark vessels."*

    **The pass is correct and is not changed here.** `_grader`'s own argument
    holds: a loop that cannot finish is worse than a mediocre answer, and
    refusing to publish turns a ceiling into a dead run, which is what
    `Grader.normalise` warns against. Only the silence is the defect.

    **The guard's `reason` is never rendered.** It is developer-facing text
    written for a model to act on — it names tables, statements and column
    expressions — and `launch-readiness/143`'s sentence-shape rule binds
    anything reaching a customer. What a reader gets is the one fact the
    machinery can state about itself honestly: this answer did not clear the
    workflow's own check on it. Which check, and what it said, is
    `verdicts[node]` on the developer channel, where it already was.
    """

    kind: Literal["unverified_answer"] = "unverified_answer"
    #: The check that was still objecting. Internal — never rendered, for the
    #: same reason `ToolFailure.tool` is not.
    check: str = ""
    #: Whether the ceiling reached was the workflow's step budget rather than
    #: this node's own attempts cap. Two ceilings, and a reader's next move
    #: differs — the same split `forced` and `budget_stops` already make on the
    #: developer channel.
    starved: bool = False


#: The carrier's payload. A fourth kind (`one-chinook-honest/30`'s executed
#: statement) is an addition here, never a second field on `ToolResult`.
#:
#: A plain union rather than an `Annotated[..., Field(discriminator="kind")]`
#: one. Each member's `kind` is a `Literal` with a default, which is what
#: makes the round trip unambiguous — pinned by a test rather than assumed —
#: and the explicit discriminator bought nothing except a `FieldInfo` repr
#: inside `ToolResult`'s signature, which is the line
#: `backend/tests/public_api.txt` pins across three interpreters.
ToolNote = Union[
    Correction,
    Substitution,
    SourceChoice,
    DeclaredUnit,
    ToolFailure,
    UncoveredWindow,
    UnverifiedAnswer,
]


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
        elif isinstance(note, DeclaredUnit):
            lines.append(_declared_unit_for_model(note))
        elif isinstance(note, Substitution) and note.changed_the_question():
            lines.append(
                f'Substituted: "{note.user_term}" is not a value in this data; '
                f"this result is for {note.canonical_value} on {note.axis} "
                f"({_HOW_MATCHED_FOR_MODEL[note.how_matched]})."
            )
    return "\n".join(lines)


def _declared_unit_for_model(note: DeclaredUnit) -> str:
    """Told to the model as a constraint on the answer, not as a preference.

    Including the density sentence verbatim, which is deliberate: the parser
    that reads a decline reads this exact phrase, so the prompt teaches the
    format the parser can read rather than the other way round — `CLAUDE.md`'s
    third defect of that shape.
    """
    axis = note.axis or "these figures"
    if not note.unit:
        return (
            f"No unit is declared for {axis}. Do not name a unit for those figures; "
            "say that this data declares none."
        )
    line = (
        f"Unit declared before this call: {axis} is measured in {note.unit}. "
        f"Report the figures in {note.unit} and name it."
    )
    if note.convertible_to:
        return line + " This data declares a conversion to " + _english_list(
            note.convertible_to
        ) + "."
    return line + (
        " Do not convert to another unit: converting needs a density this table "
        "does not carry."
    )


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


def notes_for_reader(
    notes: tuple[ToolNote, ...] | list[ToolNote],
    *,
    unsent_values: frozenset[str] | set[str] | None = None,
) -> str:
    """The reader rail: the disclosure paragraph, or `""`.

    Only substitutions, only where the word actually changed, and always
    carrying `how_matched` in words — the property `127`'s "done when" turns
    on. A `Correction` is silently skipped rather than reworded: it is the
    tool talking to the model.

    **`unsent_values` is `launch-readiness/155`**, and it is a fact about the
    run rather than about the note. A `Substitution` is minted when the word is
    *resolved*, before the model runs, so the note cannot carry whether the run
    went on to answer from it; the caller measures that
    (`compile.workflow_compiler.values_no_statement_carried`) and names the
    canonical values no statement carried. It changes one sentence and
    withdraws nothing: what the word was taken to mean is still disclosed,
    because that is `127`, and only the claim about a result that was never
    obtained is dropped.

    A **set of values** rather than a flag, because one word can resolve on two
    axes at once — *"Persian Gulf"* is a shipping region and a chokepoint
    geofence in the same warehouse — and a run that queried one of them was
    disclosed as being *"for"* both.

    Keyword-only and empty by default — *no such measurement* — so a caller
    that has not made it produces exactly the paragraph it always did.
    """
    lines: list[str] = []
    for note in notes:
        if isinstance(note, SourceChoice):
            lines.append(_source_choice_for_reader(note))
            continue
        if isinstance(note, DeclaredUnit):
            lines.append(_declared_unit_for_reader(note))
            continue
        if isinstance(note, ToolFailure):
            lines.append(_tool_failure_for_reader(note))
            continue
        if isinstance(note, UncoveredWindow):
            lines.append(_uncovered_window_for_reader(note))
            continue
        if isinstance(note, UnverifiedAnswer):
            lines.append(_unverified_answer_for_reader(note))
            continue
        if not isinstance(note, Substitution) or not note.changed_the_question():
            continue
        lines.append(
            _substitution_for_reader(note, note.canonical_value in (unsent_values or frozenset()))
        )
    return "\n".join(_dedup(lines))


def _substitution_for_reader(note: Substitution, unsent: bool) -> str:
    """Two sentences, and which one is said is a measurement — `155`.

    The first is `127`'s, and it makes a claim about a **result**: *the answer
    above is for X*. Live on 2026-08-28 a run that answered nothing carried it
    anyway, and a second live run carried it while having queried a different
    axis entirely.

    The second says the same thing about the **word**, and then states what was
    measured rather than asserting what did not happen — the property
    `UncoveredWindow` and `ToolFailure` already hold. *"No statement this run
    ran carried that value"* is checkable and is exactly what the caller
    looked at; *"nothing above came from that data"* would be a claim about
    every rail there is, and this one can only see statements.
    """
    head = f'You asked for "{note.user_term}". This data holds no such value, so '
    tail = f"{note.canonical_value} on {note.axis} — {_HOW_MATCHED_FOR_READER[note.how_matched]}."
    if not unsent:
        return f"{head}the answer above is for {tail}"
    return (
        f"{head}this run read it as {tail} No statement this run ran carried that value, "
        "so this says what the word was taken to mean and not what any answer is about."
    )


def notes_for_grader(
    notes: tuple[ToolNote, ...] | list[ToolNote],
    *,
    unsent_values: frozenset[str] | set[str] | None = None,
) -> str:
    """The reader rail, shown to the judge — `launch-readiness/154`.

    **Not a third rail.** It carries no sentence of its own: it is
    `notes_for_reader`'s paragraph plus one line saying whose it is. A grader
    handed the disclosure with no framing is being shown text and left to guess
    who wrote it, and the obvious guess — *the candidate already says this* —
    is the one wrong answer available.

    Why a grader is shown it at all: `route.grader` judges the producing node's
    raw text, and the disclosure is appended after it by `_output`. So a
    criterion like *"say which sense you used"* was judged against a document
    that did not yet contain the sentence the reader would get, and on a covered
    term — where the disclosure is unconditional — a model that happened to be
    silent cost a full revise lap to obtain a sentence the reader had anyway.

    It rides in the prompt's generated **Context** layer, never in the
    candidate, so the published answer is untouched and nothing invites the
    model to write the paragraph itself.

    Empty when the disclosure is empty. Silence by default is the whole
    module's rule and it is not suspended for a grader.
    """
    disclosure = notes_for_reader(notes, unsent_values=unsent_values)
    if not disclosure:
        return ""
    return (
        "This workflow appends the following to the answer before anyone reads "
        "it, whichever way you judge. It is the workflow's own disclosure and "
        "the answer does not have to repeat it:\n" + disclosure
    )


def _declared_unit_for_reader(note: DeclaredUnit) -> str:
    """Always rendered when it exists, for `SourceChoice`'s reason.

    A unit is never implied by the user's own words the way a canonical
    spelling can be, so there is no *nothing actually changed* case to stay
    silent about. Silence by default is preserved where it belongs: a row that
    declares nothing mints no note at all.
    """
    axis = note.axis or "The figures above"
    if not note.unit:
        return (
            f"No unit is declared for {axis} in this data, so the figures above are as "
            "it holds them and this run did not name one."
        )
    return f"Figures for {axis} are in {note.unit}, which is what this data declares."


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


def _uncovered_window_for_reader(note: UncoveredWindow) -> str:
    """Two sentences, and which one is said is a declaration rather than a guess.

    Neither names the table, the statement or the column — the reader is told
    what the zero above is worth, never in whose words. The clause carrying the
    ticket is the second half of each: *"cannot be told apart from"* for a table
    that declares nothing, and the date itself for one that does.
    """
    subject = note.subject.strip() or "results"
    if note.declared_max:
        return (
            f"The answer above reports no {subject}. This data's records stop on "
            f"{note.declared_max}, and the period asked about runs past that date, so any "
            f"{subject} after it could not have appeared here whether or not there were any."
        )
    return (
        f"The answer above reports no {subject} for the period asked about. This data does "
        f"not state which period it covers, so \"none\" here cannot be told apart from "
        "\"this data does not reach that period\"."
    )


def _unverified_answer_for_reader(note: UnverifiedAnswer) -> str:
    """The sentence a forced pass owes the person reading it.

    Says that a check objected and that the run ran out of room to satisfy it —
    and **not** what the check said, which is developer text written for a model
    (`launch-readiness/143`). Which ceiling was reached changes a reader's next
    move, so the two are different sentences: an attempts cap is a number on one
    card, the step budget is a number on the workflow.
    """
    if note.starved:
        return (
            "The answer above did not pass this workflow's own check on it, and the "
            "workflow ran out of steps before the check could be satisfied. Treat what it "
            "states as unverified."
        )
    return (
        "The answer above did not pass this workflow's own check on it, and the check ran "
        "out of attempts before it could be satisfied. Treat what it states as unverified."
    )


_QUANTITY_ALREADY_SAYS_FIGURES = re.compile(r"\bfigures?\b", re.I)


def _quantity_subject(quantity: str) -> str:
    """*What comes before "come from …"* — the half `osg-agent-experience/67`
    is about.

    The node's own field help asks the developer for the quantity "in your
    words", offering a bare noun (*"supply"*, *"outages"*) as the example but
    never requiring one. A developer who instead writes a noun phrase that
    already says "the figures" — or writes exactly that phrase — feeds the
    fixed template `The figures for {quantity}` a second copy of the word it
    already supplies, and the result stutters in front of a customer.

    Read tolerantly rather than taught a stricter field: any quantity that
    already talks about "figure(s)" is a subject on its own, so the sentence
    falls back to the fixed subject instead of nesting one figures-phrase
    inside another. A quantity that says nothing about figures — the
    documented common case — is still woven into the template exactly as
    before.
    """
    text = quantity.strip()
    if not text or _QUANTITY_ALREADY_SAYS_FIGURES.search(text):
        return "These figures"
    return f"The figures for {text}"


def _source_choice_for_reader(note: SourceChoice) -> str:
    """The sentence `launch-readiness/150` was filed to make unforgettable.

    *"I do not understand where this number comes from."* — so it names the
    store, says how that was settled, lists what else could have answered,
    and tells the reader that asking for another is a thing they may do. The
    last clause is not decoration: without it a reader learns there was a
    choice and not that it is theirs.

    Neither branch says "this data" where a source name belongs
    (`osg-agent-experience/67`): the source that answered is already named a
    few words earlier, so the clause that explains *how* it was settled
    names the mechanism ("declared here as the default") rather than
    gesturing at an unnamed "this data", and the alternatives are introduced
    as belonging to the same catalogue rather than to a vague "this data".
    """
    subject = _quantity_subject(note.quantity)
    head = f"{subject} come from {note.chosen} — {_HOW_CHOSEN_FOR_READER[note.how_chosen]}."
    if not note.alternatives:
        return head + (
            " It is the only system of record declared for them, so there was nothing to "
            "choose between."
        )
    return head + (
        " The same catalogue also holds "
        + _english_list(note.alternatives)
        + " for the same figures, and they can disagree. Ask for one by name and it will be "
        "re-run against that source."
    )


_HOW_CHOSEN_FOR_READER: dict[str, str] = {
    "named_in_question": "the source you named",
    "declared_default": "declared here as the default",
    "only_source": "the only source declared here",
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
        note
        for note in notes
        if isinstance(
            note,
            (
                Substitution,
                SourceChoice,
                DeclaredUnit,
                ToolFailure,
                UncoveredWindow,
                UnverifiedAnswer,
            ),
        )
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


def peek_notes(thread_id: str | None = None) -> tuple[ToolNote, ...]:
    """Everything this run has recorded so far, **without emptying the bucket**.

    `launch-readiness/154`. The rail has one taker and it must stay one: a
    grader that called `take_notes` to see what the reader will be told would
    empty the bucket and delete the disclosure — trading a wasted revise lap
    for the defect `127` exists to close. So a second *reader* is a different
    verb on one bucket rather than a second reading of one verb, and which
    callers may take is stated where the store is: `_output` takes, everything
    else peeks.
    """
    thread = thread_id if thread_id is not None else _current_thread()
    if not thread:
        return ()
    with _lock:
        return tuple(_recorded.get(thread, ()))


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
    "DeclaredUnit",
    "SourceChoice",
    "Substitution",
    "ToolFailure",
    "ToolNote",
    "UncoveredWindow",
    "UnverifiedAnswer",
    "notes_for_grader",
    "notes_for_model",
    "notes_for_reader",
    "peek_notes",
    "record_notes",
    "take_notes",
]
