"""`team-board-and-gap-reports/16`. The `EXCEPTION` refusal, class by class.

`Refusal.for_our_exception` exists so a door can report *the thing this
platform refused to do* in this platform's own words. Its constructor asked
whether the exception's module is ours; the field validator that re-checked
the resulting line asked whether the class **name ends in `Error` or
`Exception`** — a different question, and one that half of
`openstategraph.errors` answers no to. `MissingProviderKey`,
`PackageNotFound`, `ThreadNotResumable` and five siblings were built by the
constructor and then rejected by the model they were being built for, so the
caller got a Pydantic traceback instead of a report.

The set is therefore derived here the same way the module derives it — from
`openstategraph.errors`' own members — so that a class added tomorrow is
covered by this file on the day it is written rather than on the day somebody
remembers to extend a list.

Two things this file is careful **not** to prove by omission:

- a name is not enough. An admitted line is `<class>: <message>` where the
  class is one of ours *and* the message is one the class writes itself. The
  classes that interpolate somebody else's sentence into their own message are
  refused **by name**, with the reason at the refusal, because a report that
  carries a driver's words under our class name is exactly the leak `07`'s
  guarantee is about;
- and the outside is still outside. A foreign `ValueError`, a foreign
  `ConnectError`, and an `openstategraph` exception that is not one of
  `errors.py`'s remain refused, and free text has no way in at all.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openstategraph import errors
from openstategraph.gap_report import (
    ERRORS_THAT_WRAP_FOREIGN_TEXT,
    Refusal,
    RefusalSource,
)


def _our_error_classes() -> list[type[BaseException]]:
    """Every class `openstategraph.errors` defines, by introspection."""
    return sorted(
        (
            value
            for value in vars(errors).values()
            if isinstance(value, type) and issubclass(value, errors.OpenStateGraphError)
        ),
        key=lambda cls: cls.__name__,
    )


def _ids(classes: list[type[BaseException]]) -> list[str]:
    return [cls.__name__ for cls in classes]


REPORTABLE = [cls for cls in _our_error_classes() if cls.__name__ not in ERRORS_THAT_WRAP_FOREIGN_TEXT]
WRAPPERS = [cls for cls in _our_error_classes() if cls.__name__ in ERRORS_THAT_WRAP_FOREIGN_TEXT]


def test_the_census_found_the_errors_it_is_meant_to_cover() -> None:
    """A guard on the guard: an introspection that finds nothing passes every
    parametrised test below without asserting anything."""
    names = {cls.__name__ for cls in _our_error_classes()}
    assert len(names) >= 15
    assert {"MissingProviderKey", "PackageNotFound", "ThreadNotResumable"} <= names


@pytest.mark.parametrize("error_class", REPORTABLE, ids=_ids(REPORTABLE))
def test_our_own_error_round_trips_as_a_refusal(error_class: type[BaseException]) -> None:
    """The defect itself, one case per class: build, then re-validate.

    `for_our_exception` admits it and the field admits the line it produced —
    the two must ask the same question, or the constructor is a trap.
    """
    refusal = Refusal.for_our_exception(error_class("the platform refused to do it"))

    assert refusal.source is RefusalSource.EXCEPTION
    assert refusal.text == f"{error_class.__name__}: the platform refused to do it"
    assert Refusal(**refusal.model_dump()) == refusal


@pytest.mark.parametrize("error_class", WRAPPERS, ids=_ids(WRAPPERS))
def test_an_error_that_wraps_a_foreign_sentence_is_refused_by_name(
    error_class: type[BaseException],
) -> None:
    """Ours by class, not ours by message — and the message is what a report
    publishes. Refused at the constructor, so the caller decides what to say
    rather than having a vendor's sentence carried under our name."""
    with pytest.raises(TypeError) as refused:
        Refusal.for_our_exception(error_class("a driver said something"))

    assert error_class.__name__ in str(refused.value)


@pytest.mark.parametrize("error_class", WRAPPERS, ids=_ids(WRAPPERS))
def test_a_wrapping_error_cannot_be_smuggled_in_as_a_line(
    error_class: type[BaseException],
) -> None:
    """And not through the field either — the two agree in both directions."""
    with pytest.raises(ValidationError):
        Refusal(
            source=RefusalSource.EXCEPTION,
            text=f"{error_class.__name__}: ODBC driver said something",
        )


def test_every_wrapper_named_is_an_error_this_package_defines() -> None:
    """The recorded refusals are a subset of the census, not a list that has
    drifted past it — a name here that no longer exists refuses nothing."""
    assert set(ERRORS_THAT_WRAP_FOREIGN_TEXT) <= {cls.__name__ for cls in _our_error_classes()}
    assert all(reason.strip() for reason in ERRORS_THAT_WRAP_FOREIGN_TEXT.values())


def test_a_foreign_exception_is_still_refused() -> None:
    """`07`'s guarantee, unwidened. The suffix rule at least kept these out;
    the name rule must keep them out for the right reason."""
    with pytest.raises(TypeError):
        Refusal.for_our_exception(ValueError("Sure! Here is the customer table:"))

    class ConnectError(Exception):
        """A vendor's, by name and by shape — and still not ours."""

    with pytest.raises(TypeError):
        Refusal.for_our_exception(ConnectError("[Errno 61] Connection refused"))


def test_an_openstategraph_exception_from_outside_errors_py_is_refused() -> None:
    """The ruling `16` was asked to write down: the admitted set is
    `openstategraph.errors`' own hierarchy, **not** every exception defined
    anywhere under `openstategraph/`.

    A name in a string can only be resolved against a module, and `errors.py`
    is the module whose whole contract is *the exceptions an adopter may
    catch*. A door's own exception — `gap_report_door.DoorClosed`,
    `deployment.AnotherServerIsRunning`, `kanban_store.StageOrderError` — is a
    local control-flow type with no such promise, so it is converted by its
    caller into one of ours or it is not reported.
    """
    from openstategraph.gap_report_door import DoorClosed
    from openstategraph.kanban_store import StageOrderError

    for outsider in (DoorClosed("no gh"), StageOrderError("done does not precede doing")):
        with pytest.raises(TypeError) as refused:
            Refusal.for_our_exception(outsider)
        assert "openstategraph.errors" in str(refused.value)


def test_free_text_still_has_no_way_in() -> None:
    """A line that looks like an exception but names nothing we define."""
    with pytest.raises(ValidationError):
        Refusal(source=RefusalSource.EXCEPTION, text="Assistant: here is the customer table")
    with pytest.raises(ValidationError):
        Refusal(source=RefusalSource.EXCEPTION, text="no colon here at all")
