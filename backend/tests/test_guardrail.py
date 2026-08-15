"""The guardrail ladder: a policy table applied to one text.

Guardrails ticket 01. The load-bearing research question the ticket asked —
*"establish whether `PIIMiddleware`'s detection is separable for use inside a
node, and if it is not, whether the node is better implemented as a degenerate
agent carrying only that middleware"* — is answered by these tests being
possible at all: `RedactionRule` is exported from
`langchain.agents.middleware`, `.resolve().apply(text)` returns
`(text, matches)`, and `PIIDetectionError` carries the type and the matches.
So the detection is separable, no agent is involved, and this ladder never
writes a regex of its own.

What it *does* own is the two things the library has no opinion about:

- **`pass` as a strategy.** Not one of LangChain's four. It means "this entity
  is allowed through here", and it exists so the owner's requirement is
  *stated on the card* rather than inferred from an absent row: a user gives
  an email to look up a customer, so email inbound must pass or the product
  cannot do its job.
- **A block is a value, not an exception.** `apply_strategy` raises; a graph
  node that raises takes the whole run down. `Screening` carries the verdict
  the way `Verdict` does for the grader.
"""

from __future__ import annotations

import pytest

from openstategraph.abc.guardrail import (
    BUILTIN_ENTITIES,
    STRATEGIES,
    BaseGuardrail,
    Guardrail,
    GuardrailRule,
    IGuardrail,
    Screening,
)

EMAIL = "carla.almeida@example.com"
CARD = "5105-1051-0510-5100"


class TestTheVocabularyIsTheLibrarysPlusOne:
    def test_the_built_in_entities_are_exactly_what_langchain_ships(self) -> None:
        # Never our own list of shapes: the map's out-of-scope section is
        # explicit that hand-rolling regexes is "never reinvent" in a smaller
        # costume. This asserts against the library's own table, so a
        # LangChain release that adds `phone` fails here rather than leaving
        # the card silently behind.
        from langchain.agents.middleware._redaction import BUILTIN_DETECTORS

        assert set(BUILTIN_ENTITIES) == set(BUILTIN_DETECTORS)

    def test_pass_is_the_only_strategy_we_add(self) -> None:
        assert set(STRATEGIES) - {"block", "redact", "mask", "hash"} == {"pass"}

    def test_a_guardrail_satisfies_the_protocol(self) -> None:
        assert isinstance(Guardrail(rules=[]), IGuardrail)


class TestOneEntityTwoAnswers:
    """The owner's case, and the reason the unit of policy is entity x direction.

    Both instances are *this same class*. Nothing here knows which direction
    it is; the difference is entirely which table the card carries, which is
    the map's "position is the scope" decision made mechanical.
    """

    def test_pass_leaves_the_true_value_for_the_machine(self) -> None:
        inbound = Guardrail(rules=[{"entity": "email", "strategy": "pass"}])
        screening = inbound.screen(f"look up {EMAIL} please")

        assert screening.text == f"look up {EMAIL} please"
        assert screening.redactions == ()
        assert not screening.changed

    def test_redact_removes_it_for_the_human(self) -> None:
        outbound = Guardrail(rules=[{"entity": "email", "strategy": "redact"}])
        screening = outbound.screen(f"Her address is {EMAIL}.")

        assert screening.text == "Her address is [REDACTED_EMAIL]."
        assert screening.changed
        assert [r.count for r in screening.redactions] == [1]

    def test_a_redaction_reports_counts_and_types_and_never_the_value(self) -> None:
        # Ticket 03: the developer channel carries "3 emails redacted", not
        # three email addresses. The type has no field that could hold one.
        outbound = Guardrail(rules=[{"entity": "email", "strategy": "redact"}])
        screening = outbound.screen(f"{EMAIL}, b@x.io and c@y.io")

        (redaction,) = screening.redactions
        assert (redaction.entity, redaction.strategy, redaction.count) == ("email", "redact", 3)
        assert EMAIL not in repr(screening.redactions)


class TestEveryStrategyIsTheLibrarys:
    def test_mask_keeps_the_tail(self) -> None:
        guard = Guardrail(rules=[{"entity": "credit_card", "strategy": "mask"}])
        assert guard.screen(f"card {CARD}").text == "card ****-****-****-5100"

    def test_hash_is_deterministic(self) -> None:
        guard = Guardrail(rules=[{"entity": "email", "strategy": "hash"}])
        first = guard.screen(EMAIL).text
        assert first == guard.screen(EMAIL).text
        assert first.startswith("<email_hash:")

    def test_credit_card_is_luhn_validated_by_the_library(self) -> None:
        # The single strongest argument for adopting rather than writing one:
        # a sixteen-digit number that fails the checksum is not a card.
        guard = Guardrail(rules=[{"entity": "credit_card", "strategy": "redact"}])
        assert guard.screen("ref 1234-5678-9012-3456").text == "ref 1234-5678-9012-3456"
        assert guard.screen(f"ref {CARD}").text == "ref [REDACTED_CREDIT_CARD]"


class TestABlockIsAValue:
    def test_it_does_not_raise(self) -> None:
        guard = Guardrail(rules=[{"entity": "credit_card", "strategy": "block"}])
        screening = guard.screen(f"my card is {CARD}")

        assert screening.blocked
        assert screening.blocked_entity == "credit_card"

    def test_the_blocked_text_is_the_refusal_and_never_the_content(self) -> None:
        guard = Guardrail(rules=[{"entity": "credit_card", "strategy": "block"}])
        screening = guard.screen(f"my card is {CARD}")

        assert CARD not in screening.text
        assert "my card is" not in screening.text

    def test_the_refusal_names_the_category(self) -> None:
        # Ticket 03's trade, decided: naming the category is marginally more
        # informative to a prober and materially more useful to the far more
        # common case — someone who pasted their own card number by habit and
        # needs to know which part to remove.
        guard = Guardrail(rules=[{"entity": "credit_card", "strategy": "block"}])
        assert "credit card number" in guard.screen(CARD).text

    def test_a_developer_may_write_their_own_refusal(self) -> None:
        guard = Guardrail(
            rules=[{"entity": "credit_card", "strategy": "block"}],
            refusal="We never handle card numbers. Call us instead.",
        )
        assert guard.screen(CARD).text == "We never handle card numbers. Call us instead."

    def test_a_block_stops_the_rules_after_it(self) -> None:
        guard = Guardrail(
            rules=[
                {"entity": "credit_card", "strategy": "block"},
                {"entity": "email", "strategy": "redact"},
            ]
        )
        screening = guard.screen(f"{CARD} and {EMAIL}")

        assert screening.blocked
        assert [r.entity for r in screening.redactions] == ["credit_card"]


class TestCustomDetectors:
    """A regex is data. A lambda is not — that is the portability line.

    Ticket 01 asked for this to be decided rather than shipped by accident.
    `workflow.json` is the vendor-neutral layer and CLAUDE.md forbids storing
    host-language code in it. A regex is neither: it is a declarative pattern
    with a published grammar that every plausible target runtime implements,
    exactly as `Reducer` is a name rather than a function. So a string
    pattern is allowed and a callable is not accepted from a document at all.
    """

    def test_a_regex_covers_what_the_library_has_no_detector_for(self) -> None:
        guard = Guardrail(
            rules=[
                {"entity": "phone", "strategy": "redact", "detector": r"\+?\d[\d -]{7,}\d"}
            ]
        )
        assert guard.screen("call +47 123 45 678").text == "call [REDACTED_PHONE]"

    def test_a_custom_entity_without_a_detector_is_refused_readably(self) -> None:
        guard = Guardrail(rules=[{"entity": "passport", "strategy": "redact"}])
        with pytest.raises(ValueError, match="passport"):
            guard.screen("anything")


class TestTheTableIsRead:
    def test_an_unknown_strategy_is_refused_rather_than_ignored(self) -> None:
        # Silently skipping a misspelled strategy is a guardrail that is not
        # there while the card says it is.
        with pytest.raises(ValueError, match="obfuscate"):
            Guardrail(rules=[{"entity": "email", "strategy": "obfuscate"}]).screen("x")

    def test_an_empty_table_is_a_pass_through_not_a_failure(self) -> None:
        assert Guardrail(rules=[]).screen(f"{EMAIL} {CARD}").text == f"{EMAIL} {CARD}"

    def test_a_blank_entity_row_is_ignored_so_a_half_filled_card_still_runs(self) -> None:
        guard = Guardrail(rules=[{"entity": "", "strategy": "redact"}, GuardrailRule("email")])
        assert guard.screen(EMAIL).text == "[REDACTED_EMAIL]"

    def test_rules_apply_in_declaration_order(self) -> None:
        guard = Guardrail(
            rules=[GuardrailRule("email", "redact"), GuardrailRule("credit_card", "mask")]
        )
        screening = guard.screen(f"{EMAIL} {CARD}")
        assert screening.text == "[REDACTED_EMAIL] ****-****-****-5100"
        assert [r.entity for r in screening.redactions] == ["email", "credit_card"]


class TestTheLadder:
    def test_the_base_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            BaseGuardrail(rules=[])  # type: ignore[abstract]

    def test_a_subclass_supplies_only_the_refusal_copy(self) -> None:
        class Terse(BaseGuardrail):
            def refusal_for(self, entity: str) -> str:
                return "no"

        assert Terse(rules=[GuardrailRule("email", "block")]).screen(EMAIL).text == "no"

    def test_screening_an_empty_string_is_a_no_op(self) -> None:
        assert Guardrail(rules=[GuardrailRule("email", "block")]).screen("") == Screening(text="")
