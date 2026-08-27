"""What a word is called here — resolved before the model, deterministically.

`launch-readiness/135`. This is the engine behind the `resolve.vocabulary`
node type: derive a few search phrases from the question with plain
heuristics, fire them at a **vocabulary source** concurrently, merge what
comes back **by rank rather than by arrival**, cap, and hand back both the
entries and a report of what was *covered*.

## Why vocabulary and nothing else

The capability was lifted from one package's private prefetch function, which
searched a metadata index for tables, columns and glossary rows alike. The
measurement that scoped this ticket (2026-08-27) found the index described 10
tables against the 38 the domain's lenses name — an overlap of 3 — while its
glossary rows are of a different kind entirely:

    "MEG — Middle East Gulf … Users may say: MEG, Middle East Gulf,
     Arabian Gulf, Persian Gulf (as a trade region)."

**A glossary row is not attached to a table.** It is a fact about the
domain's *language*, true regardless of which store holds the rows, which is
why it ports where a table description does not. So this module resolves
words, and table discovery stays where it already is — a tool the agent
calls.

## Tolerant in reading, strict in trusting

A source is somebody else's Python (a package `functions/` callable), so its
rows arrive in whatever shape that author found natural: a mapping under
several reasonable key spellings, or a bare string. All of those are read.
What is *not* tolerant is the claim made from them: a `Substitution` is only
minted where the entry actually names an axis **and** a canonical value, and
`how_matched` is only ever `exact` or `declared_synonym` — this step runs
before the model and infers nothing, so `model_inference` is a state it must
be unable to record.

A row that cannot be read at all is **counted and reported**, never dropped
in silence.

## The constraint that shaped every branch below

> **A prefetch that finds nothing looks exactly like a term that is not
> ambiguous.**

Six defects on this map were two situations rendering identically. So the
report distinguishes three of them by construction:

| state | what the report says |
| --- | --- |
| the source declares its inventory and none of it matched | *not covered* — conclusive |
| the source does not declare one | *silence here is not evidence* |
| the search failed | *a failure is not a miss* |

A source declares its inventory by carrying a `coverage` attribute — a
callable or a plain sequence of the entry names it holds. It is optional
precisely because an undeclared one is a *different, honestly reportable*
state rather than an error.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from openstategraph.abc.tool_notes import Substitution

#: What the node caps at unless its card says otherwise. A product decision —
#: context costs latency and tokens — and never raised to dodge the ranking.
DEFAULT_MAX_ENTRIES = 12

#: The sentence appended when nothing was covered, unless the card supplies
#: its own. It exists because the alternative to saying this is saying
#: nothing, and saying nothing is indistinguishable from "the term was fine".
DEFAULT_WHEN_UNCOVERED = (
    "Nothing in this vocabulary names the term. Say which axis you chose and "
    "that nothing declared it, rather than treating the term as unambiguous."
)

#: How many phrases one question is worth searching for.
MAX_PHRASES = 5

#: Reciprocal-rank-fusion constant (the conventional 60). See `_fuse`.
_RRF_K = 60

#: `launch-readiness/130`: an English sentence capitalises its first word, so
#: the proper-noun heuristic below would otherwise spend a phrase slot
#: searching for "Can". Stripped from the *front* of a matched sequence, so
#: "Which VLCCs" still yields "VLCCs" and a genuine name is never lost.
_LEADING_STOPWORDS = frozenset(
    """a an and are as at can could did do does find for from give has have how
    is it list may might please should show tell the these this those was were
    what when where which who whom whose why will with would you your""".split()
)

_ID_KEYS = ("id", "entry_id", "key")
_TERM_KEYS = ("term", "name", "label")
_AXIS_KEYS = ("axis", "column", "field", "dimension")
_VALUE_KEYS = ("canonical_value", "value", "literal", "canonical")
_ALIAS_KEYS = ("aliases", "synonyms", "also_called", "users_may_say")
_NOTE_KEYS = ("note", "description", "usage_hint", "hint")
_PREDICATE_KEYS = ("predicate", "where", "glossary_maps_to", "predicate_shape")


@dataclass(frozen=True)
class VocabularyEntry:
    """One thing a vocabulary source says a word means."""

    entry_id: str
    term: str
    axis: str
    canonical_value: str
    aliases: tuple[str, ...]
    note: str
    predicate: str

    def render(self) -> str:
        head = f"- {self.term or self.entry_id}"
        if self.axis and self.canonical_value:
            head += f" — {self.axis} = {self.canonical_value!r}"
        elif self.canonical_value:
            head += f" — {self.canonical_value}"
        lines = [head]
        if self.aliases:
            lines.append("    also called: " + ", ".join(self.aliases))
        if self.note:
            lines.append(f"    note: {self.note}")
        if self.predicate:
            lines.append(f"    predicate: {self.predicate}")
        return "\n".join(lines)


def _strip_leading_stopwords(term: str) -> str:
    words = term.split()
    while words and words[0].lower() in _LEADING_STOPWORDS:
        words.pop(0)
    return " ".join(words)


def derive_phrases(question: str) -> tuple[str, ...]:
    """Heuristics only — no model call. Kept simple and explainable.

    The whole question is always phrase one, so a source that does its own
    matching is never denied the user's actual words; the rest are the
    fragments most likely to *be* a domain term.
    """
    phrases: list[str] = []
    whole = (question or "").strip()
    if whole:
        phrases.append(whole)

    phrases += [m.strip() for m in re.findall(r'"([^"]+)"', question or "") if m.strip()]

    for match in re.findall(r"\b[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3}\b", question or ""):
        term = _strip_leading_stopwords(match.strip())
        if len(term) > 2 and term.lower() not in _LEADING_STOPWORDS:
            phrases.append(term)

    seen: set[str] = set()
    deduped: list[str] = []
    for phrase in phrases:
        key = phrase.lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(phrase)
    return tuple(deduped[:MAX_PHRASES])


def _first(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], ()) and not isinstance(value, (list, tuple, dict)):
            return str(value).strip()
    return ""


def _aliases(row: Mapping[str, Any]) -> tuple[str, ...]:
    for key in _ALIAS_KEYS:
        value = row.get(key)
        if isinstance(value, (list, tuple)):
            return tuple(str(v).strip() for v in value if str(v).strip())
        if isinstance(value, str) and value.strip():
            return tuple(part.strip() for part in value.split(",") if part.strip())
    return ()


def _read_entry(row: Any) -> VocabularyEntry | None:
    """One row, read tolerantly. `None` means *unreadable*, which is counted."""
    if isinstance(row, VocabularyEntry):
        return row
    if isinstance(row, Mapping):
        entry_id = _first(row, _ID_KEYS)
        term = _first(row, _TERM_KEYS)
        note = _first(row, _NOTE_KEYS)
        if not (entry_id or term or note):
            return None
        return VocabularyEntry(
            entry_id=entry_id or term or note,
            term=term or entry_id,
            axis=_first(row, _AXIS_KEYS),
            canonical_value=_first(row, _VALUE_KEYS),
            aliases=_aliases(row),
            note=note,
            predicate=_first(row, _PREDICATE_KEYS),
        )
    if isinstance(row, str) and row.strip():
        text = row.strip()
        # A prose row carries no axis, so it can never mint a substitution —
        # which is the strict half doing its job rather than a limitation.
        return VocabularyEntry(
            entry_id=text, term="", axis="", canonical_value="", aliases=(), note=text, predicate=""
        )
    return None


def _fuse(
    per_phrase: dict[str, list[VocabularyEntry]], max_entries: int
) -> tuple[VocabularyEntry, ...]:
    """Merge several ranked lists into one — by rank, never by arrival.

    `launch-readiness/130`. Reciprocal rank fusion has the property the bug
    needs: any search's rank-1 hit scores `1/(k+1)`, above every rank-2-or-
    worse hit from anywhere, so each search places its best entry before any
    search places its second. A row several searches agree on accumulates and
    rises. Deterministic by construction — phrases are walked in sorted order
    and ties fall back to the entry id — so the output does not depend on
    which future completed first.

    Then, and only then, the cap.
    """
    entries: dict[str, VocabularyEntry] = {}
    fused: dict[str, float] = {}
    for phrase in sorted(per_phrase):
        for rank, entry in enumerate(per_phrase[phrase], start=1):
            entries.setdefault(entry.entry_id, entry)
            fused[entry.entry_id] = fused.get(entry.entry_id, 0.0) + 1.0 / (_RRF_K + rank)
    order = sorted(entries, key=lambda key: (-fused[key], key))
    return tuple(entries[key] for key in order[:max_entries])


def _declared_coverage(source: Any) -> tuple[str, ...] | None:
    """What this source says it holds, or `None` for *it does not say*."""
    declared = getattr(source, "coverage", None)
    if declared is None:
        return None
    try:
        values = declared() if callable(declared) else declared
        return tuple(str(v) for v in values)
    except Exception:  # noqa: BLE001 - an undeclared inventory, honestly reported
        return None


def _find_in_question(question: str, needle: str) -> str | None:
    """The user's own spelling of `needle`, or `None`.

    Word-bounded so "MEG" does not match inside "omega" — a substitution
    minted from a substring would be a claim about a word the user never
    used.
    """
    if not needle.strip():
        return None
    match = re.search(rf"(?<!\w){re.escape(needle.strip())}(?!\w)", question or "", re.IGNORECASE)
    return match.group(0) if match else None


def _substitutions(question: str, entries: Iterable[VocabularyEntry]) -> tuple[Substitution, ...]:
    """`launch-readiness/127`'s tuple, minted only where it is earned.

    Strict: an entry without both an axis and a canonical value makes no
    claim, and `how_matched` is `exact` when the user typed the canonical
    value itself and `declared_synonym` when they typed an alias this source
    *declares*. There is no third branch, because this step infers nothing.
    """
    notes: list[Substitution] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        if not (entry.axis and entry.canonical_value):
            continue
        matched_canonical = _find_in_question(question, entry.canonical_value)
        candidates: list[tuple[str, str]] = []
        if matched_canonical:
            # The user already used this entry's canonical value, so no alias
            # of it can be a substitution *for them* — claiming one would tell
            # a reader their word was replaced when it was not, which is the
            # noise `tool_notes` refuses on the reader rail.
            notes.append(
                Substitution(
                    user_term=matched_canonical,
                    axis=entry.axis,
                    canonical_value=entry.canonical_value,
                    how_matched="exact",
                )
            )
            seen.add((matched_canonical.casefold(), entry.axis, entry.canonical_value))
            continue
        for alias in entry.aliases:
            found = _find_in_question(question, alias)
            if not found:
                continue
            how = "exact" if found.casefold() == entry.canonical_value.casefold() else "declared_synonym"
            candidates.append((found, how))
        for user_term, how in candidates:
            key = (user_term.casefold(), entry.axis, entry.canonical_value)
            if key in seen:
                continue
            seen.add(key)
            notes.append(
                Substitution(
                    user_term=user_term,
                    axis=entry.axis,
                    canonical_value=entry.canonical_value,
                    how_matched=how,  # type: ignore[arg-type]
                )
            )
    return tuple(notes)


@dataclass(frozen=True)
class Resolution:
    """What one resolution found **and what it covered**."""

    question: str
    source_name: str
    phrases: tuple[str, ...]
    entries: tuple[VocabularyEntry, ...]
    substitutions: tuple[Substitution, ...]
    #: What the source says it holds, or `None` for *it does not say*.
    declared: tuple[str, ...] | None
    errors: tuple[str, ...]
    unreadable: int
    when_uncovered: str

    def render(self) -> str:
        """The block handed downstream. Coverage is never optional."""
        title = "## Vocabulary resolved before the model — deterministic lookup, no model call"
        head = [title]
        if self.source_name:
            head.append(f"Source: {self.source_name}")
        head.append(
            f"Searched {len(self.phrases)} phrase(s) concurrently: "
            + ", ".join(f'"{p}"' for p in self.phrases)
        )
        parts = ["\n".join(head)]

        if self.entries:
            parts.append(
                "### What this vocabulary names\n"
                + "\n".join(entry.render() for entry in self.entries)
            )
        if self.substitutions:
            parts.append(
                "### Substituted\n"
                + "\n".join(
                    f'- "{note.user_term}" → {note.canonical_value} on {note.axis} '
                    f"({'exact match' if note.how_matched == 'exact' else 'a synonym this vocabulary declares'})"
                    for note in self.substitutions
                )
            )
        parts.append("### Coverage\n" + self._coverage())
        return "\n\n".join(parts)

    def _coverage(self) -> str:
        lines: list[str] = []
        if self.declared is None:
            lines.append(
                f"This source does not declare what it covers, so it can say what matched "
                f"but not what exists. {len(self.entries)} entr(y/ies) matched."
            )
        else:
            lines.append(
                f"This source declares {len(self.declared)} entr(y/ies): "
                + ", ".join(self.declared)
                + f". {len(self.entries)} of them matched."
            )
        if not self.entries:
            if self.declared is None:
                lines.append(
                    "Nothing matched, and because this source does not declare its "
                    "inventory a miss here is **not** evidence that the term is "
                    "unambiguous — it may simply be uncovered."
                )
            else:
                lines.append(
                    "Nothing matched, and this source does declare its inventory, so the "
                    "term is **not covered** by this vocabulary. That is a gap to declare "
                    "somewhere, not a term that is unambiguous."
                )
            if self.when_uncovered.strip():
                lines.append(self.when_uncovered.strip())
        if self.unreadable:
            lines.append(
                f"{self.unreadable} row(s) could not be read in the shape a vocabulary "
                "entry takes and were skipped — counted here rather than dropped in silence."
            )
        if self.errors:
            lines.append(
                f"{len(self.errors)} of {len(self.phrases)} search(es) failed: "
                + "; ".join(self.errors)
                + ". A failed search is not a miss — what it would have covered is unknown."
            )
        return "\n".join(f"- {line}" for line in lines)


def resolve_vocabulary(
    question: str,
    source: Callable[[str], Any],
    *,
    phrases: Sequence[str] | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    source_name: str = "",
    when_uncovered: str = DEFAULT_WHEN_UNCOVERED,
) -> Resolution:
    """Search `source` concurrently for what the question's words mean here.

    `phrases` is injectable so a caller (and a test) can say exactly what was
    searched; left out, they are derived from the question.
    """
    searched = tuple(phrases) if phrases is not None else derive_phrases(question)
    per_phrase: dict[str, list[VocabularyEntry]] = {}
    errors: list[str] = []
    unreadable = 0

    if searched:
        # Concurrency preserved: `as_completed` returns as results arrive, and
        # nothing about the ordering depends on that any more (`_fuse`).
        with ThreadPoolExecutor(max_workers=max(1, len(searched))) as pool:
            futures = {pool.submit(source, phrase): phrase for phrase in searched}
            for future in as_completed(futures):
                phrase = futures[future]
                try:
                    rows = list(future.result() or [])
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{phrase}: {exc}")
                    continue
                read: list[VocabularyEntry] = []
                for row in rows:
                    entry = _read_entry(row)
                    if entry is None:
                        unreadable += 1
                    else:
                        read.append(entry)
                per_phrase[phrase] = read

    entries = _fuse(per_phrase, max(1, int(max_entries)))
    return Resolution(
        question=question or "",
        source_name=source_name,
        phrases=searched,
        entries=entries,
        substitutions=_substitutions(question or "", entries),
        declared=_declared_coverage(source),
        errors=tuple(sorted(errors)),
        unreadable=unreadable,
        when_uncovered=when_uncovered,
    )


def unresolved_source(source_name: str, when_uncovered: str = DEFAULT_WHEN_UNCOVERED) -> str:
    """What the node says when its source does not exist.

    Not a passthrough. A resolver that silently forwarded the question would
    put the run in exactly the state this whole module exists to make
    impossible: no vocabulary consulted, and nothing saying so.
    """
    named = source_name or "(none named)"
    lines = [
        "## Vocabulary resolved before the model — deterministic lookup, no model call",
        "",
        "### Coverage",
        f"- No vocabulary source resolved for {named}, so **nothing was consulted**. "
        "This is not a miss and not a clean term: the lookup did not happen.",
    ]
    if when_uncovered.strip():
        lines.append(f"- {when_uncovered.strip()}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_WHEN_UNCOVERED",
    "MAX_PHRASES",
    "Resolution",
    "VocabularyEntry",
    "derive_phrases",
    "resolve_vocabulary",
    "unresolved_source",
]
