"""An issue a user files, copied onto the board — `team-board-and-gap-reports/05`.

Six workflows existed and none of them fired on `issues`, so a platform-gap
report reached a maintainer through a notification email or not at all, and
closing it taught the board nothing: when the fix shipped, the card that was
never filed could not be resolved.

This module is the whole of what the Action runs. Two properties are the
design, and both are what make it testable at all:

**It is pure over a payload and a store.** `apply_event` takes the decoded
GitHub event and an `IKanbanStore`, and returns a `BridgeOutcome` saying what
it wrote and what it would like posted back. It opens no socket, imports no
GitHub client and knows no token; `main` is the only part that touches the
environment, and the tests never reach it with a real event. The workflow
posts the comment, because posting is the one thing that needs the repository's
own token and is therefore the one thing a test cannot honestly rehearse.

**It never invents a resolution.** A card reaches Resolved through the evidence
gate (`kanban-patrol/17`: a failing test, its fix, and the commit that carries
it) and closing an issue is not that evidence. So a close over an unfinished
card moves nothing and *says so on the issue* — the write-back is the mark. The
one card a close can legitimately write to is a judgement still waiting in
Needs You, where `answer_card` is the store's own door for "a person decided",
and closing an issue is exactly that.

## The two spellings this module has to keep straight

A rendered issue-form body is headed by each field's **label**, not its id, and
this module has no checkout to read `.github/ISSUE_TEMPLATE/platform-gap.yml`
from. So `FIELD_LABELS` is the map, and
`tests/test_an_issue_a_user_files_reaches_the_board.py` pins it against the
template rather than trusting two files to agree.

## Tolerant in reading, strict in trusting

`CLAUDE.md`'s rule, applied to a form a person fills in by hand: a body with no
headings at all still becomes a card (its text is the story), `_No response_`
is an absent value rather than a value, and a label nobody registered falls to
a known card kind instead of minting one the board has no column for.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openstategraph.abc.kanban_store import IKanbanStore
from openstategraph.kanban_store import (
    KANBAN_URL_ENV,
    Stage,
    column_for,
    open_kanban_store,
)

__all__ = [
    "BOARD",
    "BridgeOutcome",
    "DEFAULT_KIND",
    "FIELD_LABELS",
    "KIND_BY_LABEL",
    "apply_event",
    "card_task_id",
    "main",
    "parse_issue_form",
]

#: The third value of the `board` column that already exists on `cards`. The
#: GitHub tab is not a second integration; it is a third board.
BOARD = "github"

#: Each report field, and the heading GitHub renders it under. Pinned against
#: the template by the ticket's test — the module cannot read the template,
#: because the workflow deliberately has no checkout.
FIELD_LABELS: Mapping[str, str] = {
    "version": "Version",
    "kind": "Kind",
    "type_ids": "Node or tool type ids",
    "door": "Door",
    "refusal": "What refused",
    "check": "Check id",
    "traceback_line": "First traceback line",
    "aad_code": "Azure AD error code",
    "os": "Operating system",
    "python": "Python",
    "project_hash": "Project hash",
}

#: A GitHub label, and the card kind it means. Every value is one of
#: `cardKind.ts`'s six, because the column a card lands in is derived from the
#: kind and a seventh spelling would land it nowhere.
KIND_BY_LABEL: Mapping[str, str] = {
    "platform-gap": "bug",
    "bug": "bug",
    "enhancement": "task",
    "feature": "task",
    "documentation": "task",
    "question": "grilling",
    "decision": "decision",
    "research": "research",
}

#: What an issue with no label we know becomes. `task` rather than `bug`: a
#: card that says a fix is already decided when nobody decided one is the
#: dishonest default of the two.
DEFAULT_KIND = "task"

#: What a GitHub issue form writes for a box the reporter left empty.
_NO_RESPONSE = "_No response_"

#: `### <label>` — the heading an issue form renders each field under.
_HEADING = re.compile(r"^###[ \t]+(.+?)[ \t]*$")

#: How much of a person's prose a card carries. A card is a pointer to the
#: issue, never a copy of it — the issue is the record.
_STORY_CAP = 2000
_TITLE_CAP = 200


def card_task_id(number: int) -> str:
    """`github:issue-<number>` — the id the same issue always maps to.

    Derived from the issue number and nothing else, so every re-run of this
    workflow over one issue is the same card: an `edited` after an `opened`, a
    `reopened` a month later, a re-delivered webhook. The number is the only
    identifier GitHub guarantees is stable and unique in a repository — a title
    is edited and a body is rewritten.
    """
    return f"{BOARD}:issue-{int(number)}"


def parse_issue_form(body: str) -> dict[str, str]:
    """The template's fields, out of the body GitHub rendered.

    Tolerant: unknown headings are dropped rather than raising, `_No response_`
    is an absent value, and a body with no headings at all yields `{}` — which
    is an issue somebody filed by hand, not an error.
    """
    by_label = {label: field for field, label in FIELD_LABELS.items()}
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        heading = _HEADING.match(line)
        if heading is not None:
            current = by_label.get(heading.group(1).strip())
            if current is not None:
                found.setdefault(current, [])
            continue
        if current is not None:
            found[current].append(line)
    fields = {}
    for field, lines in found.items():
        value = "\n".join(lines).strip()
        if value and value != _NO_RESPONSE:
            fields[field] = value
    return fields


@dataclass(frozen=True)
class BridgeOutcome:
    """What one event did, and what it would like said on the issue.

    `comment` is empty whenever there is nothing to say — the workflow posts
    only what this hands it, so a run that changed nothing is silent rather
    than adding a comment per webhook.
    """

    action: str
    task_id: str
    comment: str = ""
    note: str = ""


def _kind_for(labels: Sequence[Mapping[str, Any]]) -> str:
    for label in labels:
        name = str(label.get("name", "")).strip().lower()
        if name in KIND_BY_LABEL:
            return KIND_BY_LABEL[name]
    return DEFAULT_KIND


def _story(issue: Mapping[str, Any], fields: Mapping[str, str]) -> str:
    """What the card shows: the report's own fields when the template was
    used, the person's own words when it was not, and the issue's address
    either way — a card is a pointer, and the issue is the record."""
    lines = [str(issue.get("html_url", "")).strip()]
    if fields:
        lines += [
            f"{FIELD_LABELS[field]}: {fields[field]}"
            for field in FIELD_LABELS
            if field in fields
        ]
    else:
        lines.append(str(issue.get("body", "")).strip())
    return "\n".join(line for line in lines if line)[:_STORY_CAP]


def _done_when(fields: Mapping[str, str]) -> str:
    refusal = fields.get("refusal", "").splitlines()
    if refusal and fields.get("door"):
        return (
            f"The {fields['door']} door stops answering: {refusal[0].strip()} "
            "— with the test that reproduces it green."
        )
    return (
        "The behaviour this issue reports no longer happens, and the issue "
        "carries the commit that changed it."
    )


def _priority_reason(issue: Mapping[str, Any], fields: Mapping[str, str]) -> str:
    who = str(issue.get("user", {}).get("login", "")).strip() or "somebody"
    where = f"issue #{issue.get('number')}"
    if not fields:
        return f"Filed on GitHub as {where} by {who}, without the gap template."
    install = ", ".join(
        f"{FIELD_LABELS[field]} {fields[field]}"
        for field in ("version", "os", "python")
        if field in fields
    )
    kind = fields.get("kind", "a gap")
    return f"Filed on GitHub as {where} by {who}: {kind} on an install running {install}."


def _file(issue: Mapping[str, Any], store: IKanbanStore) -> tuple[str, bool]:
    """File the card for this issue if it has none. Returns its id and whether
    this call is the one that filed it."""
    task_id = card_task_id(int(issue["number"]))
    try:
        store.read_card(task_id)
        return task_id, False
    except KeyError:
        pass
    fields = parse_issue_form(str(issue.get("body", "")))
    store.file_card(
        task_id=task_id,
        board=BOARD,
        kind=_kind_for(issue.get("labels", ())),
        category="gap" if fields else "issue",
        title=str(issue.get("title", "")).strip()[:_TITLE_CAP],
        priority="high" if fields.get("kind") == "no-backend" else "med",
        area="backend",
        priority_reason=_priority_reason(issue, fields),
        story=_story(issue, fields),
        done_when=_done_when(fields),
    )
    return task_id, True


def _resolution_comment(task_id: str, card: Any) -> str:
    resolution = (card.finished_reason or card.answer or "").strip()
    lines = [
        f"Shipped. The board card `{task_id}` is finished.",
        "",
        resolution or "No closing note was recorded on the card.",
    ]
    if card.evidence_commit:
        lines += ["", f"Commit: `{card.evidence_commit}`"]
    return "\n".join(lines)


def _unresolved_comment(task_id: str, card: Any, recorded: bool) -> str:
    tail = (
        "The close is recorded on the card as the decision it is."
        if recorded
        else (
            "The card was left where it is: the board's only road to Resolved "
            "is a failing test, its fix and the commit that carries it, and "
            "closing an issue is not that evidence."
        )
    )
    return (
        f"Closed. The board card `{task_id}` is still at `{card.stage.value}`, "
        f"so nothing here says what shipped. {tail}"
    )


def apply_event(payload: Mapping[str, Any], store: IKanbanStore) -> BridgeOutcome:
    """One GitHub event, applied to the board. Pure over both arguments.

    A payload with no issue, or one whose "issue" is a pull request, writes
    nothing: `issue_comment` fires for pull requests too, and a pull request is
    not a gap report. That is checked rather than assumed, because it is the
    one way untrusted content reaches this workflow at all.
    """
    issue = payload.get("issue")
    if not isinstance(issue, Mapping) or "number" not in issue:
        return BridgeOutcome("skipped", "", note="no issue in this payload")
    if issue.get("pull_request") is not None:
        return BridgeOutcome(
            "skipped", "", note="a pull request is not an issue this board copies"
        )

    task_id, filed = _file(issue, store)
    if payload.get("action") != "closed":
        return BridgeOutcome(
            "filed" if filed else "already-filed",
            task_id,
            note=f"{'filed' if filed else 'already on the board as'} {task_id}",
        )

    card = store.read_card(task_id)
    if card.stage is Stage.FINISHED:
        return BridgeOutcome(
            "closed-with-resolution",
            task_id,
            comment=_resolution_comment(task_id, card),
            note=f"{task_id} is finished; posting its resolution",
        )

    recorded = False
    if column_for(card) == "needsYou":
        # The one write a close legitimately makes: a judgement nobody had
        # claimed, decided by the person who closed the issue.
        recorded = store.answer_card(
            task_id,
            actor="github",
            answer=f"Closed on GitHub: {issue.get('html_url', task_id)}",
        ).ok
    return BridgeOutcome(
        "closed-unresolved",
        task_id,
        comment=_unresolved_comment(task_id, card, recorded),
        note=f"{task_id} is at {card.stage.value}; the close resolves nothing",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """The Action's one command. Every failure names what is missing.

    `openwiki-update.yml` is this repository's standing example of a workflow
    that fires on a schedule and dies for an unset secret with a message about
    interactive terminals; a run that cannot reach the board says which
    variable was empty and which secret fills it.
    """
    del argv
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not event_path:
        print(
            "GITHUB_EVENT_PATH is unset — this command reads the event GitHub "
            "wrote and is not meant to be run outside a workflow.",
            file=sys.stderr,
        )
        return 1
    if not os.environ.get(KANBAN_URL_ENV, "").strip():
        print(
            f"{KANBAN_URL_ENV} is empty. The issues workflow reads it from "
            f"`secrets.{KANBAN_URL_ENV}`; set that Actions secret to the team "
            "board's Postgres URL (docs/maintainers/public-repository-settings.md).",
            file=sys.stderr,
        )
        return 1

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    outcome = apply_event(payload, open_kanban_store())
    print(outcome.note or outcome.action)

    comment_file = os.environ.get("OPENSTATEGRAPH_BRIDGE_COMMENT_FILE", "").strip()
    if outcome.comment and comment_file:
        Path(comment_file).write_text(outcome.comment, encoding="utf-8")
        step_output = os.environ.get("GITHUB_OUTPUT", "").strip()
        if step_output:
            with open(step_output, "a", encoding="utf-8") as handle:
                handle.write("comment=written\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - the workflow's entry point
    raise SystemExit(main())
