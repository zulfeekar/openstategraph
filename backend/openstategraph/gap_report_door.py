"""The user's own door onto the issue tracker — `team-board-and-gap-reports/08`.

A refusal this install printed already knows what it refused: a node type this
runtime has no implementation for, named by its type id. Until this module
existed the next step it offered was nothing, so a user shrugged or opened a
browser, found the repository, found the form, and retyped from memory what the
terminal already had in its hand.

The owner's decision, and the shape of everything below: **GitHub is the user's
door.** The issue is filed under the user's **own** `gh` login, after the exact
payload has been printed, once, only if they said so in the same run.

## Three properties, and each is why a part of this is shaped as it is

- **No credential of ours is involved.** `gh` brings the user's; we bring none,
  read none, and hand the subprocess nothing but the issue it is to file. There
  is nothing here to rotate, and nothing here that could leak. That is also why
  it is a subprocess rather than an HTTP client: a token would need an owner.
- **It adds no dependency.** `gh` is a program a user has or does not, so the
  four-dependency core floor is untouched — and an install without it is a
  refusal that names the fix, never a traceback.
- **The address is derived, never typed.** `repository()` reads the package's
  own metadata, which is generated from `pyproject.toml`'s `[project.urls]`.
  A second copy here would be the drift this repository names by name: the
  stable home receives this code with every URL re-pointed in one change, and a
  literal in this file would be the one that stayed behind.

## What a subject may be, and the one that is refused on purpose

The subject is a **type id** — the thing every `NO_BACKEND` refusal already
prints, and the archetypal platform gap. A patrol **card id** is accepted as
far as saying why it cannot be sent: a card records a run's own failure, which
is a driver's sentence or a node's, and `GapReport` carries only the sentences
*this codebase* writes (`gap_report.Refusal` has no constructor that takes free
text, deliberately). So there is nothing on such a card this door could
honestly send, and the refusal says so and points at the by-hand form rather
than assembling a report with somebody else's prose in it. Filed as
`team-board-and-gap-reports/15`.

## Why the body is a rendered form and not `render()`'s block

Both are the same values; only one of them parses. `render()` is what the
**user** reads — the model's own preview, derived from its own dump so a field
added later cannot be sent unseen. The **issue body** is what the board reads:
`github_issue_bridge.parse_issue_form` turns `### <label>` sections into a
card, and it is the same function that reads an issue a person filled in by
hand. Rendering the preview block into the body would file an issue the bridge
could only treat as prose, so an automated report and a hand-typed one would
land as two different kinds of card. `FIELD_LABELS` is imported from that
module rather than restated, so there is one map and not two.

## No MCP door, and that is the trust boundary rather than an omission

`mcp_server.py` states it: publishing is not exposed over MCP, and a human
clicks publish. Filing a public issue under a user's own login is a public,
irreversible write, and the client filling in an MCP tool's arguments is a
model. `report_gap` would be that boundary crossed for the convenience of not
typing one command. The CLI is the door; an agent that wants one runs the verb.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from typing import Any, Callable, Protocol

from openstategraph.document_checks import FindingClass
from openstategraph.gap_report import (
    GapDoor,
    GapKind,
    GapReport,
    Refusal,
    report_for_finding,
)
from openstategraph.github_issue_bridge import FIELD_LABELS

__all__ = [
    "DoorClosed",
    "LABEL",
    "PROGRAM",
    "UnreportableSubject",
    "build_report",
    "by_hand",
    "file_issue",
    "issue_body",
    "issue_title",
    "issue_form_url",
    "preview",
    "report_for_card",
    "repository",
]

#: The program this door shells out to. A name, resolved on `PATH` at call
#: time — never an absolute path, which would be one machine's answer.
PROGRAM = "gh"

#: The label the template applies, and the one `github_issue_bridge` reads to
#: decide the card kind. Passed explicitly because `gh issue create --body`
#: files a plain issue: the template's own `labels:` applies to the web form
#: only, so an issue this door files would otherwise reach the board unlabelled.
LABEL = "platform-gap"

#: The template a hand-filled report uses, so a refusal can name the exact page
#: rather than "the issue tracker".
_TEMPLATE = "platform-gap.yml"

_HOST = "https://github.com/"


class Runner(Protocol):
    """`subprocess.run`, narrowed to the two calls made here."""

    def __call__(self, args: Sequence[str], **kwargs: Any) -> Any: ...


class DoorClosed(RuntimeError):
    """There is no `gh` to file through, so nothing was sent.

    Carries the whole refusal as its message — what is missing, the command
    that fixes it, and the way to file the same report by hand — because a
    caller printing only *"gh not found"* would be the refusal with no next
    step this ticket exists to end.
    """


class UnreportableSubject(ValueError):
    """Nothing this door can honestly build a report from."""


def repository() -> str:
    """`<owner>/<name>`, from the package's own metadata.

    One config place: `[project.urls]` in `pyproject.toml`, published into the
    installed distribution's metadata. Read rather than restated, so the day
    this code moves to its stable home there is nothing here to remember.
    """
    from importlib.metadata import metadata

    for entry in metadata("openstategraph").get_all("Project-URL") or []:
        name, _, url = str(entry).partition(", ")
        if name.strip().casefold() == "repository" and _HOST in url:
            return url.strip().rstrip("/").split(_HOST, 1)[1]
    raise DoorClosed(
        "this build's metadata names no repository, so there is no tracker to "
        "file against. Report the gap wherever you obtained the package."
    )


def issue_form_url() -> str:
    """The platform-gap form, as a person opens it."""
    return f"{_HOST}{repository()}/issues/new?template={_TEMPLATE}"


def by_hand(report: GapReport) -> str:
    """What to do instead, when this door cannot open.

    Named once and used by every refusal below, so the two ways of failing say
    the same thing about the way that still works.

    `09`'s keyless door is named as what it is: a door that exists in this
    package and is **off** until an install names an endpoint for it. Saying
    "there is another door" without that clause would be a promise the install
    in front of the user cannot keep, and saying nothing at all leaves a reader
    who will never have `gh` believing the form is their only path. This
    function does not read the variable to find out — a report door that reads
    the environment is the one thing this module must be able to say it never
    does — so it points at the page that explains it.
    """
    return "\n".join(
        [
            "File it by hand — the form's boxes are the lines above, in order:",
            f"  {issue_form_url()}",
            "",
            "There is a second, keyless door for installs that will never have "
            "`gh` — it is off unless your install names an endpoint for it. See "
            "\u201cThe keyless door\u201d in docs/reporting-a-platform-gap.md.",
            f"Nothing was sent. The report is unchanged: {report.finding_hash}.",
        ]
    )


def build_report(
    subject: str,
    *,
    project_hash: str,
    door: GapDoor = GapDoor.CLI,
) -> GapReport:
    """One gap, from the one thing the refusal already handed the user.

    The subject is **not** re-validated here. `GapReport` refuses anything that
    is not a type id — a question, a path, a table name — and a second gate in
    this module would be a second answer to the question that model exists to
    settle.
    """
    candidate = subject.strip()
    if ":" in candidate:
        raise UnreportableSubject(
            f"{candidate!r} looks like a board card id, not a type id. A card records "
            "what a run did — a driver's own sentence, or a node that failed — and a "
            "gap report carries only the sentences this codebase writes, so there is "
            "nothing on it this door could send without putting somebody's prose in a "
            "report that has no field for it. Report the type id the refusal named, or "
            f"file the card by hand: {issue_form_url()}"
        )
    return GapReport(
        kind=GapKind.NO_BACKEND,
        type_ids=(candidate,),
        door=door,
        refusal=Refusal.for_missing_implementation(candidate),
        check=FindingClass.NO_BACKEND.value,
        project_hash=project_hash,
    )


def report_for_card(
    card: Any,
    *,
    project_hash: str,
    door: GapDoor = GapDoor.CLI,
) -> GapReport:
    """One gap, from a card the patrol filed — `team-board-and-gap-reports/15`.

    `08` refused every card id and said why: a card recorded the classifier's
    prose and nothing a report has a field for. `15` settled both halves of
    that. A card minted from a finding now records the finding
    (`Card.gap_evidence`), and the words a report carries about a run failure
    are this codebase's own — so what is sent is which kind of failure, which
    tool **types** were involved, the check that named it, and Azure AD's own
    code when the refusal carried one. The driver's sentence is not on the
    card's evidence's account; `Refusal.for_finding` decides that, and it
    decides it again here rather than trusting what the store held.

    A card with no evidence is refused **by name**, which is the whole of why
    the field is empty rather than absent: a hand-filed idea, a repeated call
    and an unstable answer are not platform gaps, and a report assembled from
    one would be a maintainer reading somebody's prose under our schema.
    """
    task_id = str(getattr(card, "task_id", "") or "")
    evidence = str(getattr(card, "gap_evidence", "") or "").strip()
    if not evidence:
        raise UnreportableSubject(
            f"{task_id!r} is a card with no finding behind it, so there is nothing "
            "on it a report could carry. Cards filed from a run failure record "
            "the finding they were minted from; a card somebody typed, and a card "
            "about a repeated call or an unstable answer, record a judgement about "
            "this install rather than a gap in the platform. Report the type id a "
            f"refusal named, or file this one by hand: {issue_form_url()}"
        )
    try:
        recorded = json.loads(evidence)
        finding = str(recorded["finding"])
        type_ids = tuple(str(item) for item in recorded.get("type_ids") or ())
        refusal_text = str(recorded.get("refusal") or "")
    except (ValueError, KeyError, TypeError) as exc:
        raise UnreportableSubject(
            f"{task_id!r} carries evidence this version cannot read ({exc}), so "
            "nothing was built from it. Report the type id the refusal named, or "
            f"file it by hand: {issue_form_url()}"
        ) from exc
    return report_for_finding(
        finding=finding,
        type_ids=type_ids,
        refusal_text=refusal_text,
        project_hash=project_hash,
        door=door,
    )


def issue_title(report: GapReport) -> str:
    """`[gap]: …` — the template's own prefix, then what refused.

    The type id and nothing else after it. A title is the one part of an issue
    a maintainer reads before opening it, and every other field is in the body
    a line later.
    """
    named = " ".join(report.type_ids) or report.check or report.kind.value
    return f"[gap]: {report.kind.value} — {named}"[:200]


def preview(report: GapReport) -> str:
    """Everything that will leave this machine, before any of it does.

    Two blocks, and both are the same values: the model's own `render()`, which
    is what `docs/reporting-a-platform-gap.md` shows a reader and what an agent
    following the skill prints, and then the issue exactly as `gh` will receive
    it. The second is there because *"an issue is filed"* is not something a
    person can check, and the body is the part they are being asked to consent
    to. The words live here rather than in the CLI for the reason the CLI's own
    header gives: a command wraps a seam and adds no logic, and a second door
    onto this report must not have to re-say any of it.
    """
    lines = [
        report.render(),
        "",
        f"The issue this files on {repository()}, as you, under your own gh login:",
        f"  {issue_title(report)}",
    ]
    lines += [f"  {line}" if line else "" for line in issue_body(report).splitlines()]
    return "\n".join(lines)


def issue_body(report: GapReport) -> str:
    """The report, under the labels the template renders.

    Derived from `model_dump` rather than from a list here, for the same reason
    `render()` is: a field added to the model later must not be able to reach an
    issue unseen, or be silently left out of one.
    """
    sent = report.model_dump(mode="json")
    sections: list[str] = []
    for field, label in FIELD_LABELS.items():
        value = sent.get(field)
        if field == "refusal":
            value = report.refusal.text
        elif isinstance(value, list):
            value = " ".join(str(item) for item in value)
        text = "" if value is None else str(value).strip()
        if not text:
            continue
        sections += [f"### {label}", "", text, ""]
    return "\n".join(sections).strip() + "\n"


_UNSET = object()


def file_issue(
    report: GapReport,
    *,
    executable: str | None | Any = _UNSET,
    run: Callable[..., Any] | None = None,
) -> str:
    """File it, under the user's own login, and answer with the issue's address.

    Two calls, in this order and no other: `auth status`, which is read-only and
    decides whether there is a login at all, and then `issue create`. A logged
    out `gh` is never asked to create anything — it would prompt for a login in
    the middle of a command the user ran to send one report.

    `executable` and `run` are the injection seam the tests use. Nothing else
    passes them: the default resolves `gh` on `PATH` at call time, so a `gh`
    installed after this process started is still found.
    """
    runner = run or subprocess.run
    program = shutil.which(PROGRAM) if executable is _UNSET else executable
    if not program:
        raise DoorClosed(
            "\n".join(
                [
                    f"`{PROGRAM}` is not on your PATH, so this report was not sent.",
                    "",
                    "The GitHub CLI is what files the issue under your own login — "
                    "no credential of ours is involved, and none is needed. Install "
                    f"it, run `{PROGRAM} auth login`, and run this command again.",
                    "",
                    by_hand(report),
                ]
            )
        )
    status = runner([program, "auth", "status"], capture_output=True, text=True, check=False)
    if getattr(status, "returncode", 1) != 0:
        raise DoorClosed(
            "\n".join(
                [
                    f"`{PROGRAM}` is installed and not logged in, so this report was "
                    "not sent.",
                    "",
                    f"Run `{PROGRAM} auth login` and run this command again. The issue "
                    "is filed as you — your account, your issue, yours to edit, close "
                    "and follow.",
                    "",
                    by_hand(report),
                ]
            )
        )
    created = runner(
        [
            program,
            "issue",
            "create",
            "--repo",
            repository(),
            "--title",
            issue_title(report),
            "--body",
            issue_body(report),
            "--label",
            LABEL,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if getattr(created, "returncode", 1) != 0:
        said = (getattr(created, "stderr", "") or "").strip()
        raise DoorClosed(
            "\n".join(
                [
                    f"`{PROGRAM}` refused to file the issue, in its own words:",
                    f"  {said}" if said else "  (it said nothing)",
                    "",
                    by_hand(report),
                ]
            )
        )
    return str(getattr(created, "stdout", "") or "").strip()
