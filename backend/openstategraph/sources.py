"""Which store answered — settled before the model, deterministically.

`launch-readiness/150`. This is the engine behind the `resolve.source` node
type, and the sibling of `openstategraph.vocabulary` on the same rung ladder:

| | answers |
| --- | --- |
| `resolve.vocabulary` | *"what does this word mean here?"* |
| `resolve.source` | *"which of the several stores that could answer this is answering it — and what else could have?"* |

Both are deterministic, both run **before** the model, and both record what
they did on the run's own rail so the disclosure is not the model's to forget.

## The complaint

> *"the AI should state the assumptions on which source (or BAV) is being
> used, and guide the user to the fact that there are multiple sources… In
> the may number 1664 is given in the table. I do not understand where this
> number comes from."*

> *"I expected the outage to reflect the plant tracker data. For russia we
> have 4031 kbd for the week starting on the 24.8. This is very different to
> the number presented in the table."*

Three of seven complaints in that round were this one failure. **Neither is
missing data.** The balance lens carries a provider dimension with its own
lookup, and the outage store holds the quantity at several grains from
several systems of record — so `4031` and the table's figure may *both* be
right. The defect is that the answer named neither, and a number with no
stated source is indistinguishable from a number from the wrong one.

## A step, not a tool — and not a prompt

A source must not be a choice the model makes differently on every run; that
is the argument `resolve.vocabulary` already made and measured. And it is not
a sentence in a preamble: six prompt-level rules have been declined on this
project, and `cpl-mcp`'s prompt already carries a rule of exactly this shape
which six runs ignored.

## Tolerant in reading, strict in trusting

A catalogue is somebody else's Python (a package `functions/` callable), so
its rows arrive in whatever shape that author found natural — a mapping under
several reasonable key spellings, or a bare name. All of those are read. What
is *not* tolerant is the claim made from them: a `SourceChoice` is minted only
where **something other than this module decided** — the user named a source,
the catalogue declared a default, or there was only ever one. There is no
branch in which this module prefers a source, because a preference invented
here would arrive on the reader's rail wearing the same clothes as a
declaration.

## The constraint that shaped every branch below

`resolve.vocabulary` was built around *a prefetch that finds nothing looks
exactly like a term that is not ambiguous.* Here the analogous trap is
sharper, because the two states are both success-shaped:

> **A catalogue that declares no provider dimension and a catalogue with
> exactly one source must not look the same.**

One means *there is nothing to choose*. The other means *we could not tell*.
So five states are distinguished by construction and none of them can be
turned off:

| state | what the report says |
| --- | --- |
| the catalogue named nothing | *silence here is not evidence* — it cannot say whether one store or six could answer |
| exactly one source | *nothing to choose* — conclusive, and the source is still named |
| several, and one is settled | the choice, how it was settled, and the alternatives |
| several, and none is settled | the run **could not tell**; no note is minted |
| the lookup failed | *a failure is not a miss* |

and a sixth, `unresolved_catalogue`, for *nothing was consulted at all*.

## Where the fourth state stops, and what it is waiting for

Several live sources with no default is `guardrails/06`'s territory — *a
router that cannot tell should ask, not guess*. That abstain does not exist
yet (checked 2026-08-28: `guardrails/06` is open and unbuilt), so this module
**leaves the seam rather than building a competing way to ask**: it records no
choice, reports the live sources by name, and carries the developer's
`when_undecided` sentence downstream, where a router that can abstain will one
day read it. Nothing here routes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from openstategraph.abc.tool_notes import SourceChoice

#: Carried downstream when several systems of record are live and nothing
#: settled which. It exists because the alternative to saying this is picking
#: one, and picking one silently is the whole defect.
DEFAULT_WHEN_UNDECIDED = (
    "More than one system of record can answer this and none is declared the default. "
    "Say which ones are live and ask which is meant, rather than choosing one and "
    "presenting its figures as the figures."
)

_ID_KEYS = ("id", "source_id", "provider_id", "key")
_NAME_KEYS = ("name", "source", "provider", "label", "term")
_DEFAULT_KEYS = ("default", "is_default", "preferred", "is_preferred")
_ALIAS_KEYS = ("aliases", "synonyms", "also_called", "users_may_say")
_GRAIN_KEYS = ("grain", "granularity", "frequency", "resolution", "period")
_NOTE_KEYS = ("note", "description", "usage_hint", "hint")
_PREDICATE_KEYS = ("predicate", "where", "filter", "predicate_shape")


@dataclass(frozen=True)
class DeclaredSource:
    """One system of record a catalogue says could answer the question."""

    source_id: str
    name: str
    is_default: bool
    aliases: tuple[str, ...]
    grain: str
    note: str
    predicate: str

    @property
    def label(self) -> str:
        return self.name or self.source_id

    def render(self) -> str:
        head = f"- {self.label}"
        if self.grain:
            head += f" — {self.grain}"
        if self.is_default:
            head += " (declared default)"
        lines = [head]
        if self.aliases:
            lines.append("    also called: " + ", ".join(self.aliases))
        if self.note:
            lines.append(f"    note: {self.note}")
        if self.predicate:
            lines.append(f"    predicate: {self.predicate}")
        return "\n".join(lines)


def _first(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], ()) and not isinstance(value, (list, tuple, dict, bool)):
            return str(value).strip()
    return ""


def _flag(row: Mapping[str, Any], keys: Sequence[str]) -> bool:
    for key in keys:
        if key in row:
            return bool(row[key])
    return False


def _aliases(row: Mapping[str, Any]) -> tuple[str, ...]:
    for key in _ALIAS_KEYS:
        value = row.get(key)
        if isinstance(value, (list, tuple)):
            return tuple(str(v).strip() for v in value if str(v).strip())
        if isinstance(value, str) and value.strip():
            return tuple(part.strip() for part in value.split(",") if part.strip())
    return ()


def _read_source(row: Any) -> DeclaredSource | None:
    """One row, read tolerantly. `None` means *unreadable*, which is counted."""
    if isinstance(row, DeclaredSource):
        return row
    if isinstance(row, Mapping):
        source_id = _first(row, _ID_KEYS)
        name = _first(row, _NAME_KEYS)
        if not (source_id or name):
            return None
        return DeclaredSource(
            source_id=source_id or name,
            name=name or source_id,
            is_default=_flag(row, _DEFAULT_KEYS),
            aliases=_aliases(row),
            grain=_first(row, _GRAIN_KEYS),
            note=_first(row, _NOTE_KEYS),
            predicate=_first(row, _PREDICATE_KEYS),
        )
    if isinstance(row, str) and row.strip():
        # A bare name is enough to *declare* a source — the alternatives are
        # the payload and a name is what a reader needs to ask for one. It can
        # never be a default, because nothing said it was.
        text = row.strip()
        return DeclaredSource(
            source_id=text, name=text, is_default=False, aliases=(), grain="", note="", predicate=""
        )
    return None


def _named_in(question: str, source: DeclaredSource) -> bool:
    """Whether the user asked for this source, by any name it declares.

    Word-bounded, for the reason `vocabulary._find_in_question` is: a source
    chosen from inside another word ("JODI" in "jodible") is a claim the user
    never made, and here that claim decides which figures they are shown.
    """
    for needle in (source.name, source.source_id, *source.aliases):
        if not str(needle).strip():
            continue
        if re.search(rf"(?<!\w){re.escape(str(needle).strip())}(?!\w)", question or "", re.I):
            return True
    return False


@dataclass(frozen=True)
class Selection:
    """What one resolution settled **and what it could not**."""

    question: str
    quantity: str
    catalogue_name: str
    sources: tuple[DeclaredSource, ...]
    chosen: DeclaredSource | None
    #: `""` where nothing was settled — never a fourth `how_chosen` value.
    how_chosen: str
    alternatives: tuple[DeclaredSource, ...]
    #: More than one source matched the user's words, so naming settled nothing.
    named_several: tuple[DeclaredSource, ...]
    #: More than one row declared itself the default.
    rival_defaults: tuple[DeclaredSource, ...]
    error: str
    unreadable: int
    when_undecided: str

    @property
    def notes(self) -> tuple[SourceChoice, ...]:
        """The run's record — empty wherever nothing was actually settled."""
        if self.chosen is None or not self.how_chosen:
            return ()
        return (
            SourceChoice(
                quantity=self.quantity,
                chosen=self.chosen.label,
                alternatives=tuple(s.label for s in self.alternatives),
                how_chosen=self.how_chosen,  # type: ignore[arg-type]
            ),
        )

    def render(self) -> str:
        """The block handed downstream. Coverage is never optional."""
        head = ["## System of record settled before the model — declared lookup, no model call"]
        if self.catalogue_name:
            head.append(f"Catalogue: {self.catalogue_name}")
        if self.quantity:
            head.append(f"Quantity: {self.quantity}")
        parts = ["\n".join(head)]

        if self.chosen is not None:
            parts.append(
                "### Using\n"
                + self.chosen.render()
                + f"\n    settled by: {_HOW_CHOSEN_IN_REPORT[self.how_chosen]}"
            )
        if self.alternatives:
            parts.append(
                "### Not used, and available\n"
                + "\n".join(source.render() for source in self.alternatives)
                + "\n\nThese can disagree. A figure from one is not comparable with a figure "
                "from another, and the user may ask for any of them by name."
            )
        if self.chosen is None and self.sources:
            parts.append(
                "### Live systems of record\n"
                + "\n".join(source.render() for source in self.sources)
            )
        parts.append("### Coverage\n" + self._coverage())
        return "\n\n".join(parts)

    def _coverage(self) -> str:
        lines: list[str] = []
        if self.error:
            lines.append(
                f"The catalogue lookup failed ({self.error}). A failure is not a miss — "
                "which systems of record exist here is unknown, so no figure below can "
                "claim a source."
            )
        elif not self.sources:
            lines.append(
                "This catalogue names no system of record for this question, so it cannot "
                "say whether one store or six could answer it. Silence here is **not "
                "evidence** that there is only one."
            )
        elif len(self.sources) == 1:
            lines.append(
                f"This catalogue declares exactly one system of record — {self.sources[0].label} "
                "— so there was nothing to choose between. Name it in the answer anyway: a "
                "figure with no stated source reads the same as a figure from the wrong one."
            )
        elif self.chosen is not None:
            lines.append(
                f"This catalogue declares {len(self.sources)} systems of record. "
                f"{self.chosen.label} answered; "
                + ", ".join(source.label for source in self.alternatives)
                + " did not, and could have."
            )
        else:
            if self.named_several:
                lines.append(
                    "The question named more than one system of record ("
                    + ", ".join(source.label for source in self.named_several)
                    + "), so naming settled nothing."
                )
            if self.rival_defaults:
                lines.append(
                    ", ".join(source.label for source in self.rival_defaults)
                    + " both declare themselves the default, so the declaration settled nothing."
                )
            lines.append(
                f"{len(self.sources)} systems of record are live and **nothing settled which "
                "one answers**. No source was chosen here, and none may be chosen downstream "
                "without saying so."
            )
            if self.when_undecided.strip():
                lines.append(self.when_undecided.strip())
        if self.unreadable:
            lines.append(
                f"{self.unreadable} row(s) could not be read in the shape a declared source "
                "takes and were skipped — counted here rather than dropped in silence."
            )
        return "\n".join(f"- {line}" for line in lines)


_HOW_CHOSEN_IN_REPORT: dict[str, str] = {
    "named_in_question": "the question named it",
    "declared_default": "this catalogue declares it the default",
    "only_source": "it is the only one declared",
}


def resolve_source(
    question: str,
    catalogue: Callable[[str], Any],
    *,
    quantity: str = "",
    catalogue_name: str = "",
    when_undecided: str = DEFAULT_WHEN_UNDECIDED,
) -> Selection:
    """Ask `catalogue` which stores could answer, and settle which one does.

    One call, not one per phrase: this is an inventory question, not a search
    (`vocabulary.resolve_vocabulary` is the search, and its concurrency is
    there because it fires several phrases).

    The order of the three settling rules is the substance. The user's own
    words come first — that is what makes *"ask for another and I will re-run"*
    true — then what the catalogue declares, then the degenerate case of one.
    Nothing after that: an unsettled question stays unsettled.
    """
    error = ""
    rows: list[Any] = []
    try:
        rows = list(catalogue(question) or [])
    except Exception as exc:  # noqa: BLE001 - a failure is reported, never a miss
        error = str(exc)

    sources: list[DeclaredSource] = []
    unreadable = 0
    for row in rows:
        source = _read_source(row)
        if source is None:
            unreadable += 1
        else:
            sources.append(source)

    ordered = tuple(sorted(sources, key=lambda s: s.label.casefold()))
    named = tuple(s for s in ordered if _named_in(question, s))
    defaults = tuple(s for s in ordered if s.is_default)

    chosen: DeclaredSource | None = None
    how_chosen = ""
    named_several: tuple[DeclaredSource, ...] = ()
    rival_defaults: tuple[DeclaredSource, ...] = ()

    if len(named) == 1:
        chosen, how_chosen = named[0], "named_in_question"
    elif len(named) > 1:
        named_several = named
    elif len(ordered) == 1:
        chosen, how_chosen = ordered[0], "only_source"
    elif len(defaults) == 1:
        chosen, how_chosen = defaults[0], "declared_default"
    elif len(defaults) > 1:
        rival_defaults = defaults

    alternatives = tuple(s for s in ordered if chosen is not None and s is not chosen)
    return Selection(
        question=question or "",
        quantity=quantity or "",
        catalogue_name=catalogue_name,
        sources=ordered,
        chosen=chosen,
        how_chosen=how_chosen,
        alternatives=alternatives,
        named_several=named_several,
        rival_defaults=rival_defaults,
        error=error,
        unreadable=unreadable,
        when_undecided=when_undecided,
    )


def unresolved_catalogue(
    catalogue_name: str, when_undecided: str = DEFAULT_WHEN_UNDECIDED
) -> str:
    """What the node says when its catalogue does not exist.

    Not a passthrough, for the same reason `vocabulary.unresolved_source` is
    not: a step that silently forwarded the question would put the run in
    exactly the state this module exists to make impossible — no catalogue
    consulted, and nothing saying so.
    """
    named = catalogue_name or "(none named)"
    lines = [
        "## System of record settled before the model — declared lookup, no model call",
        "",
        "### Coverage",
        f"- No source catalogue resolved for {named}, so **nothing was consulted**. Which "
        "systems of record this data holds was never asked, so no figure below may name "
        "one and none may imply there is only one.",
    ]
    if when_undecided.strip():
        lines.append(f"- {when_undecided.strip()}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_WHEN_UNDECIDED",
    "DeclaredSource",
    "Selection",
    "resolve_source",
    "unresolved_catalogue",
]
