"""The guardrail ladder: ``IGuardrail`` → ``BaseGuardrail`` → ``Guardrail``.

Same shape as the router and the grader, and for the same reason: applying a
policy to a piece of text is always the same job — detect, transform or
refuse, and say what happened without repeating what was found — and none of
that is domain knowledge. What varies is the **table**.

## Detection is borrowed, never written

The map's out-of-scope section is one line: *writing our own PII detectors is
"never reinvent" in a smaller costume*. `RedactionRule` is exported from
`langchain.agents.middleware` (it is the public type `ShellToolMiddleware`
takes as `redaction_rules`), `RedactionRule.resolve()` returns a rule whose
`.apply(text)` gives back `(text, matches)`, and `PIIDetectionError` carries
the entity and every match. So every shape — `email`, `credit_card` with its
Luhn checksum, `ip`, `mac_address`, `url` — and all four strategies come from
the library, and this module contains no regular expression at all. (It
imports `re` since guardrails ticket 05, to *check* the one regex a developer
may write — `detector` — before a run reaches it. Checking somebody else's
pattern is not writing one.)

That answers ticket 01's research question directly, and it answers it the
better way: **detection is separable from the middleware**, so a guardrail is
a plain graph node rather than a degenerate agent built only to carry
middleware it never uses.

## The two things the library has no opinion about

**`pass` is a fifth strategy, and it is ours.** LangChain has four, because
middleware is configured by *listing the rules you want*: an entity you did
not name is simply not handled. On a canvas that is a silence, and the
owner's requirement is precisely a decision that must not be silent — a user
gives an email address to look up a customer, so email **inbound must pass**
or the product cannot do its job, while the same email **outbound** is
customer data leaving the building. `pass` makes that first half a row
somebody wrote rather than a row nobody wrote.

**A block is a value, not an exception.** `apply_strategy` raises
`PIIDetectionError`, which is right for middleware wrapping one model call
and wrong for a graph node: an exception out of a node takes down a run that
was behaving exactly as designed. `Screening` carries the verdict the way
`Verdict` does for the grader, and the compiler turns it into an edge.

## What this ladder deliberately does not know

**Which direction it is.** The map settled that position is the scope: an
instance placed after Input and an instance placed before Output differ only
in the table they carry. Nothing here has an `apply_to_input` flag, because
there is nowhere on a canvas for one to mean anything the wire does not
already say.

**Prompt injection.** These detectors are deterministic shapes. Nothing here
looks at intent — see `docs/decisions/injection-screening.md` and
`openstategraph.injection`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping, Protocol, Sequence, cast, runtime_checkable

#: The entity types LangChain detects out of the box, most specific first.
#:
#: Mirrored here rather than imported at module scope so that reading the
#: catalogue costs nothing; `test_guardrail.py` asserts the two sets are equal,
#: so a LangChain release adding one fails a test instead of leaving the card
#: quietly behind the runtime.
BUILTIN_ENTITIES: tuple[str, ...] = ("email", "credit_card", "ip", "mac_address", "url")

#: Every strategy a row may name. Four are LangChain's; `pass` is ours — see
#: the module docstring for why an allowed entity has to be sayable.
STRATEGIES: tuple[str, ...] = ("pass", "redact", "mask", "hash", "block")

#: The longest pattern a `detector` may be, in characters.
#:
#: A bound on the absurd, and **not** a defence against a pathological pattern:
#: `(a+)+$` is six characters. See `detector_problem` for what is refused and
#: what is deliberately not. Mirrored on the card by
#: `src/nodes/guard/detectorPattern.ts` and pinned by
#: `backend/tests/test_a_detector_is_checked_before_it_runs.py`.
DETECTOR_MAX_LENGTH = 400


def detector_problem(detector: str) -> str:
    """Why this pattern cannot be used, or `""` if it can.

    The single place "invalid detector" is decided, so that the card, the
    compiler and the ladder cannot hold three opinions of it — the same role
    `resolved` plays for a strategy and `STRATEGIES` for its vocabulary.

    **Compiling is not running.** `re.compile` parses a pattern; it matches
    nothing, so asking it whether a user's regex is well formed costs a parse
    and executes none of the user's intent. That distinction is the whole fix
    here: the check that used to happen was `resolved()` inside `screen()`,
    where compiling and matching arrive together, mid-run.

    **What is refused, stated plainly: nothing about how long a match takes.**
    Catastrophic backtracking — `(a+)+$` against a long non-matching string —
    is not detected here and is not bounded anywhere else either. Python's
    `re` cannot be interrupted, so the only real answers are a third-party
    engine with a `timeout=` or a subprocess per screening, and both are a
    dependency and a per-run cost paid by every document to bound a pattern
    the document's own author wrote. A nested-quantifier heuristic was
    considered and rejected for the reason CLAUDE.md gives for pinning numbers:
    it would refuse legitimate patterns and miss others, while reading like a
    guarantee. So the trust boundary is stated instead — a detector is code the
    package author supplies, at the same trust level as that package's
    `tools/*.py`, and mounting a third party's package means running a third
    party's patterns.
    """
    if not detector:
        return ""
    if len(detector) > DETECTOR_MAX_LENGTH:
        return (
            f"is {len(detector)} characters long; a pattern may be at most "
            f"{DETECTOR_MAX_LENGTH}."
        )
    try:
        re.compile(detector)
    except re.error as bad:
        return f'"{detector}" is not a valid pattern: {bad.msg}.'
    return ""

#: How the refusal names an entity. Category names, never values, and phrased
#: so one sentence works in both directions: an outbound block is refusing the
#: model's own answer, so "remove it and try again" would be addressed to
#: somebody who never wrote it.
_ENTITY_NAMES: dict[str, str] = {
    "email": "an email address",
    "credit_card": "a credit card number",
    "ip": "an IP address",
    "mac_address": "a MAC address",
    "url": "a link",
}


@dataclass(frozen=True)
class GuardrailRule:
    """One row of the policy table: what to look for, and what to do.

    `detector` is a **regular expression string**, and that is a portability
    decision recorded rather than defaulted (ticket 01). `workflow.json` is
    the vendor-neutral layer and CLAUDE.md forbids host-language code in it —
    a stored Python lambda kills portability and serialisability in one move.
    A regex is neither: it is declarative data with a published grammar that
    every plausible target runtime implements, which is the same reason
    `Reducer` is a name rather than a function. The library's own
    `RedactionRule` takes `str` for exactly this case.

    The residual cost, stated rather than hidden: dialects differ at the edges
    (lookbehind, named groups), so what round-trips is the common subset — and
    a pathological pattern is the author's own to run on the author's own
    server, the same trust level as the Python in their package's `tools/`.
    """

    entity: str
    strategy: str = "redact"
    detector: str = ""


@dataclass(frozen=True)
class Redaction:
    """What one rule did to one text.

    **There is no field that could hold a value, and that is the type doing
    ticket 03's work.** The developer channel is entitled to "3 emails
    redacted from this answer"; showing *which* three recreates the leak in
    the surface people read most often. A shape that cannot carry the value
    cannot leak it by a later edit either.
    """

    entity: str
    strategy: str
    count: int


@dataclass(frozen=True)
class Screening:
    """The outcome of applying a policy to one text.

    A value, in the same spirit as `Verdict`: the node decides, the compiler's
    conditional edge dispatches, and neither has to catch anything.
    """

    text: str
    blocked: bool = False
    #: The entity that caused the block. Empty when nothing was blocked.
    blocked_entity: str = ""
    redactions: tuple[Redaction, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        """Whether the policy altered the text at all.

        Read by the compiler's builder to decide whether to overwrite a
        settled `answer`: a guardrail that found nothing must not publish
        anything, or an inbound instance would announce the question as the
        run's answer.
        """
        return self.blocked or bool(self.redactions)


@runtime_checkable
class IGuardrail(Protocol):
    """The contract consumers depend on."""

    def screen(self, text: str) -> Screening: ...


class BaseGuardrail(ABC):
    """Everything every guardrail shares, declared once."""

    BUILTIN_ENTITIES: ClassVar[tuple[str, ...]] = BUILTIN_ENTITIES
    STRATEGIES: ClassVar[tuple[str, ...]] = STRATEGIES

    def __init__(
        self,
        *,
        rules: Sequence[GuardrailRule | Mapping[str, Any]] = (),
        refusal: str = "",
    ) -> None:
        self.rules = tuple(self._coerce(row) for row in rules if self._named(row))
        #: The developer's own refusal copy. Their words, not machinery — a
        #: refusal is a message to a person, not part of a prompt's contract,
        #: so unlike an output contract this one is theirs to write.
        self.refusal = refusal.strip()

    # -- reading the table ------------------------------------------------- #

    @staticmethod
    def _named(row: GuardrailRule | Mapping[str, Any]) -> bool:
        """Whether a row names an entity at all.

        A blank row is what a half-filled card looks like mid-edit, and
        dropping it is what lets the rest of the table still run. A *named*
        row with a bad strategy is the opposite case and raises — see
        `resolved`.
        """
        entity = row.entity if isinstance(row, GuardrailRule) else row.get("entity")
        return bool(str(entity or "").strip())

    @staticmethod
    def _coerce(row: GuardrailRule | Mapping[str, Any]) -> GuardrailRule:
        if isinstance(row, GuardrailRule):
            return row
        return GuardrailRule(
            entity=str(row.get("entity") or "").strip(),
            strategy=str(row.get("strategy") or "redact").strip(),
            detector=str(row.get("detector") or ""),
        )

    def resolved(self) -> tuple[tuple[GuardrailRule, Any], ...]:
        """The single place a table becomes library rules.

        The counterpart of `BaseGrader.resolve_system_prompt` and of
        `AbstractAgentNode.resolveMiddleware`: config becomes machinery in one
        method, so a subclass shapes the table rather than reimplementing the
        translation.

        `pass` rows resolve to nothing — they are a statement on the card that
        this entity is allowed here, and the correct implementation of
        "allowed" is to install no detector for it.

        Raises `ValueError` for a strategy nobody implements, a custom entity
        with no pattern, or a pattern that is not a pattern. All three are
        cards that claim a protection which does not exist, and a guardrail
        that silently is not there is worse than no guardrail at all.

        The third one used to be the exception: a malformed `detector` reached
        `re.compile` inside the library, mid-run, and came back as a bare
        `re.error` — which is not a `ValueError`, so the compiler's own
        handler around `screen()` did not catch it and the run died with a
        traceback out of the standard library (guardrails ticket 05). It is a
        `ValueError` now, alongside its two siblings, and `problems()` finds
        it at compile time so nobody has to meet it here.
        """
        from langchain.agents.middleware import RedactionRule

        out: list[tuple[GuardrailRule, Any]] = []
        for rule in self.rules:
            if rule.strategy not in self.STRATEGIES:
                raise ValueError(
                    f'Guardrail rule for "{rule.entity}" names strategy '
                    f'"{rule.strategy}", which is not one of {", ".join(self.STRATEGIES)}.'
                )
            problem = detector_problem(rule.detector)
            if problem:
                raise ValueError(f'Guardrail rule for "{rule.entity}": pattern {problem}')
            if rule.strategy == "pass":
                continue
            out.append(
                (
                    rule,
                    RedactionRule(
                        pii_type=rule.entity,
                        # The `cast` is where our five-member vocabulary meets
                        # the library's four. The check above is what makes it
                        # safe, and it is the *reason* the check is a raise
                        # rather than a filter: a strategy that reached here
                        # unrecognised would be a guardrail silently absent.
                        strategy=cast("Any", rule.strategy),
                        detector=rule.detector or None,
                    ).resolve(),
                )
            )
        return tuple(out)

    def problems(self) -> tuple[tuple[str, str], ...]:
        """Every row that cannot do what its card says, as `(entity, why)`.

        The compile-time half of `resolved`, and deliberately a *list* rather
        than a raise: `resolved` stops at the first bad row because it is
        producing machinery and there is nothing to produce, while a developer
        looking at a card wants all three mistakes at once rather than three
        runs.

        Cheap on purpose — it parses patterns and reads a tuple, and imports
        nothing from LangChain — so the compiler can call it on every guardrail
        node it builds without paying for detectors it may never run.
        """
        found: list[tuple[str, str]] = []
        for rule in self.rules:
            if rule.strategy not in self.STRATEGIES:
                found.append(
                    (
                        rule.entity,
                        f'names strategy "{rule.strategy}", which is not one of '
                        f'{", ".join(self.STRATEGIES)}',
                    )
                )
                continue
            problem = detector_problem(rule.detector)
            if problem:
                found.append((rule.entity, f"pattern {problem.rstrip('.')}"))
        return tuple(found)

    # -- the part a subclass supplies -------------------------------------- #

    @abstractmethod
    def refusal_for(self, entity: str) -> str:
        """What a person is told when this entity blocked the text.

        Abstract because the copy is the whole of a refusal's usefulness, and
        because the base has no way to know a deployment's tone. `Guardrail`
        supplies a default that names the category.
        """

    # -- inherited behaviour ----------------------------------------------- #

    def screen(self, text: str) -> Screening:
        """Apply the table, in order, and report what it did.

        Order is the substance, as it is for a prompt and for middleware: each
        rule sees what the rule before it left, so `redact` then `mask` is not
        `mask` then `redact`. A `block` short-circuits, because there is no
        longer any text of the user's for a later rule to act on.
        """
        if not text:
            return Screening(text=text)

        from langchain.agents.middleware import PIIDetectionError

        current = text
        done: list[Redaction] = []
        for rule, resolved in self.resolved():
            try:
                current, matches = resolved.apply(current)
            except PIIDetectionError as blocked:
                done.append(Redaction(rule.entity, rule.strategy, len(blocked.matches)))
                return Screening(
                    text=self.refusal or self.refusal_for(rule.entity),
                    blocked=True,
                    blocked_entity=rule.entity,
                    redactions=tuple(done),
                )
            if matches:
                done.append(Redaction(rule.entity, rule.strategy, len(matches)))
        return Screening(text=current, redactions=tuple(done))


class Guardrail(BaseGuardrail):
    """The default, and what the editor's Guardrail node instantiates.

    Almost empty, which is the demonstration: a working guardrail is a table,
    not a new class.
    """

    def refusal_for(self, entity: str) -> str:
        """Names the category, never the value — ticket 03's trade, decided.

        "Not allowed" teaches a prober nothing and frustrates the far more
        common case: someone who pasted their own card number out of habit and
        cannot tell which part of their message was the problem. Naming the
        category is marginally more informative to an attacker, who already
        knows what they sent and could learn the same by trying one entity at
        a time whatever the wording says. The asymmetry is decisive.
        """
        named = _ENTITY_NAMES.get(entity, f"a {entity.replace('_', ' ')}")
        return (
            f"Blocked by a guardrail: this content contains {named}, "
            "which this workflow is not allowed to pass on."
        )


__all__ = [
    "BUILTIN_ENTITIES",
    "STRATEGIES",
    "BaseGuardrail",
    "Guardrail",
    "GuardrailRule",
    "IGuardrail",
    "Redaction",
    "Screening",
]
