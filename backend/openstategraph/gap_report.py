"""What a gap report may carry, as a type rather than as a promise.

`team-board-and-gap-reports/07`. A user whose install refused to do something
— a node type this runtime has no implementation for, a provider that is not
configured, a door that said no — can send **that refusal and nothing else**
to the maintainers. The only honest way to ask that is to be able to say
exactly what goes and what does not, and *"we only send anonymous
diagnostics"* is a sentence, not a guarantee.

So the guarantee is this model. Its fields are the owner's allowlist and
nothing else, it is closed (`extra="forbid"`), and the classes on the
never-list are structurally unrepresentable rather than merely absent: a door
that reaches for the document, a prompt, a field value, a table name, the
question, a path or an environment value gets a `ValidationError` instead of a
send.

## Why it is a projection and not one of the three finding shapes we have

`RunFinding` is Pydantic already and carries `arguments` — normalised tool
arguments, which is user content. `DocumentFinding` carries a subject of
`<node id>.<field>`, and a node id is a name its author chose. Both are the
**internal** vocabulary, where user content is exactly what makes a finding
useful. A report is a narrower projection of them, and the narrowing is the
product — which is also why the NO_BACKEND refusal here is rendered from the
*type id* rather than copied from `document_checks`' sentence, whose first
word after "Node" is the author's own name for it.

## What is deliberately not here

No transport. There is no timer, no background sender and no HTTP client in
this module, so no call path can construct a report *and* dispatch it; the
doors (`08`, the user's own `gh`, and `09`, the keyless one) are the only
things that will ever send, once, after a person has read `render()`. That is
opt-in per send with no stored consent, and
`tests/test_a_gap_report_carries_the_allowlist_and_nothing_else.py` holds both
halves open — including a census asserting nothing else in the package
constructs one.
"""

from __future__ import annotations

import hashlib
import platform
import re
from collections.abc import Sequence
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from openstategraph.compile.diagnostics import CompileDiagnostics, Finding
from openstategraph.document_checks import FindingClass
from openstategraph.run_findings import (
    _DIGEST_CHARS,
    EVERY_TOOL_CALL_FAILED,
    NODE_FAILURE,
)

__all__ = [
    "CHECK_IDS",
    "ERRORS_THAT_WRAP_FOREIGN_TEXT",
    "GAP_REPORT_SCHEMA_PATH",
    "GapDoor",
    "GapKind",
    "GapReport",
    "Refusal",
    "RefusalSource",
    "first_traceback_line",
    "report_for_finding",
    "gap_report_schema",
    "hashed_project_id",
]

#: The committed publication of this model. Pydantic is the source of truth
#: for the wire (CLAUDE.md); this file is its generated, committed schema, the
#: way `docs/openapi.json` is for the run/stream seam. Written by
#: `scripts/generate_gap_report_schema.py --write`, never by hand.
GAP_REPORT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "gap-report.schema.json"
)

#: How much of a digest a finding hash carries — imported rather than chosen,
#: for the reason `patrol.refusal_task_id` gives: twelve characters is the
#: width this project already reads in a ticket, and a second number would be
#: a second answer to the same question.
_FINDING_HASH_CHARS = _DIGEST_CHARS

#: A type id, as every one of CLAUDE.md's four channels spells it: an optional
#: package slug, then one namespace, one dot, one name. **Type ids, never
#: values** is the line this pattern draws — a question, a paragraph, a
#: credential and an absolute path all fail it, and so does a bare table name.
_TYPE_ID = re.compile(r"^(?:[a-z0-9][a-z0-9-]*/)?([a-z][a-z0-9_]*)\.([A-Za-z0-9_-]+)$")

#: A path-shaped token, replaced wherever a free-text field would otherwise
#: carry one. Applied in the field validator and not only in the helper, so a
#: door that assembles the string itself is not a second route.
_PATHISH = re.compile(r"(?:[A-Za-z]:)?[\\/][\w.\-\\/]{2,}")

#: Azure AD's own error code, when the refusal carried one — the same shape
#: `patrol._AAD_CODE` matches, for the same reason: `AADSTS7000222` is *the
#: client secret is expired*, and a report that holds it and does not carry it
#: has thrown away the one string that ends the investigation
#: (`osg-agent-experience/73`).
_AAD_CODE = re.compile(r"^AADSTS\d+$")

#: The same code, **found** in a longer sentence rather than validated as a
#: whole field. Two patterns for one code because they answer two questions: a
#: field is not a haystack, so `_AAD_CODE` stays anchored, and a finding's
#: refusal is prose with the code somewhere inside it.
_AAD_IN_TEXT = re.compile(r"\bAADSTS\d+\b")

#: An exception line: the class this package raised, and its own message.
#:
#: **One pattern, and it vouches for nothing on its own** — it splits the class
#: from the message, and `_reportable_error_names()` decides. Until
#: `team-board-and-gap-reports/16` the `EXCEPTION` source had a second pattern
#: that ended `(?:Error|Exception): `, and a suffix is not a set: half of this
#: package's own errors are not called `…Error` at all
#: (`MissingProviderKey`, `PackageNotFound`, `ThreadNotResumable`), so
#: `for_our_exception` built a `Refusal` the `Refusal` model then rejected and
#: the caller got a `ValidationError` where a report was meant to be. The two
#: questions are one question now, asked in one place.
_OUR_EXCEPTION_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*): (.{1,400})$")

_VERSION = re.compile(r"^[0-9A-Za-z.+-]{1,40}$")
_OS = re.compile(r"^[A-Za-z][A-Za-z0-9 ._-]{0,59}$")
_PYTHON = re.compile(r"^\d+\.\d+\.\d+[A-Za-z0-9.+-]{0,12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: The longest a single carried sentence may be. A cap rather than a trim of
#: the model's choosing: the refusal sentences this codebase writes are all
#: well under it, so a value that needs cutting is a value that did not come
#: from one of them.
TEXT_CAP = 400


def hashed_project_id(project_id: str) -> str:
    """The tenancy key a report carries in place of the install's identity.

    The owner's decision: *"a report carries a hash of it; two clones of one
    repo are one project"*. Full SHA-256 rather than the twelve characters a
    finding hash carries, because this one is a key that a rate limit and a
    board's tenancy both hang off, across every install in the world, while a
    finding hash only has to be distinct inside one project.
    """
    return hashlib.sha256(project_id.encode("utf-8")).hexdigest()


def _this_version() -> str:
    from openstategraph import __version__

    return __version__


def _this_os() -> str:
    """The system and its release, and nothing narrower.

    `platform.node()` is the hostname and `platform.platform()` carries it on
    some systems; neither is on the allowlist, and the reason a report names
    an OS at all is that a gap can be one platform's.
    """
    return f"{platform.system()} {platform.release()}".strip()


def _redacted(text: str) -> str:
    return _PATHISH.sub("<path>", text).strip()[:TEXT_CAP]


def first_traceback_line(exc: BaseException) -> str:
    """One line naming what was raised, with nothing under it.

    The owner's allowlist says *first traceback line*, and read literally the
    first line of a formatted traceback is `Traceback (most recent call
    last):` — which carries no information — while every line under it names a
    file on this machine. So the line carried is the exception line: the one
    line of a traceback that has a cause in it and no frame, and therefore no
    path. Later frames are never read at all, which is stronger than stripping
    them.

    The message is still redacted, because an exception's *class* being ours
    does not make its *argument* ours: `FileNotFoundError` puts the path it
    could not find in its own message.
    """
    return _redacted(f"{type(exc).__name__}: {exc}")


@lru_cache(maxsize=1)
def _runtime_sentences() -> tuple[re.Pattern[str], ...]:
    """The compiler's own sentences, as patterns, for the two findings whose
    subjects are type ids.

    Narrow on purpose. `UNENFORCED_OUTCOME` reads *Team "{0}" mounts "{1}"* —
    those slots are the names a user gave two workflows, so admitting that
    template would admit user content through a field this module exists to
    close.
    """
    slot = _TYPE_ID.pattern.strip("^$")
    patterns = []
    for finding in (Finding.UNRESOLVED_TOOL, Finding.UNRESOLVED_FUNCTION):
        pieces = re.split(r"\{\d+\}", CompileDiagnostics.sentence_for(finding))
        literal = slot.join(re.escape(piece) for piece in pieces)
        patterns.append(re.compile(f"^{literal}$"))
    return tuple(patterns)


@lru_cache(maxsize=1)
def _provider_sentences() -> frozenset[str]:
    """Every refusal a built-in provider spec can write, enumerated from the
    catalogue itself — a second list here would be the drift this repository
    names by name."""
    from openstategraph.providers import builtin_specs

    found: set[str] = set()
    for spec in builtin_specs():
        found.add(spec.missing_package_message())
        if spec.env_vars:
            found.add(spec.missing_key_message())
    return frozenset(found)


@lru_cache(maxsize=1)
def _our_error_names() -> frozenset[str]:
    """Every error class `openstategraph.errors` defines, by name.

    Derived from the module rather than listed here, for the reason every
    census in this repository is: a list written down covers the errors
    somebody already thought of. Narrower than `for_our_exception`'s test,
    which asks whether the *object*'s module is ours — a name in a string
    cannot be asked that, and the package's own error module is the set that
    can be resolved from one.
    """
    from openstategraph import errors

    return frozenset(
        name
        for name, value in vars(errors).items()
        if isinstance(value, type) and issubclass(value, errors.OpenStateGraphError)
    )


#: Errors of ours whose **message** is not, and the reason at each.
#:
#: `team-board-and-gap-reports/16`. A line is admitted as
#: `<class>: <message>`, so admitting a class publishes whatever that class
#: puts after the colon. Most of `errors.py` writes its own sentence — a
#: `ProviderSpec`'s variable names, `step_budget`'s wording, a slug — and
#: `credential_error_from` and `unreachable_endpoint_error_from` go out of
#: their way to *drop* the vendor's text rather than append it. These two do
#: not, so they are refused by name at the door: ours by class is not the
#: test, ours by sentence is, and `07`'s guarantee is about the sentence.
#:
#: Refused rather than trimmed, because there is no honest trim: the foreign
#: half is in the middle of our own words, and a caller who wants to report
#: one of these knows what refused and can say it themselves.
ERRORS_THAT_WRAP_FOREIGN_TEXT: dict[str, str] = {
    "RunProducedNothing": (
        "its message quotes the run's own first failure, and a node failure "
        "carries `describe_failure(exc)` — a driver's or a vendor's sentence"
    ),
    "DocumentError": (
        "`schema.py` raises it with `json.JSONDecodeError`'s text interpolated "
        "into the message; its subclasses write their own sentences and are "
        "admitted"
    ),
}


@lru_cache(maxsize=1)
def _reportable_error_names() -> frozenset[str]:
    """The class names an `EXCEPTION` refusal line may carry.

    `_our_error_names()` less the classes above — the census minus the ones
    whose message is somebody else's. Derived at validation time from the
    module itself, so an error class added tomorrow is reportable the day it
    is written, and one added tomorrow that wraps foreign text is a name
    somebody has to add here with a reason beside it.
    """
    return frozenset(_our_error_names() - frozenset(ERRORS_THAT_WRAP_FOREIGN_TEXT))


#: What **this codebase** says about a finding the patrol recorded, one
#: sentence per finding kind a report has a `GapKind` for.
#:
#: Written here rather than taken from the finding, and that is the whole of
#: `team-board-and-gap-reports/15`'s judgement. A finding's own `arguments`
#: is what a tool produced: `ToolResult.failure` puts the driver's sentence
#: there, and `Invalid arguments: …` puts the model's own arguments there. So
#: the words a report carries about a run failure are ours, and what makes
#: the report worth reading is the structure beside them — the tool **type**
#: that could not be reached, the check that noticed, and Azure AD's own code
#: when the refusal carried one.
_FINDING_SENTENCES: dict[str, str] = {
    EVERY_TOOL_CALL_FAILED: (
        "Every tool call this run made was refused, all of them the same way, "
        "and no result came back."
    ),
    NODE_FAILURE: "A node failed after retries and produced no result.",
}


class RefusalSource(str, Enum):
    """Where a refusal sentence was written. Not *what refused* — that is
    `GapDoor` — but which of this codebase's three sentence-writing seams
    produced the words, because each is validated differently."""

    #: The compiler's own `_SENTENCES` table.
    RUNTIME = "runtime"
    #: A `ProviderSpec`'s own message about a credential or a package.
    PROVIDER = "provider"
    #: An exception this package defines, as one line.
    EXCEPTION = "exception"
    #: A finding the patrol recorded — `team-board-and-gap-reports/15`. Two
    #: shapes, both ours and both re-checked on every construction: this
    #: module's own sentence for that finding kind, or an exception line
    #: naming a class `openstategraph.errors` defines, which is what the tool
    #: seam wrote when the thing that failed was ours. Never the finding's own
    #: text otherwise, because that text is a vendor's or a model's.
    FINDING = "finding"


class GapKind(str, Enum):
    """What kind of gap this is, in the vocabulary that already exists.

    Three of the five are imported rather than coined: a gap report about a
    node type with no implementation is the same fact `FindingClass.NO_BACKEND`
    names, and one vocabulary is the whole reason this model is a projection
    of the finding shapes rather than a fourth spelling of them.
    """

    NO_BACKEND = FindingClass.NO_BACKEND.value
    NODE_FAILURE = NODE_FAILURE
    EVERY_TOOL_CALL_FAILED = EVERY_TOOL_CALL_FAILED
    #: A provider named by a document that this install cannot build a client
    #: for. Not a defect of ours; a gap in what the install was given.
    PROVIDER_NOT_CONFIGURED = "provider-not-configured"
    #: Anything a door refused outright, with its own sentence.
    DOOR_REFUSED = "door-refused"


class GapDoor(str, Enum):
    """Which surface the user was standing at when it refused.

    The four blocking doors `run_doors.py` names, plus the editor — the same
    list, because a report that invents a fifth name for `POST /api/runs`
    makes two boards disagree about where something happens.
    """

    API = "api"
    MCP = "mcp"
    CLI = "cli"
    LIBRARY = "library"
    EDITOR = "editor"


#: The check ids a report may cite, derived from the three enums that already
#: publish them: the document checks' classes, the compiler's findings, and
#: the patrol's finding names. A check id is a name **we** publish; a table
#: name and a question are not check ids and fail here.
CHECK_IDS: frozenset[str] = frozenset(
    {member.value for member in FindingClass}
    | {member.value for member in Finding}
    | {NODE_FAILURE, EVERY_TOOL_CALL_FAILED}
)


class Refusal(BaseModel):
    """The sentence that refused, and which seam of ours wrote it.

    **Ours, not theirs.** There is no constructor here that takes a bare
    string: the three classmethods take a type id, a `ProviderSpec` and an
    exception this package defines, and validation re-checks the text against
    what those seams can produce, so a round trip cannot widen it either. A
    model's answer is a `str` and has no way in — which matters because this
    product prints prose constantly and a refusal field is exactly where a
    door would be tempted to put "what the agent said".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: RefusalSource
    text: str

    @field_validator("text")
    @classmethod
    def _one_of_ours(cls, value: str, info: Any) -> str:
        source = info.data.get("source")
        text = _redacted(value)
        if source is RefusalSource.RUNTIME:
            if any(pattern.match(text) for pattern in _runtime_sentences()):
                return text
        elif source is RefusalSource.PROVIDER:
            if text in _provider_sentences():
                return text
        elif source is RefusalSource.EXCEPTION:
            named = _OUR_EXCEPTION_LINE.match(text)
            if named is not None and named.group(1) in _reportable_error_names():
                return text
        elif source is RefusalSource.FINDING:
            if text in _FINDING_SENTENCES.values():
                return text
            named = _OUR_EXCEPTION_LINE.match(text)
            if named is not None and named.group(1) in _our_error_names():
                return text
        raise ValueError(
            "a refusal is a sentence this codebase writes, not text handed to "
            "it — build one with Refusal.for_missing_implementation, "
            "Refusal.for_provider, Refusal.for_our_exception or "
            "Refusal.for_finding"
        )

    @classmethod
    def for_missing_implementation(cls, type_id: str) -> Refusal:
        """`No implementation for tool "<type id>"` — the archetypal platform
        gap, in the compiler's own words and about the *type*, never about the
        node id the author chose."""
        return cls(
            source=RefusalSource.RUNTIME,
            text=CompileDiagnostics.sentence_for(Finding.UNRESOLVED_TOOL).format(type_id),
        )

    @classmethod
    def for_provider(cls, spec: Any) -> Refusal:
        """A `ProviderSpec`'s own refusal — it names variables, never values."""
        text = spec.missing_key_message() if spec.env_vars else spec.missing_package_message()
        return cls(source=RefusalSource.PROVIDER, text=text)

    @classmethod
    def for_our_exception(cls, exc: BaseException) -> Refusal:
        """One line from an exception **`openstategraph.errors` defines**.

        A `TypeError` for anything else, raised rather than validated away: a
        third party's exception carries a third party's message, and the
        caller has to decide what to say instead rather than have this module
        decide quietly for them.

        **`errors.py`, not "anywhere under `openstategraph/`"** —
        `team-board-and-gap-reports/16`'s ruling, and it is a narrowing of what
        the module test used to admit. Two reasons, and the second is the one
        that decides it: `errors.py` is the module whose whole contract is
        *the exceptions an adopter may catch*, written to be read by someone
        who cannot fix it, while a door's own type — `DoorClosed`,
        `AnotherServerIsRunning`, `StageOrderError` — is local control flow
        with no such promise; and a name arriving as a **string** (the finding
        path, `for_finding`) can only be resolved against one module, so the
        alternative was two different sets called by one name. A door's
        exception is converted into one of ours by its caller, or it is not
        reported.

        A class of ours whose message quotes somebody else's is refused here
        too, by name and with the reason — see
        `ERRORS_THAT_WRAP_FOREIGN_TEXT`.
        """
        from openstategraph.errors import OpenStateGraphError

        name = type(exc).__name__
        if not isinstance(exc, OpenStateGraphError) or name not in _our_error_names():
            raise TypeError(
                f"{name} is defined in {type(exc).__module__!r}, not in "
                "openstategraph.errors — a report carries our own refusal "
                "sentences only"
            )
        wrapped = ERRORS_THAT_WRAP_FOREIGN_TEXT.get(name)
        if wrapped is not None:
            raise TypeError(
                f"{name} is ours but its message is not: {wrapped}. Say what "
                "refused in your own words, or report the finding instead"
            )
        return cls(source=RefusalSource.EXCEPTION, text=first_traceback_line(exc))

    @classmethod
    def for_finding(cls, finding: str, text: str = "") -> Refusal:
        """What a patrol finding refused, in words this codebase wrote.

        `team-board-and-gap-reports/15`. **Tolerant in reading, strict in
        trusting**, and here the strict half is the product: the finding's own
        text is read, and it is carried only when it turns out to be an
        exception line naming a class `openstategraph.errors` defines — the
        subset `15` named, the one a tool of ours put there. Anything else —
        an ODBC message, an `AADSTS` sentence, `Invalid arguments: …` with the
        model's own arguments echoed back — is dropped, and the sentence this
        module writes for that finding kind is carried instead.

        A finding kind no report has a `GapKind` for is refused by name rather
        than given a sentence: waste is not a platform gap, and a report
        saying nothing about a real problem is worse than no report.
        """
        if finding not in _FINDING_SENTENCES:
            raise ValueError(
                f"{finding!r} is not a finding a gap report can be built from. "
                f"The reportable ones are {', '.join(sorted(_FINDING_SENTENCES))} "
                "— a repeated call and an unstable answer are this install's own "
                "waste, not a gap in the platform."
            )
        from openstategraph.abc.tool import TOOL_FAILURE_PREFIX

        line = _redacted(text).removeprefix(TOOL_FAILURE_PREFIX).strip()
        named = _OUR_EXCEPTION_LINE.match(line)
        if named is not None and named.group(1) in _our_error_names():
            return cls(source=RefusalSource.FINDING, text=line)
        return cls(source=RefusalSource.FINDING, text=_FINDING_SENTENCES[finding])


def report_for_finding(
    *,
    finding: str,
    type_ids: Sequence[str],
    refusal_text: str,
    project_hash: str,
    door: GapDoor = GapDoor.CLI,
) -> GapReport:
    """The report a patrol finding supports, and nothing more than it supports.

    `team-board-and-gap-reports/15`. The finding's contribution is its
    **structure** — which kind of failure, which tool types were involved, the
    check that named it, and Azure AD's own code when the refusal carried one
    (`osg-agent-experience/73`: that string ends the investigation). The words
    come from `Refusal.for_finding`, which is where the judgement about whose
    sentence it is lives.

    Built here rather than at either caller, so the module that owns the
    allowlist is still the only one that constructs a report from parts — the
    census in `tests/test_a_gap_report_carries_the_allowlist_and_nothing_else.py`
    holds unchanged, and the patrol, which calls this only for the hash and
    sends nothing, does not become a door.
    """
    code = _AAD_IN_TEXT.search(refusal_text or "")
    return GapReport(
        kind=GapKind(finding),
        type_ids=tuple(type_ids),
        door=door,
        refusal=Refusal.for_finding(finding, refusal_text),
        check=finding,
        project_hash=project_hash,
        aad_code=code.group(0) if code else None,
    )


class GapReport(BaseModel):
    """One platform gap, as it will be sent — and nothing else.

    Every field is on the owner's allowlist. The two hashes are the map's own
    additions: `project_hash` is the install's identity as a hash
    (`team-board-and-gap-reports/01`'s seam) and `finding_hash` is the dedup
    key `09` needs, so forty runs of one refusal are one card with a count.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The package version, from this install. Filled in here rather than
    #: asked of a caller: a door that has to remember to state the version is
    #: a door that will one day send a report about an install nobody can name.
    version: str = Field(default_factory=lambda: _this_version())
    kind: GapKind
    #: The node/tool **type ids** involved. Type ids, never values.
    type_ids: tuple[str, ...] = ()
    door: GapDoor
    refusal: Refusal
    #: A check id this codebase publishes, when a check is what noticed.
    check: str | None = None
    traceback_line: str | None = None
    os: str = Field(default_factory=lambda: _this_os())
    python: str = Field(default_factory=lambda: platform.python_version())
    project_hash: str
    #: Azure AD's own code when the refusal carried one.
    aad_code: str | None = None

    @field_validator("type_ids")
    @classmethod
    def _only_type_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        namespaces = _known_namespaces()
        for candidate in value:
            found = _TYPE_ID.match(candidate)
            if not found or found.group(1) not in namespaces:
                raise ValueError(
                    f"{candidate!r} is not a node or tool type id. Type ids, never "
                    "values: a field's contents, a table name, a question and a path "
                    "are all things a report does not carry."
                )
        return value

    @field_validator("check")
    @classmethod
    def _a_published_check_id(cls, value: str | None) -> str | None:
        if value is None or value in CHECK_IDS:
            return value
        raise ValueError(
            f"{value!r} is not a check id this codebase publishes. The vocabulary is "
            "the document checks' classes, the compiler's findings and the patrol's "
            "finding names."
        )

    @field_validator("traceback_line")
    @classmethod
    def _one_redacted_line(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _redacted(value.splitlines()[0] if value.splitlines() else "")

    @field_validator("version")
    @classmethod
    def _a_version(cls, value: str) -> str:
        return _matched(_VERSION, value, "a package version")

    @field_validator("os")
    @classmethod
    def _an_os(cls, value: str) -> str:
        return _matched(_OS, value, "an operating system name and release")

    @field_validator("python")
    @classmethod
    def _a_python(cls, value: str) -> str:
        return _matched(_PYTHON, value, "a Python version")

    @field_validator("project_hash")
    @classmethod
    def _a_hashed_id(cls, value: str) -> str:
        return _matched(_SHA256, value, "a SHA-256 of the project id, never the id")

    @field_validator("aad_code")
    @classmethod
    def _an_aad_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _matched(_AAD_CODE, value, "an Azure AD error code")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def finding_hash(self) -> str:
        """The dedup key, from what the finding *is*.

        Deliberately **not** over the version, the OS or the Python: the same
        gap on the same install after an upgrade is the same gap, and a key
        that moved on every release would file a fresh card each time. Not a
        field either, so a door cannot hand one in.
        """
        stable = "\n".join(
            [
                self.kind.value,
                "\t".join(sorted(self.type_ids)),
                self.door.value,
                self.check or "",
                self.refusal.source.value,
                self.refusal.text,
                self.traceback_line or "",
                self.aad_code or "",
            ]
        )
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:_FINDING_HASH_CHARS]

    def render(self) -> str:
        """The exact payload, as a person reads it before deciding.

        Derived from the model's own dump rather than from a list written
        here, so a field added later cannot be sent unseen — the failure this
        whole model exists to make impossible would otherwise walk straight
        back in through its own preview.
        """
        payload = self.model_dump(mode="json")
        width = max(len(name) for name in payload)
        rows = []
        for name, value in payload.items():
            if isinstance(value, dict):
                shown = " · ".join(f"{key}: {item}" for key, item in value.items())
            elif isinstance(value, list):
                shown = ", ".join(str(item) for item in value) or "—"
            else:
                shown = "—" if value in (None, "") else str(value)
            rows.append(f"  {name.ljust(width)}  {shown}")
        return "\n".join(
            [
                "This is the whole report. Nothing else is sent.",
                "",
                *rows,
                "",
                "Never sent: the document, prompts, field values, table names,",
                "question text, file paths, environment values. The project id is",
                "sent as a hash, never as itself.",
                "",
                "Nothing has been sent yet. Sending happens once, now, only if you",
                "say so — there is no stored consent and no background sender.",
            ]
        )


def _matched(pattern: re.Pattern[str], value: str, expected: str) -> str:
    if pattern.match(value):
        return value
    raise ValueError(f"{value!r} is not {expected}")


@lru_cache(maxsize=1)
def _known_namespaces() -> frozenset[str]:
    """The namespaces a type id may open with, read off the catalogue.

    Membership is deliberately **not** checked: the archetypal report is about
    a type this runtime has no implementation for, and a package's own
    `tools/` leaf is minted per package. So the gate is the shape and the
    namespace — enough to make a question, a path or a table name
    unrepresentable, and not so much that the one report this map exists for
    cannot be filed.
    """
    from openstategraph.compile.node_catalogue import CATALOGUE

    namespaces = {node_type.partition(".")[0] for node_type in CATALOGUE.node_types}
    namespaces |= {
        str(prefix.get("prefix", "")).rstrip(".") for prefix in CATALOGUE.type_prefixes
    }
    #: The package-scoped channel: `<slug>/tools.QueryTool`, whose namespace is
    #: the folder the discovery walks rather than a palette namespace.
    namespaces |= {"tools", "functions"}
    return frozenset(name for name in namespaces if name)


def gap_report_schema() -> dict[str, Any]:
    """The JSON Schema published to `docs/gap-report.schema.json`."""
    schema = GapReport.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "OpenStateGraph gap report"
    schema["description"] = (
        "Everything a gap report may carry, and nothing else. Generated from "
        "openstategraph.gap_report.GapReport by "
        "scripts/generate_gap_report_schema.py; never hand-edited."
    )
    return schema
