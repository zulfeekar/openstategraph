"""One carrier, two notes: `launch-readiness/117` and `launch-readiness/127`.

Both tickets ask for the same thing in different words — **the tool, holding
the result, states a structured fact about the call it just made** — and both
were handed over together with the instruction to check whether one mechanism
serves both before building two. It does, and the argument is in
`openstategraph/abc/tool_notes.py`.

What is pinned here:

- the carrier is **additive**: a tool that says nothing behaves exactly as it
  did before `notes` existed (`BaseTool` is Tier 1, 26 in-tree implementations
  plus one in every adopter's `tools/*.py`);
- a corrective reaches the model **with the data**, in the same
  `ToolMessage`, rather than as a rule issued earlier and hoped for;
- a substitution is a **recorded fact**, not prose the model is asked to
  remember, and a substitution `how_matched="model_inference"` can never
  render without saying so;
- **silence by default** — the failure mode both tickets name is a field that
  fires on every call and becomes noise the model learns to skip.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openstategraph.abc import BaseTool, NoArgs, ToolResult
from openstategraph.abc.tool_notes import (
    Correction,
    Substitution,
    notes_for_model,
    notes_for_reader,
    record_notes,
    take_notes,
)


class Silent(BaseTool):
    name = "silent"
    description = "says nothing"
    Args = NoArgs
    side_effecting = False

    def _execute(self, args):  # noqa: ANN001, ANN201
        return ToolResult(content="two rows")


class Corrective(BaseTool):
    name = "corrective"
    description = "returns nothing, and says what that means"
    Args = NoArgs
    side_effecting = False

    def _execute(self, args):  # noqa: ANN001, ANN201
        return ToolResult(
            content="0 rows",
            notes=(
                Correction(
                    text=(
                        "Zero matches on this join; the dark table keys on IMO and "
                        "`imo = 0` is a real value here, so confirm before reporting "
                        "an absence."
                    )
                ),
            ),
        )


# --- the carrier is additive ------------------------------------------------


def test_a_tool_that_says_nothing_carries_no_notes() -> None:
    """The whole of the Tier-1 promise: silence costs an adopter nothing."""
    result = Silent().run()
    assert result.ok
    assert result.content == "two rows"
    assert result.notes == ()


def test_a_silent_tool_hands_the_model_exactly_its_content() -> None:
    lc = Silent().as_langchain_tool()
    assert lc.func() == "two rows"


def test_notes_survive_a_json_round_trip() -> None:
    """`ToolResult` crosses a wire; a note that could not be rebuilt from its
    own dump would be a fact only the process that made it can read."""
    original = ToolResult(
        content="x",
        notes=(
            Correction(text="widen the window"),
            Substitution(
                user_term="persian gulf",
                axis="shipping_region_v2",
                canonical_value="Middle East Gulf (MEG)",
                how_matched="declared_synonym",
            ),
        ),
    )
    rebuilt = ToolResult.model_validate_json(original.model_dump_json())
    assert rebuilt.notes == original.notes
    assert isinstance(rebuilt.notes[0], Correction)
    assert isinstance(rebuilt.notes[1], Substitution)


# --- 117: the corrective arrives with the data ------------------------------


def test_a_corrective_reaches_the_model_in_the_same_message() -> None:
    text = Corrective().as_langchain_tool().func()
    assert text.startswith("0 rows")
    assert "confirm before reporting an absence" in text


@pytest.mark.asyncio
async def test_the_async_door_carries_the_corrective_too() -> None:
    text = await Corrective().as_langchain_tool().coroutine()
    assert "confirm before reporting an absence" in text


def test_a_corrective_does_not_reach_the_reader() -> None:
    """A `next_step` is addressed to the model. Rendering it to a person would
    be the scratchpad leak `abc/narration.py` closed."""
    assert notes_for_reader((Correction(text="widen the window"),)) == ""


def test_nothing_is_appended_when_there_is_nothing_to_say() -> None:
    assert notes_for_model(()) == ""
    assert notes_for_reader(()) == ""


# --- 127: a substitution is a recorded fact ---------------------------------


def _meg(how_matched: str = "declared_synonym") -> Substitution:
    return Substitution(
        user_term="persian gulf",
        axis="shipping_region_v2",
        canonical_value="Middle East Gulf (MEG)",
        how_matched=how_matched,  # type: ignore[arg-type]
    )


def test_how_matched_has_no_default() -> None:
    """The honest field cannot be omitted. A substitution whose epistemic
    state is unstated is the one shape this must not be able to record."""
    with pytest.raises(ValidationError):
        Substitution(
            user_term="persian gulf",
            axis="shipping_region_v2",
            canonical_value="Middle East Gulf (MEG)",
        )


def test_an_invented_how_matched_is_refused() -> None:
    with pytest.raises(ValidationError):
        _meg("vibes")


def test_confidence_cannot_be_non_finite() -> None:
    with pytest.raises(ValidationError):
        Substitution(
            user_term="a",
            axis="b",
            canonical_value="c",
            how_matched="exact",
            confidence=float("inf"),
        )


def test_a_substitution_renders_the_user_word_and_the_canonical_one() -> None:
    text = notes_for_reader((_meg(),))
    assert "persian gulf" in text
    assert "Middle East Gulf (MEG)" in text
    assert "shipping_region_v2" in text


def test_a_model_inferred_substitution_can_never_render_silently() -> None:
    text = notes_for_reader((_meg("model_inference"),))
    assert "persian gulf" in text
    assert "model" in text.lower()
    assert "not" in text.lower()


def test_a_declared_synonym_says_it_was_declared_and_a_model_guess_does_not() -> None:
    declared = notes_for_reader((_meg("declared_synonym"),))
    inferred = notes_for_reader((_meg("model_inference"),))
    assert declared != inferred
    assert "declares" in declared.lower()
    assert "declares" not in inferred.lower()


def test_a_value_that_did_not_change_renders_nothing() -> None:
    """Silence by default. A disclosure on every answer trains a reader to
    skip disclosures, which is the failure mode both tickets name."""
    same = Substitution(
        user_term="Middle East Gulf (MEG)",
        axis="shipping_region_v2",
        canonical_value="Middle East Gulf (MEG)",
        how_matched="exact",
    )
    assert notes_for_reader((same,)) == ""


def test_a_difference_of_case_alone_is_not_a_substitution() -> None:
    cased = Substitution(
        user_term="middle east gulf (meg)",
        axis="shipping_region_v2",
        canonical_value="Middle East Gulf (MEG)",
        how_matched="exact",
    )
    assert notes_for_reader((cased,)) == ""


def test_a_substitution_also_reaches_the_model() -> None:
    """The reader's disclosure is the enforcement; the model still needs to
    know it is not answering on the word it was given."""
    text = notes_for_model((_meg(),))
    assert "persian gulf" in text
    assert "Middle East Gulf (MEG)" in text


# --- the run rail: recorded by the run, not recounted by the model ----------


def test_what_a_tool_records_is_readable_once_and_then_gone() -> None:
    thread = "test-thread-a"
    take_notes(thread)  # start clean
    record_notes((_meg(),), thread_id=thread)
    first = take_notes(thread)
    assert len(first) == 1
    assert take_notes(thread) == ()


def test_two_threads_never_see_each_others_substitutions() -> None:
    take_notes("t1")
    take_notes("t2")
    record_notes((_meg(),), thread_id="t1")
    assert take_notes("t2") == ()
    assert len(take_notes("t1")) == 1


def test_a_tool_run_inside_a_run_records_what_it_substituted(monkeypatch) -> None:
    """The property `127` asks for: the *run* records the substitution, so a
    model that never mentions it cannot suppress it."""
    from openstategraph.abc import tool_notes

    thread = "test-thread-ambient"
    take_notes(thread)
    monkeypatch.setattr(tool_notes, "_current_thread", lambda: thread)

    class Resolver(BaseTool):
        name = "resolver"
        description = "resolves a word"
        Args = NoArgs
        side_effecting = False

        def _execute(self, args):  # noqa: ANN001, ANN201
            return ToolResult(content="68 ports", notes=(_meg(),))

    Resolver().run()
    recorded = take_notes(thread)
    assert len(recorded) == 1
    assert recorded[0].canonical_value == "Middle East Gulf (MEG)"


def test_recording_outside_a_run_is_a_no_op_not_a_failure() -> None:
    """A package's own `tests/` and a script call tools directly. A note that
    detonated a unit test would make CLAUDE.md's claim for `tools/` false."""
    assert Corrective().run().ok is True
    assert record_notes((_meg(),)) is False
