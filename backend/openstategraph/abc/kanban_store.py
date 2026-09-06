"""The card store ladder: ``IKanbanStore`` → ``AbstractKanbanStore`` →
``SqliteKanbanStore`` — `team-board-and-gap-reports/02`.

## Why the middle rung earns its place

`CLAUDE.md` asks for the decision rather than the habit — *"inheritance must
earn itself; where a hierarchy exists only to share two fields, use composition
and say so"* — so here is the argument, in one sentence:

**Every refusal in this family is pure, and every write it guards is not.**

`set_stage`'s evidence gate and stage ordering, `file_idea_card`'s brief check,
`answer_card`'s two refusals and the first-wins claim are all decisions about a
`Card` that no storage engine can have an opinion about. The write each one
guards is a single conditional `UPDATE` that only an engine can perform. A
ladder with no middle rung would hand a second store the gate along with the
write — and a second store reimplementing `set_stage`'s
`UPDATE ... WHERE stage = ?` would reintroduce `kanban-patrol/13`'s lost card on
the one board where two claimants racing stops being hypothetical.

So the base owns every decision and declares five primitives — `_insert_card`,
`_fetch_card`, `_advance_stage`, `_reset_card`, `_record_answer` — and a
concrete store implements those plus `list_cards` and `store_digest`. Two of
those primitives return a `bool` that means *the conditional write matched*: the
base turns that into the honest sentence a loser is told, which is the half of
the concurrency guarantee that is prose rather than SQL.

## What is deliberately not here

`triage`, `column_for`, `card_row`, `flagged_stale`, `unresolved_blockers` and
`resolve_blocked_by` are **rules**, not storage. They stay module-level
functions in `kanban_store.py`, off this interface, so a second store cannot
disagree with the order the board is worked in or with which column a card is
in. `IKanbanStore` reads and writes a card, lists, and says whether anything
changed — `CLAUDE.md`'s **I**, and nothing else.

No CLI, no MCP tool, no HTTP route either: those are thin adapters over
`open_kanban_store()`, so the claim/stage logic exists exactly once.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from openstategraph.kanban_store import (
    BOARD_AREAS,
    BOARD_PRIORITIES,
    IDEA_KINDS,
    Card,
    CardEvidence,
    MissingEvidenceError,
    SetStageResult,
    Stage,
    StageOrderError,
    column_for,
    flagged_stale,
    idea_task_id,
    now_iso,
    required_previous_stage,
    resolve_blocked_by,
)


@runtime_checkable
class IKanbanStore(Protocol):
    """What every consumer of a board depends on — the CLI's `kanban` verbs,
    the MCP `kanban_*` tools, the HTTP routes, the patrol, and the change
    watcher behind the board's live stream. Consumers import this, never a
    class (`CLAUDE.md`)."""

    def file_card(
        self,
        *,
        task_id: str,
        board: str,
        kind: str,
        category: str,
        title: str,
        priority: str = "med",
        area: str = "backend",
        priority_reason: str = "",
        story: str = "",
        done_when: str = "",
        gap_evidence: str = "",
    ) -> None: ...

    def file_idea_card(
        self,
        *,
        project_id: str,
        kind: str,
        title: str,
        story: str,
        done_when: str,
        priority: str,
        priority_reason: str,
        area: str = "backend",
        actor: str = "",
        blocked_by: Sequence[str] = (),
        agent_model: str = "",
        agent_effort: str = "",
    ) -> str: ...

    def read_card(self, task_id: str) -> Card: ...

    def list_cards(self) -> list[Card]: ...

    def set_stage(
        self,
        task_id: str,
        stage: Stage,
        *,
        actor: str,
        test_id: str = "",
        reason: str = "",
        commit: str = "",
    ) -> SetStageResult: ...

    def release_card(
        self, task_id: str, *, threshold_seconds: int = 3600
    ) -> SetStageResult: ...

    def answer_card(self, task_id: str, *, actor: str, answer: str) -> SetStageResult: ...

    def store_digest(self) -> str: ...


class AbstractKanbanStore(ABC):
    """Every rule in the family, over five primitives a store supplies."""

    # -- what a concrete store must supply ---------------------------------

    @abstractmethod
    def list_cards(self) -> list[Card]:
        """Every card. Empty, never an error, when nothing has been filed."""

    @abstractmethod
    def store_digest(self) -> str:
        """Opaque, compared and never parsed. An absent store has one too."""

    @abstractmethod
    def _insert_card(self, card: Card) -> bool:
        """Insert if this id is free; `False` when it was already taken. The
        two filings differ only in what the base does with that `False`."""

    @abstractmethod
    def _fetch_card(self, task_id: str) -> Card | None:
        """`None` for both "no card" and "no store" — the caller cannot act
        differently on the two, and `kanban_store_location` is the door that
        tells them apart for a reader who can."""

    @abstractmethod
    def _advance_stage(
        self,
        task_id: str,
        *,
        required_previous: Stage,
        stage: Stage,
        actor: str,
        heartbeat: str,
        evidence: CardEvidence,
    ) -> bool:
        """One conditional write, guarded on `required_previous`. `False`
        means the card had already moved — never a read-then-write."""

    @abstractmethod
    def _reset_card(self, task_id: str) -> bool:
        """Back to filed-but-never-attended, evidence included, guarded on the
        card not already being unattended."""

    @abstractmethod
    def _record_answer(self, task_id: str, *, answer: str, actor: str, at: str) -> bool:
        """One conditional write, guarded on the answer still being blank and
        the card still being unattended."""

    # -- the rules ---------------------------------------------------------

    def read_card(self, task_id: str) -> Card:
        card = self._fetch_card(task_id)
        if card is None:
            raise KeyError(task_id)
        return card

    def file_card(
        self,
        *,
        task_id: str,
        board: str,
        kind: str,
        category: str,
        title: str,
        priority: str = "med",
        area: str = "backend",
        priority_reason: str = "",
        story: str = "",
        done_when: str = "",
        gap_evidence: str = "",
    ) -> None:
        """The patrol's write. `kanban-patrol/02`: once a card leaves
        `unattended`, a re-patrol must never touch it again — enforced by the
        caller, not here; this is the initial file only, and a second patrol
        filing the same `task_id` is a no-op rather than an error.

        `priority`/`area` default rather than require an argument at every call
        site that does not yet have an opinion; a real patrol (`07`/`08`) is
        expected to always pass both explicitly.

        `story`/`done_when` default the same way and for a related reason —
        `team-board-and-gap-reports/05`. A patrol card justifies itself with
        the run it was minted from, so it needs neither; a card copied from a
        GitHub issue has a person's own account of the gap and the check that
        settles it, and dropping those would put a title on the board with the
        report thrown away. Not a reason to route that filing through
        `file_idea_card`, which mints its own id from the title and forces
        `board="workflows"` — an issue's identity is its number, on the
        `github` board.

        `gap_evidence` is the third to default that way, and its reason is the
        narrowest yet (`team-board-and-gap-reports/15`): only a patrol card
        minted from a finding a gap report can be built from carries one, and
        the emptiness of every other card is what lets the report door refuse
        a hand-filed card by name instead of guessing at it.
        """
        self._insert_card(
            Card(
                task_id=task_id,
                board=board,
                kind=kind,
                category=category,
                title=title,
                stage=Stage.UNATTENDED,
                actor=None,
                last_heartbeat_at=None,
                priority=priority,
                area=area,
                priority_reason=priority_reason,
                filed_at=now_iso(),
                evidence_test_id="",
                evidence_red_reason="",
                evidence_green=False,
                evidence_commit="",
                answer="",
                answered_by="",
                answered_at="",
                story=story.strip(),
                done_when=done_when.strip(),
                gap_evidence=gap_evidence.strip(),
            )
        )

    def file_idea_card(
        self,
        *,
        project_id: str,
        kind: str,
        title: str,
        story: str,
        done_when: str,
        priority: str,
        priority_reason: str,
        area: str = "backend",
        actor: str = "",
        blocked_by: Sequence[str] = (),
        agent_model: str = "",
        agent_effort: str = "",
    ) -> str:
        """File a card out of a conversation — `osg-agent-experience/25`.
        Returns its `task_id`.

        **Not `file_card` with more arguments.** That one writes what a patrol
        found, and its whole justification is the run thread behind it, which
        any later reader can go and look at. This one writes what somebody
        *said they wanted*, and the chat log it came from is not a thing the
        next reader can open. So the brief is required here and defaulted
        there: an empty `story` is precisely the shape the lost conversation
        would take on the card.

        **And it refuses a duplicate rather than ignoring it.** A patrol re-run
        seeing the same finding is one card; here a collision means two
        different ideas were given one title, and silently keeping the first
        would lose the second with nothing said. The caller renames.

        `actor` is who filed it, and it goes in the same column a claimant's
        name goes in — the card is still `unattended`, so the first `attend`
        overwrites it with whoever takes the work, which is the honest reading
        of that column either way: the person this card is currently with.
        """
        if kind not in IDEA_KINDS:
            raise ValueError(
                f"kind {kind!r} is not one this door files — use one of "
                f"{', '.join(sorted(IDEA_KINDS))}"
            )
        if priority not in BOARD_PRIORITIES:
            raise ValueError(
                f"priority {priority!r} is not one of {', '.join(BOARD_PRIORITIES)}"
            )
        if area not in BOARD_AREAS:
            raise ValueError(f"area {area!r} is not one of {', '.join(BOARD_AREAS)}")
        for name, value in (
            ("story", story),
            ("done_when", done_when),
            ("priority_reason", priority_reason),
        ):
            if not value.strip():
                raise ValueError(
                    f"{name} is empty — a card filed from a conversation carries "
                    "its brief or the brief is lost with the conversation"
                )

        task_id = idea_task_id(project_id, title)
        known = frozenset(card.task_id for card in self.list_cards())
        resolved_blockers = resolve_blocked_by(project_id, blocked_by, known)
        inserted = self._insert_card(
            Card(
                task_id=task_id,
                board="workflows",
                kind=kind,
                category="idea",
                title=title.strip(),
                stage=Stage.UNATTENDED,
                actor=actor.strip() or None,
                last_heartbeat_at=None,
                priority=priority,
                area=area,
                priority_reason=priority_reason.strip(),
                filed_at=now_iso(),
                evidence_test_id="",
                evidence_red_reason="",
                evidence_green=False,
                evidence_commit="",
                answer="",
                answered_by="",
                answered_at="",
                story=story.strip(),
                done_when=done_when.strip(),
                blocked_by=resolved_blockers,
                agent_model=agent_model.strip(),
                agent_effort=agent_effort.strip(),
            )
        )
        if not inserted:
            existing = self.read_card(task_id)
            raise ValueError(
                f"{task_id} already exists ({existing.title!r}) — two ideas cannot "
                "share one title; name this one differently"
            )
        return task_id

    def set_stage(
        self,
        task_id: str,
        stage: Stage,
        *,
        actor: str,
        test_id: str = "",
        reason: str = "",
        commit: str = "",
    ) -> SetStageResult:
        """The one write path.

        **Attend (`stage == ATTENDED`) is a race, not a logic error** — two
        coding agents legitimately racing for one card is `kanban-patrol/13`'s
        own finding, so a conflict here is reported through
        `SetStageResult.ok`, told plainly who won, never raised.

        **Every later transition (red/green/finished) is a logic error, not a
        race** — only the actor that already holds the card advances it, so a
        mismatch there (skipping a stage, moving backward) is the caller's own
        mistake and raises `StageOrderError`.

        **`kanban-patrol/17`+`21`: the evidence gate.** Checked before the
        conditional write, same as the stage-order check — a card only reaches
        `red` with a test id and a reason, only reaches `green` with the *same*
        test id already recorded at `red`, and only reaches `finished` once red
        and green are both already durably on the row.

        **`osg-agent-experience/85`: `reason` is answered at every stage.** It
        is kept at `red` (the failing test's story) and at `finished` (the
        closing gate's output), and refused by name at `attended` and `green`,
        which keep none. Accepting a value and dropping it is the defect the
        ticket was filed for; `kanban-patrol/33` set the precedent by refusing
        a mismatched `test_id` at `finished` rather than widening anything.
        """
        if not actor.strip():
            # `kanban-patrol/20`: the floor, not full identity. "already
            # attended by " with nothing in the blank is meaningless to a
            # human reading the card, so an actor must be non-blank.
            raise MissingEvidenceError(
                f"{task_id}: actor must be a real, non-blank name"
            )

        current = self.read_card(task_id)
        required_previous = required_previous_stage(stage)

        if stage == Stage.ATTENDED:
            # Attend is a race only between UNATTENDED (fresh) and ATTENDED
            # (someone else just won it). Anything already past attended is
            # not a race at all: it is moving backward on a card the actor
            # already progressed, a logic error.
            if current.stage not in (Stage.UNATTENDED, Stage.ATTENDED):
                raise StageOrderError(
                    f"{task_id}: cannot move from {current.stage.value} back to "
                    f"{stage.value} — stage only ever advances"
                )
        elif stage == Stage.FINISHED:
            # Ordering for `finished` is enforced by the evidence check below,
            # not here: `evidence_green` can only be True once a `green`
            # transition has happened, and `green` only after `red` — so a
            # complete-evidence check already implies the correct stage was
            # reached. Checking literal order here as well would reject
            # red -> finished with `StageOrderError` rather than the more
            # specific `MissingEvidenceError` this gate exists to raise.
            pass
        elif current.stage != required_previous:
            raise StageOrderError(
                f"{task_id}: cannot move from {current.stage.value} to "
                f"{stage.value} — stage only ever advances, one step at a time"
            )

        # `kanban-patrol/17`+`21`, hardened: `.strip()` before every truthiness
        # check below. `bool(" ")` is `True` in Python, so `reason=" "` passed
        # this gate silently until that fix; a whitespace string is exactly as
        # meaningless as an empty one to anyone reading a card's evidence.
        test_id = test_id.strip()
        reason = reason.strip()
        commit = commit.strip()

        evidence = CardEvidence(
            test_id=current.evidence_test_id,
            red_reason=current.evidence_red_reason,
            green=current.evidence_green,
            commit=current.evidence_commit,
            finished_reason=current.finished_reason,
        )

        if stage == Stage.RED:
            if not test_id:
                raise MissingEvidenceError(f"{task_id}: red requires test_id")
            if not reason:
                raise MissingEvidenceError(f"{task_id}: red requires reason")
            evidence = evidence.replace(test_id=test_id, red_reason=reason)
        elif stage == Stage.GREEN:
            if not test_id:
                raise MissingEvidenceError(f"{task_id}: green requires test_id")
            self._require_matching_test_id(
                task_id, "green", test_id, current.evidence_test_id
            )
            self._require_no_reason(task_id, "green", reason)
            evidence = evidence.replace(green=True)
        elif stage == Stage.ATTENDED:
            self._require_no_reason(task_id, "attended", reason)
        elif stage == Stage.FINISHED:
            # `kanban-patrol/33`: `test_id` is optional at `finished` — the
            # recorded id from `red`/`green` is the evidence — but when an
            # agent does supply one it is checked against that recorded id
            # rather than read for `commit` alone and silently dropped.
            self._require_matching_test_id(
                task_id, "finished", test_id, current.evidence_test_id
            )
            # `kanban-patrol/17`'s own bar names four things, not three — "the
            # commit or diff that carries the work" is the fourth.
            missing = []
            if not current.evidence_test_id:
                missing.append("test_id")
            if not current.evidence_red_reason:
                missing.append("red reason")
            if not current.evidence_green:
                missing.append("green")
            if not commit:
                missing.append("commit")
            if missing:
                raise MissingEvidenceError(
                    f"{task_id}: finished requires evidence — missing "
                    f"{', '.join(missing)}"
                )
            evidence = evidence.replace(commit=commit, finished_reason=reason)

        wrote = self._advance_stage(
            task_id,
            required_previous=required_previous,
            stage=stage,
            actor=actor,
            heartbeat=now_iso(),
            evidence=evidence,
        )

        if not wrote:
            if stage != Stage.ATTENDED:
                # A concurrent second advance of an already-progressed card is
                # not a race this schema allows at all (only the holder calls
                # these) — treated the same as any other order violation.
                raise StageOrderError(
                    f"{task_id}: cannot move to {stage.value} — card is no longer "
                    f"at {required_previous.value}"
                )
            # Lost the attend race between the read above and this write —
            # reread to report who actually holds it, truthfully.
            loser_view = self.read_card(task_id)
            return SetStageResult(
                ok=False,
                reason=(
                    f"already attended by {loser_view.actor} — card is at "
                    f"{loser_view.stage.value}"
                ),
            )
        return SetStageResult(ok=True)

    def release_card(
        self, task_id: str, *, threshold_seconds: int = 3600
    ) -> SetStageResult:
        """The human half of "flag, never auto-release" — `kanban-patrol/19`.

        `flagged_stale` only ever reports; nothing writes on its own. This is
        the one function a human's own explicit press calls, and it is guarded
        twice:

        - **A card must already be flagged.** A human can only release what the
          system has already named as stale, never an arbitrary active card by
          accident — the button cannot invent staleness.
        - **Atomic against the store.** A genuine resume landing between the
          check and the write must not be silently clobbered; no rows written
          is treated exactly like "no longer stale".

        A successful release resets the row to a fresh, unattended state, all
        five evidence fields included, so the card looks exactly as if nobody
        had ever touched it. A partial reset would leave stale evidence to
        bleed into whoever attends next.
        """
        refusal = SetStageResult(
            ok=False,
            reason=(
                f"{task_id}: not stale — a card can only be released once it "
                "has been flagged"
            ),
        )
        if task_id not in flagged_stale(self, threshold_seconds=threshold_seconds):
            return refusal
        return SetStageResult(ok=True) if self._reset_card(task_id) else refusal

    def answer_card(self, task_id: str, *, actor: str, answer: str) -> SetStageResult:
        """Record the decision a person made on a Needs You card —
        `kanban-patrol/15`, the owner's decision of 2026-09-04.

        **The card goes back to Detected, never to Resolved.** A decision is
        not evidence that anything was built, so `17`'s gate is still the only
        road to Resolved; and the card must not stay in Needs You either,
        because that is the column a person reads for outstanding questions.
        `column_for` does the move on its own, from the answer this writes.

        **One write path, and it writes once.** The stage is untouched. Two
        refusals and one loss:

        - A blank actor or a blank answer is `MissingEvidenceError`.
        - A card that is not a judgement waiting in Needs You is
          `StageOrderError`.
        - A **second** answer is a race, not a mistake — two people reading one
          board and both deciding is ordinary — so it is reported through
          `SetStageResult.ok` naming who answered first, and the first
          decision stands.
        """
        if not actor.strip():
            raise MissingEvidenceError(
                f"{task_id}: actor must be a real, non-blank name"
            )
        answer = answer.strip()
        if not answer:
            raise MissingEvidenceError(
                f"{task_id}: answer must be a real, non-blank decision"
            )

        current = self.read_card(task_id)
        if current.answer.strip():
            return self._already_answered(current)
        if column_for(current) != "needsYou":
            raise StageOrderError(
                f"{task_id}: not waiting on a decision — a {current.kind} card at "
                f"{current.stage.value} is in {column_for(current)}, and only a "
                "judgement nobody has claimed carries a question to answer"
            )

        if self._record_answer(task_id, answer=answer, actor=actor, at=now_iso()):
            return SetStageResult(ok=True)

        # Lost between the read above and this write — reread and report who
        # actually holds the decision, truthfully, never a silent overwrite.
        loser_view = self.read_card(task_id)
        if loser_view.answer.strip():
            return self._already_answered(loser_view)
        return SetStageResult(
            ok=False,
            reason=(
                f"{task_id}: no longer waiting on a decision — card is at "
                f"{loser_view.stage.value}"
            ),
        )

    @staticmethod
    def _already_answered(card: Card) -> SetStageResult:
        return SetStageResult(
            ok=False,
            reason=(
                f"{card.task_id}: already answered by {card.answered_by} "
                f"at {card.answered_at} — an answer is written once"
            ),
        )

    @staticmethod
    def _require_matching_test_id(
        task_id: str, stage_word: str, test_id: str, recorded: str
    ) -> None:
        """The one sentence `green` and `finished` both need when a supplied
        `test_id` disagrees with the one recorded at `red` — `kanban-patrol/33`
        found `finished` reading this same parameter and silently ignoring it.
        A blank `test_id` is not a mismatch here; callers that require one
        non-blank (`green`) check that separately before calling this."""
        if test_id and test_id != recorded:
            raise MissingEvidenceError(
                f"{task_id}: {stage_word} test_id {test_id!r} does not match the "
                f"red test_id {recorded!r} recorded on this card"
            )

    @staticmethod
    def _require_no_reason(task_id: str, stage_word: str, reason: str) -> None:
        """`osg-agent-experience/85`. The two stages that keep no reason say so
        rather than dropping one — and they name the two that do, because a
        caller with something to record needs to be told where it goes, not
        only that this is not the place."""
        if reason:
            raise MissingEvidenceError(
                f"{task_id}: {stage_word} keeps no reason — a reason is recorded "
                "at red (why the test fails) and at finished (what the closing "
                "checks said); pass it at one of those, not here"
            )
