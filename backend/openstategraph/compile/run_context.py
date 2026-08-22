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

import dataclasses
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openstategraph.errors import DocumentError, RunContextError
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


# --------------------------------------------------------------------------- #
# The mint — organisms-first-class/69, step 3 of the seven.
# --------------------------------------------------------------------------- #

#: What the minted class is *called*, and it is the whole of what we control.
#:
#: Measured against langgraph 1.2.10: when a caller supplies a key the schema
#: does not declare, the failure is a raw
#: `TypeError: RunContext.__init__() got an unexpected keyword argument 'zzz'`.
#: The `.__init__()` half is generated by `dataclasses` and cannot be replaced
#: — assigning `__qualname__` after the fact does not touch it, because the
#: generated `__init__` baked its own name in at class-creation time. The
#: *first* half is ours, so it is the lexicon word a workflow author has
#: actually read (`docs/decisions/runtime-context.md`, "Run context") rather
#: than a two-letter stand-in from a test file.
#:
#: A non-identifier name (`"the run context this workflow declared"`) does
#: render in that message and was tried; it was rejected because the class is a
#: real Python type that a `repr`, a traceback and `Runtime[...]` will all
#: print, and a type whose name is a sentence lies about what it is everywhere
#: except the one message. **The message is not the fix** — ticket 70 puts our
#: own validator at the door, naming the key and the workflow, so this
#: `TypeError` becomes the second line of defence it was always meant to be.
CONTEXT_SCHEMA_NAME = "RunContext"

_ANNOTATION: dict[str, Any] = {"string": str, "number": float, "boolean": bool}

#: A key that can become a field name. Deliberately ASCII and deliberately
#: narrower than `str.isidentifier()`: this key is also going to be a CLI flag
#: (`--context tenant=acme`), a prompt variable and a JSON object key, so the
#: portable answer is a plain word rather than whatever one host language
#: happens to accept.
_MINTABLE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def unmintable_context_keys(fields: Sequence[ContextField]) -> list[str]:
    """Declared keys that cannot become a field name, in declaration order."""
    return [f.key for f in fields if not _MINTABLE_KEY.match(f.key)]


def _sealed_schema() -> type:
    """A context schema with no fields — *this document declares nothing*.

    Distinct from `None`, which means *pass no argument*, and the difference is
    the whole of `organisms-first-class/76`: only a graph that declares a schema
    gets one of its own, and only a graph with one of its own is isolated from
    its caller's.
    """
    return dataclasses.make_dataclass(CONTEXT_SCHEMA_NAME, [], kw_only=True)


def mint_context_schema(document: Any, *, sealed: bool = False) -> type | None:
    """The declaration as a `dataclass`, or `None` when there is nothing to mint.

    **A build artefact, minted here and discarded with the build.** Nothing
    reads it back: the compile seam is one-directional, `workflow.json` holds
    JSON field descriptors and never a Python type, and `core/` never sees this
    function's return value at all. That is how portability guardrail 4
    survives a feature whose entire purpose is to let a document describe a
    Python class.

    A **dataclass** and not a `TypedDict`, and the choice is load-bearing
    rather than stylistic. Measured in `tests/test_runtime_context_facts.py`
    against langgraph 1.2.10: a dataclass schema is *constructed* from the
    mapping the caller passed, so an undeclared key and a missing required key
    are both refused; a TypedDict schema is never constructed and refuses
    nothing at all. Neither checks a value's *type*, which is why ticket 70's
    validator exists regardless.

    `None` — meaning *pass no argument at all* — for a document that declares
    nothing, for one that declares an empty list (the same claim, and 67
    preserves the distinction in the file without inventing one here), and for
    a malformed declaration, whose problems `context_declaration_problems`
    already put on `plan.warnings`. A document without the key must compile
    exactly as it did before this ticket, and `None` and absent are not
    guaranteed to be the same thing to a library we do not own.

    Every field is **keyword-only**, which is what lets declaration order be
    the order of `dataclasses.fields()` regardless of which fields carry
    defaults. Without it a document that declares an optional field before a
    required one would raise `non-default argument follows default argument`
    at build — the author's order silently becoming a build failure, when
    order is the substance of this list (it is the order the generated prompt
    section renders in).

    `sealed` is the mount boundary's argument, and it changes only what
    *nothing to mint* means (`organisms-first-class/76`). A graph compiled with
    no `context_schema` at all does not merely see an empty context: measured
    against langgraph 1.2.10, it sees **whatever the caller's runtime carried**,
    and no argument to `invoke` can take that away — `context=None`, `context={}`
    and passing nothing are all the same to a schema-less graph. A mounted child
    is compiled by `NodeRuntime._subgraph` with `sealed=True`, so a document that
    declares nothing is given an **empty** schema and reads an empty context
    instead of its caller's. A workflow run directly is never sealed: it has no
    caller whose values could leak into it, and 69's promise that a document
    declaring nothing builds exactly the graph it built before is kept where it
    was made.
    """
    if context_declaration_problems(document):
        return _sealed_schema() if sealed else None
    fields = context_declaration(document)
    if not fields or unmintable_context_keys(fields):
        return _sealed_schema() if sealed else None

    specs: list[tuple[str, Any, Any]] = []
    for declared in fields:
        annotation = _ANNOTATION[declared.type]
        # Required means *required of the caller*, so a field carrying a
        # default is not required however it was flagged: the caller may omit
        # it and get the value the author wrote down.
        if declared.required and declared.default is None:
            specs.append((declared.key, annotation, dataclasses.field()))
        else:
            specs.append(
                (
                    declared.key,
                    annotation | None,
                    dataclasses.field(default=declared.default),
                )
            )
    return dataclasses.make_dataclass(CONTEXT_SCHEMA_NAME, specs, kw_only=True)


# --------------------------------------------------------------------------- #
# The door — organisms-first-class/70, step 4 of the seven.
#
# Three supply routes and **one** validator, ours. The library's is unusable
# and the measurement is in `tests/test_runtime_context_facts.py`: an
# undeclared key and a missing required one are refused only as
# `TypeError: RunContext.__init__() got an unexpected keyword argument 'zzz'`,
# from a `dataclasses`-generated `__init__` naming a class the workflow author
# never wrote; **no schema checks a value's type at all**, so `{"tenant": 123}`
# against `tenant: string` is delivered as an `int`; and a run supplying
# nothing is not refused at the door but fails as an `AttributeError` inside
# whichever node touched `runtime.context` first, naming neither the key nor
# the run.
#
# So every sentence below names the **key** and the **workflow**, and every one
# of them is raised *before* `invoke`. The minted dataclass stays exactly where
# 69 put it and keeps doing exactly what it did — it is the second line of
# defence now rather than the only one.
# --------------------------------------------------------------------------- #

#: What a supplied value is called, in the words the declaration uses.
_SUPPLIED_TYPE: dict[type, str] = {bool: "boolean", int: "number", float: "number", str: "string"}


def workflow_label(document: Any, slug: str | None = None) -> str:
    """What a refusal calls the workflow it is speaking for.

    The slug first — it is the identity, it is what `?w=` and a mount field
    carry, and it is the one name that addresses the package on disk. A
    document that has no slug (a canvas the editor has not saved, which is
    exactly what `POST /api/runs` posts) falls back to its display name, and a
    document with neither says *this workflow*, because a refusal that names an
    empty string is worse than one that names nothing.
    """
    if slug:
        return str(slug)
    name = (document or {}).get("name") if isinstance(document, dict) else None
    return str(name).strip() if isinstance(name, str) and name.strip() else "this workflow"


def _supplied_type_name(value: Any) -> str:
    if value is None:
        return "null"
    # `bool` before `int`: in Python `True` is an `int`, and a boolean reported
    # as a number is the accepted-and-wrong this module exists to prevent.
    for python_type in (bool, str, int, float):
        if isinstance(value, python_type):
            return _SUPPLIED_TYPE[python_type]
    return type(value).__name__


def _accepts(declared: str, value: Any) -> bool:
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


def validate_run_context(
    document: Any,
    supplied: Mapping[str, Any] | None,
    *,
    slug: str | None = None,
) -> dict[str, Any] | None:
    """The run's context, checked against the document's own declaration.

    Returns the mapping to hand `invoke(context=…)`, or `None` meaning **pass
    no argument at all** — for a workflow that declares nothing and a run that
    supplies nothing, which is every run this platform has ever made and must
    keep behaving exactly as it did. `None` and absent are not guaranteed to be
    the same thing to a library we do not own, so the distinction is kept here
    rather than flattened.

    Raises `RunContextError` naming the key and the workflow. It refuses, in
    this order, so that a caller who got several things wrong learns the most
    structural one first:

    - a run that supplied **nothing** where something was required;
    - an **undeclared** key;
    - a **missing required** key;
    - a value of the **wrong declared type**, including a `number` that is not
      finite — `Infinity` and `NaN` are not representable in JSON, so a value
      that could not survive its own round trip is refused where it is written
      rather than lost silently later.

    Defaults are **not** filled in here. The minted dataclass carries them
    (69), which is the one place they live; copying them into the mapping would
    be a second spelling of the author's intent, and the two would drift.

    A malformed *declaration* is not this function's business: it is already a
    `plan.warnings` problem (67) and already exits `validate` non-zero, and 69
    mints no schema from one. A run against such a document is validated
    against nothing and passes through, exactly as it compiles.
    """
    workflow = workflow_label(document, slug)
    values = dict(supplied or {})

    if context_declaration_problems(document):
        return values or None
    declared = context_declaration(document)
    by_key = {field.key: field for field in declared}
    # `required` yields to a default, as 69 decided: a field the caller must
    # always name even though an answer already exists makes that answer
    # unreachable.
    required = [f.key for f in declared if f.required and f.default is None]

    if not values:
        if required:
            raise RunContextError(
                f"Workflow {workflow!r} requires run context that this run supplied none of: "
                f"{', '.join(required)}."
            )
        return None if not declared else (values or None)

    for key in values:
        if key in by_key:
            continue
        names = ", ".join(field.key for field in declared)
        asked = f"It asks for: {names}." if names else "It asks its callers for no run context."
        raise RunContextError(
            f"Run context key {key!r} is not declared by workflow {workflow!r}. {asked}"
        )

    for key in required:
        if key not in values:
            raise RunContextError(
                f"Run context key {key!r} is required by workflow {workflow!r}, "
                "and this run supplied no value for it."
            )

    for key, value in values.items():
        field = by_key[key]
        if field.type == "number" and isinstance(value, float) and not math.isfinite(value):
            raise RunContextError(
                f"Run context key {key!r} is declared 'number' by workflow {workflow!r}, and "
                "this run supplied a value that is not a finite number — Infinity and NaN "
                "cannot survive a JSON round trip."
            )
        if not _accepts(field.type, value):
            raise RunContextError(
                f"Run context key {key!r} is declared {field.type!r} by workflow "
                f"{workflow!r}, and this run supplied a {_supplied_type_name(value)}."
            )
    return values


def mount_run_context(
    child_document: Any,
    parent_context: Mapping[str, Any],
    *,
    slug: str | None = None,
) -> dict[str, Any]:
    """What a mounted child is invoked with — **inherit, then narrow**.

    `organisms-first-class/76`. A mount is a closure over the child's
    `invoke()`, so until this function existed LangGraph carried the parent's
    runtime down it whole: a child read fields it never declared, and the
    fields it *did* declare never materialised because its own schema was never
    constructed. Both are the failure this chain exists to remove.

    The rule is `582e098`'s rule for the step budget, pointed at a different
    channel: **the run supplies, the child's own document decides**. A key
    crosses a mount only when *both* documents declare it; the child's own
    defaults fill everything else, minted from its own declaration by
    `mint_context_schema` exactly as they would be for a direct run.

    Two shapes were rejected:

    - **Inherit whole**, today's behaviour made deliberate. It cannot be: a
      package would read a caller's field it never asked for, which is the
      thing 70 put a validator at the door to stop, and a package's answer
      would depend on which parent happened to declare a key of the same name.
    - **Isolate completely** — the child gets its own declaration and nothing
      else, and the parent supplies the rest through a new per-mount field.
      Honest, and it is the shape a package needing a value its caller does not
      itself declare will eventually need; it is `organisms-first-class/78`,
      filed rather than invented here, because it is a **new serialised field
      on the mount** and changing what a saved document carries is not a thing
      to do on the way past. Narrowing is the half that needs no new field and
      closes both leaks today.

    What it deliberately does **not** do is fill defaults itself. The minted
    dataclass carries them and is the one place they live — the same sentence
    `validate_run_context` makes about the supply doors, for the same reason.

    Raises `RunContextError`, in our words and naming the child, when the run
    cannot honour what the child declared: a required key neither document
    could supply a value for, or a value the parent typed differently. A
    declared field that arrived silently `None` is what this ticket refused.
    """
    declared = context_declaration(child_document)
    if context_declaration_problems(child_document) or not declared:
        # Nothing well-formed to narrow *to*, so nothing crosses. The child is
        # still sealed by `mint_context_schema(sealed=True)`, which is what
        # makes an empty mapping mean an empty context rather than the
        # caller's.
        return {}
    narrowed = {field.key: parent_context[field.key] for field in declared if field.key in parent_context}
    return validate_run_context(child_document, narrowed, slug=slug) or {}


#: What `--context flag=value` accepts for a `boolean` field, and nothing else.
#:
#: Deliberately not `1`/`0`, `yes`/`no`, `on`/`off`, and emphatically not
#: Python's own truthiness, under which the string `"false"` is `True`.
#: `CLAUDE.md`'s law is *never promise what is not possible*, and a flag that
#: quietly makes `false` mean true is that promise broken in the direction
#: nobody checks. Two spellings, both obvious, everything else refused with the
#: two words that work printed in the refusal.
_FLAG_BOOLEANS = {"true": True, "false": False}


def coerce_context_flags(
    document: Any,
    raw: Mapping[str, str],
    *,
    slug: str | None = None,
) -> dict[str, Any]:
    """`--context key=value` strings, typed by the **declaration**.

    A command line carries strings and nothing else, so the type has to come
    from somewhere. It comes from the document — never guessed from the
    literal, which is the trap this function exists to avoid: guessing would
    make `--context caseId=00123` an integer for one workflow and a string for
    the next, and `--context flag=false` a non-empty and therefore true string
    for everybody.

    A key the document does not declare has no type to be read as, so it is
    left the string it arrived as and refused by the validator with the
    undeclared-key sentence — one door, one refusal, whichever route the value
    came in by.
    """
    workflow = workflow_label(document, slug)
    if context_declaration_problems(document):
        return dict(raw)
    by_key = {field.key: field for field in context_declaration(document)}

    typed: dict[str, Any] = {}
    for key, text in raw.items():
        field = by_key.get(key)
        if field is None or field.type == "string":
            typed[key] = text
            continue
        if field.type == "boolean":
            value = _FLAG_BOOLEANS.get(text.strip().lower())
            if value is None:
                raise RunContextError(
                    f"--context {key}={text!r} is declared 'boolean' by workflow "
                    f"{workflow!r} — write true or false. 1, 0, yes, no, on and off are "
                    "deliberately not accepted."
                )
            typed[key] = value
            continue
        try:
            number = float(text.strip())
        except ValueError:
            raise RunContextError(
                f"--context {key}={text!r} is declared 'number' by workflow "
                f"{workflow!r} — write a number, such as 3 or 3.5."
            ) from None
        if not math.isfinite(number):
            raise RunContextError(
                f"--context {key}={text!r} is declared 'number' by workflow {workflow!r}, and "
                "this run supplied a value that is not a finite number — Infinity and NaN "
                "cannot survive a JSON round trip."
            )
        typed[key] = int(number) if number.is_integer() and "." not in text else number
    return typed


# --------------------------------------------------------------------------- #
# The read side, door one: a node reads what the caller supplied.
# `organisms-first-class/71`, step 5 of the seven in
# `docs/decisions/runtime-context.md`.
# --------------------------------------------------------------------------- #

#: How an author names a declared field inside their own text: `{{tenant}}`.
#:
#: A **name reference and not an expression** — no operators, no calls, no
#: dotted paths — which is portability guardrail 1 obeyed rather than skirted:
#: a placeholder that could compute would be host-language code living in a
#: serialised field. The key grammar is `_MINTABLE_KEY`'s, restated as an
#: inline group rather than composed from it, because this pattern also has to
#: match a key it will then *refuse* to substitute; a pattern that only matched
#: mintable keys would silently leave `{{case-id}}` looking like prose.
#:
#: Surrounding whitespace is tolerated (`{{ tenant }}`) for the reason
#: `CLAUDE.md` gives about reading a model's answer, applied to a human's
#: typing: be tolerant in what you accept, strict in what you then trust — and
#: the strictness is the next paragraph.
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def run_context() -> dict[str, Any]:
    """What this run was given for the fields its workflow declared, or `{}`.

    The sibling of `run_identity()`, and deliberately the same shape of answer:
    a plain mapping, never the minted class. **The compile seam is
    one-directional** — the dataclass is an artefact of the build, so a node
    reads *values* out of it and nothing anywhere reads the type back. A caller
    that received the class would have a LangGraph-shaped object to pass
    around; a caller that receives a dict has JSON.

    `{}` covers three genuinely different situations on purpose, because a node
    can do nothing different about any of them:

    - there is no runnable context at all (a unit test, a script) —
      `get_runtime()` raises, exactly as `get_config()` does for the identity
      accessor;
    - the workflow declares nothing, so the compiler passed no
      `context_schema` and `runtime.context` is `None`;
    - the caller supplied nothing to a workflow that declares nothing.

    That last pair is why this exists rather than every reader writing
    `get_runtime().context.tenant`: measured in
    `tests/test_runtime_context_facts.py`, a run supplying no context is **not**
    refused at the door — `runtime.context` is `None` and the failure is an
    `AttributeError` at whichever node touched it first, naming neither the key
    nor the run. Ticket 70 closed the three supply doors; this closes the
    reader's half of the same hole for the workflow that declares nothing at
    all, which is the common case (none of the shipped packages declares one).
    """
    try:
        from langgraph.runtime import get_runtime

        context = get_runtime().context
    except Exception:
        return {}
    if context is None:
        return {}
    if dataclasses.is_dataclass(context) and not isinstance(context, type):
        # Not `dataclasses.asdict`: that deep-copies and recurses, and these
        # values are declared scalars by construction.
        return {f.name: getattr(context, f.name) for f in dataclasses.fields(context)}
    if isinstance(context, Mapping):
        return dict(context)
    return {}


def _spell(value: Any) -> str:
    """One value, in the spelling the author typed at the door.

    `true`/`false` rather than Python's `True`/`False`, because that is what
    `--context dryRun=false` accepts and what JSON carries; a run whose text
    said `True` would be showing the reader a third spelling of a value they
    supplied in one of the other two.

    An integral `number` renders without its decimal point. The same declared
    value arrives as `3` over HTTP and as `3.0` from the CLI's `float()`, and a
    node's output must not depend on which door the run came in by.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_run_context(text: str, values: Mapping[str, Any] | None = None) -> str:
    """`text` with every `{{key}}` the run actually supplied a value for filled in.

    **Everything else is left byte-identical**, and that is the whole safety
    property. A key the workflow does not declare, a declared key this run has
    no value for, and a `{{` that was never a placeholder at all are each
    passed through exactly as written. The alternative — substituting an empty
    string for what we cannot resolve — silently deletes an author's text, and
    the surfaces this runs on are Markdown, skill instructions and prompts,
    which legitimately contain braces.

    That is `CLAUDE.md`'s two-part rule about reading tolerantly and trusting
    strictly, pointed at a document instead of at a model: the *pattern* is
    generous, the *substitution* is resolved against the run's declared keys
    and nothing else.

    `values` is injectable so a test can exercise the rendering without a
    runnable context; production callers pass nothing and get the ambient run.
    """
    if "{{" not in text:
        return text
    supplied = run_context() if values is None else dict(values)
    if not supplied:
        return text

    def _fill(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in supplied:
            return match.group(0)
        value = supplied[key]
        if value is None:
            return match.group(0)
        return _spell(value)

    return _PLACEHOLDER.sub(_fill, text)
