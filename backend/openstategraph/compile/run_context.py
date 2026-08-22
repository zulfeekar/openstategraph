"""What a workflow declares its runs carry — the declaration, and only that.

`organisms-first-class/67`, step 1 of the seven in
`docs/decisions/runtime-context.md`. A run carries three kinds of data and this
platform had a home for two: **graph state**, which flows between nodes and is
drawn on the canvas, and **environment**, which is identical for every run on
the process. Between them sits a third — per-run and static for the whole run:
which tenant, which case id, a caller-supplied locale, a refund ceiling. Those
values used to be smuggled into the question, where a model can argue with
them, or into an environment variable, where they are the same for everybody.

This module is where a document *says* what it wants. Nothing here mints a
schema (69), supplies a value (70) or reads one (71). A declaration that
compiles to nothing is the correct end state for this ticket: a workflow that
declares run context today behaves exactly as it did yesterday, and a workflow
that declares none pays nothing for the feature existing.

## Why it is a list of JSON descriptors and not a type

Portability guardrail 4 is the hard one here, because LangGraph's channel *is*
a Python class and the entire point of the feature is to let a document
describe one. It is resolved by never storing the type. `workflow.json` holds a
list of field descriptors — a key, a named type drawn from a three-value enum,
a label, a scalar default — with no import path, no class name and nothing to
resolve at load time. A document declaring run context is readable by a runtime
that has never heard of LangGraph, and `core/` sees descriptors and nothing
else.

**A list, not an object map**, because order is the substance: it is the order
the generated prompt section will render in and the order the inspector will
list. JSON object key order is not a contract. Port descriptors are a list for
the same reason.

**Three types and no more.** Not `object` and not `array`: a nested value
cannot be rendered into a prompt section honestly, cannot be typed on a CLI
flag without inventing a parser, and inventing that parser is guardrail 1
asking to be broken. A workflow needing structure passes a string and parses it
in a tool it owns.

**A default is a scalar, absent means unset, and `required` defaults to
false.** There is no sentinel and no non-finite number anywhere in this block —
`Infinity` and `NaN` are not representable in JSON, so a value that could not
survive its own round trip is refused at the point it is written rather than
lost silently later. `maxConnections` is the worked example the rule was
written from.

## Why a refusal, and on which channel

The library validates nothing usable. Measured against langgraph 1.2.10 in
`tests/test_runtime_context_facts.py`: a dataclass schema refuses an undeclared
key by raising `TypeError` naming a class the author never wrote and cannot
see; a TypedDict schema refuses nothing at all; **neither checks a value's
type**; and a run supplying no context is not refused at the door but fails as
an `AttributeError` inside whichever node touched it first. So every check
worth having is ours, and the first of them is on the declaration itself —
before any value exists to check against it.

The problems go on `plan.warnings`, which is the compiler's own channel and the
one `ValidateWorkflowTool` turns into PROBLEMS FOUND and `openstategraph
validate` turns into exit 1. That is the right class: `validate`'s single
question is *is this ready to run here*, and a document declaring a field of a
type nothing can supply is not. It is deliberately not a `Finding` — those name
a capability a compiled graph lost, and this is a malformed document, the same
kind of thing as `plan`'s own "dropped an edge with an unknown endpoint".
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openstategraph.errors import DocumentError
from openstategraph.run_identity import RUN_IDENTITY_KEYS

#: Where a document declares it — a sibling of `model` and `recursionLimit`.
#: `document.setSetting(key, value)` is already generic in the key, so nothing
#: new is needed on the editor side to write it.
RUN_CONTEXT_SETTING = "context"

#: The named type enum. Three values, for the reason in the module docstring.
RUN_CONTEXT_TYPES: tuple[str, ...] = ("string", "number", "boolean")

#: Keys a declaration may not name, read from the one place they are listed.
#:
#: **`configurable` is who the run is *for*; `context` is what the workflow
#: asked its caller for.** `thread_id`, `session_id`, `user_email` and
#: `workflow_slug` are server-determined and unforgeable — `RunRequest`
#: deliberately has no `user_email` field, because that value keys a per-person
#: memory namespace and a client that could name the person could read that
#: person's memories (memory ticket 01). `settings.context` is the opposite by
#: construction: the author declares it and the caller fills it. A key that
#: existed on both channels would hand back exactly what that ticket took away,
#: and would be two spellings of one fact besides.
RESERVED_CONTEXT_KEYS: tuple[str, ...] = RUN_IDENTITY_KEYS


def _fold(key: str) -> str:
    """A key reduced to what casing and punctuation cannot disguise.

    `threadId`, `THREAD_ID` and `Thread-Id` are the same claim on the same
    channel; a refusal that only knew one spelling would be advice rather than
    a rule.
    """
    return "".join(character for character in key.lower() if character.isalnum())


_RESERVED_FOLDED = {_fold(key): key for key in RESERVED_CONTEXT_KEYS}

_PYTHON_TYPE: dict[str, tuple[type, ...]] = {
    # `bool` first and excluded from `number` on purpose: in Python `True` is
    # an `int`, and a boolean default silently satisfying a numeric field is
    # the kind of accepted-and-wrong this whole module exists to prevent.
    "string": (str,),
    "number": (int, float),
    "boolean": (bool,),
}


class ContextField(BaseModel):
    """One declared field. JSON in, JSON out, nothing host-language."""

    model_config = ConfigDict(extra="forbid")

    key: str
    type: Literal["string", "number", "boolean"]
    label: str = ""
    description: str = ""
    required: bool = False
    #: Absent means unset. There is no sentinel, and never a non-finite number.
    default: str | float | bool | None = None


def _problems_for(index: int, raw: Any) -> list[str]:
    position = index + 1
    if not isinstance(raw, dict):
        return [f"Run context field at position {position} is not an object: {raw!r}."]

    key = raw.get("key")
    if not isinstance(key, str) or not key.strip():
        return [f"Run context field at position {position} declares no 'key'."]

    problems: list[str] = []
    declared = raw.get("type")
    if declared not in RUN_CONTEXT_TYPES:
        allowed = ", ".join(RUN_CONTEXT_TYPES)
        problems.append(
            f"Run context field '{key}' declares an unknown type {declared!r} — "
            f"use one of: {allowed}."
        )

    unknown = sorted(set(raw) - set(ContextField.model_fields))
    if unknown:
        listed = ", ".join(repr(name) for name in unknown)
        problems.append(f"Run context field '{key}' declares unknown properties: {listed}.")

    reserved = _RESERVED_FOLDED.get(_fold(key))
    if reserved is not None:
        named = ", ".join(RESERVED_CONTEXT_KEYS)
        problems.append(
            f"Run context field '{key}' names the reserved run identity key "
            f"'{reserved}' — {named} are supplied by the server on every run and "
            "cannot be declared or filled by a caller."
        )

    if "default" in raw:
        default = raw["default"]
        if isinstance(default, float) and not math.isfinite(default):
            problems.append(
                f"Run context field '{key}' has a default that is not a finite number — "
                "Infinity and NaN cannot survive a JSON round trip; omit the default instead."
            )
        elif declared in RUN_CONTEXT_TYPES:
            expected = _PYTHON_TYPE[str(declared)]
            wrong = isinstance(default, bool) and declared == "number"
            if wrong or not isinstance(default, expected):
                problems.append(
                    f"Run context field '{key}' declares type {declared!r} and a default "
                    f"of type {type(default).__name__}."
                )

    if "required" in raw and not isinstance(raw["required"], bool):
        problems.append(f"Run context field '{key}' declares a non-boolean 'required'.")

    return problems


def context_declaration_problems(document: Any) -> list[str]:
    """Everything wrong with a document's run-context declaration, in order.

    Empty for a document that declares none, and empty for one that declares an
    empty list. The two are the same claim — *this workflow asks its caller for
    nothing* — and the empty list is preserved rather than helpfully dropped,
    because a serializer that rewrites a file nobody edited is the loss this
    repository has paid for twice.
    """
    settings = (document or {}).get("settings") if isinstance(document, dict) else None
    if not isinstance(settings, dict) or RUN_CONTEXT_SETTING not in settings:
        return []

    declared = settings[RUN_CONTEXT_SETTING]
    if declared is None:
        return []
    if not isinstance(declared, list):
        return [
            "Run context must be a list of field descriptors — order is the rendering "
            f"contract, and JSON object key order is not — but this document declares a "
            f"{type(declared).__name__}."
        ]

    problems: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(declared):
        problems.extend(_problems_for(index, raw))
        if isinstance(raw, dict) and isinstance(raw.get("key"), str):
            key = raw["key"]
            if key in seen:
                problems.append(
                    f"Run context declares '{key}' more than once — each key may appear only once."
                )
            seen.add(key)
    return problems


def context_declaration(document: Any) -> tuple[ContextField, ...]:
    """A document's declared fields, in document order, or raise.

    The strict door, for a caller that is about to depend on the answer.
    `context_declaration_problems` is the tolerant one, for the compiler, which
    reports everything wrong rather than stopping at the first thing.
    """
    problems = context_declaration_problems(document)
    if problems:
        raise DocumentError(" ".join(problems))
    settings = (document or {}).get("settings") if isinstance(document, dict) else None
    declared = (settings or {}).get(RUN_CONTEXT_SETTING) or []
    return tuple(ContextField.model_validate(raw) for raw in declared)
