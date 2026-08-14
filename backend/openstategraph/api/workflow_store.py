"""File-backed workflow persistence — tickets 10/14/16, resolved.

**Files own the definition.** This is the settled split from ticket 10: a
`workflow.json` under `workflows/<slug>/` is the source of truth, diffable and
git-reviewable, the same as `functions/`/`tools/` already are for the seeded
Chinook workflow. Postgres (or any runtime store) would own *execution* state
(threads, checkpoints) — out of scope here, and nothing here assumes it exists.

**The browser cannot write to disk** (ticket 16's hard constraint — the File
System Access API is Chromium-only and permission-gated, not a production
answer), so every write goes through this module, called only from the
backend. The editor posts a document; this is where it actually becomes bytes
on disk.

**Slug is frozen identity; name is not** (ticket 14's own recommendation,
argued out rather than assumed): renaming a workflow must not move its
directory, or every reference to it — and its git history — breaks. The slug
is derived once, from the name, at creation, and never changes; the display
name inside `workflow.json` can change freely.

**Minting a slug is the store's job, never a caller's** (ticket 20). A name is
not unique and never was, so `slugify` alone is a *proposal*; only something
holding the workflows directory can say whether that proposal is free. When a
caller minted its own slug and handed it to :meth:`save`, two workflows named
"My Workflow" both resolved to `my-workflow` and the second silently
overwrote the first — destroyed work, reproduced before it was fixed. So
creation is :meth:`create`, which mints and claims in one atomic step; `save`
now only ever addresses a slug the caller already holds.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# `workflows/<slug>/` sits at the repo root, the same as the seeded
# `chinook-assistant` workflow — not inside the `backend/` package (ticket 12:
# Python-package code and authored-workflow content are different things with
# different owners and different lifecycles). *Which* root that is, for a
# process that may be an installed wheel rather than this checkout, is
# `openstategraph.workflows_root`'s one job — see its docstring for what a
# constant frozen at import time cost.
from openstategraph.scaffold import WORKFLOW_DIRECTORIES
from openstategraph.workflows_root import workflows_root

_SLUG_RE = re.compile(r"[^a-z0-9]+")

#: The longest slug this store will *mint*. Not a validation rule — an existing
#: directory of any length stays loadable — but a name pasted from a document
#: title can exceed the filesystem's own 255-byte component limit, and a
#: `mkdir` that fails with `OSError: File name too long` is a 500 where a
#: shorter directory would have been fine.
_MAX_MINTED_SLUG = 60

#: The disambiguator's alphabet: digits and lowercase letters with `0`, `1`,
#: `l` and `o` removed, so a slug read aloud or copied out of a chat message
#: cannot be mistyped into a different workflow.
_SUFFIX_ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"
_SUFFIX_LENGTH = 6
#: How many disambiguated candidates to try before giving up. With 32**6 ≈ 1.07
#: billion suffixes, reaching the end means something is wrong with the disk,
#: not that the space is full — and an unbounded loop would hide that.
_MINT_ATTEMPTS = 8


def slugify(name: str) -> str:
    """A stable, filesystem- and URL-safe identity, derived once from a name.

    Never recomputed from a later rename — see the module's own docstring on
    why the slug is frozen. Falls back to a generic name rather than an empty
    string, since an empty slug would either collide with every other empty
    name or, worse, resolve to the workflows root itself.

    **A proposal, not an identity.** This is a pure name→slug transform and
    knows nothing about what is already on disk, so two workflows named the
    same get the same answer from it. :meth:`WorkflowStore.create` is what
    turns a proposal into an identity nobody else holds.
    """
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "workflow"


def _candidate_slugs(name: str) -> Iterator[str]:
    """The bare slug first, then disambiguated variants of it.

    **The first workflow of a given name keeps the clean slug.** A scheme that
    suffixed every workflow would charge every user for a collision most never
    have, and `my-workflow-k7m3qp` is a worse URL than `my-workflow` for no
    gain. The suffix is the exception, not the rule.

    The suffix is *random*, not a `-2`/`-3` counter, for two reasons. A counter
    has to be derived from what already exists, so two clients creating the
    same name at the same moment both compute `-2` and one of them still loses
    — the very failure being fixed. And a counter states how many workflows of
    that name a workspace holds, which is nobody's business in a URL. Six
    characters rather than a full uuid4: `my-workflow-k7m3qp` is short enough
    to read out and paste, where `my-workflow-3f2b9c1e-...` is a machine's
    string in a human's address bar.
    """
    base = slugify(name)[:_MAX_MINTED_SLUG].strip("-") or "workflow"
    yield base
    for _ in range(_MINT_ATTEMPTS):
        suffix = "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(_SUFFIX_LENGTH))
        yield f"{base[: _MAX_MINTED_SLUG - _SUFFIX_LENGTH - 1].strip('-')}-{suffix}"


def _broken(slug: str, reason: str) -> WorkflowSummary:
    """A row for a package that could not be read. Never published, by
    construction: rubble must not reach the customer surface even if the
    envelope it came from claimed it was published."""
    return WorkflowSummary(
        slug=slug,
        name=slug,
        saved_at="",
        node_count=0,
        edge_count=0,
        published=False,
        error=reason,
    )


def _summarize(slug: str, path: Path) -> WorkflowSummary | None:
    """One package's envelope, read and nothing else — the single place a
    `workflow.json` becomes a `WorkflowSummary`.

    Shared by `list` and `describe` on purpose: those two differ only in
    *which* packages they are willing to report, and duplicating how a row is
    built is how the two answers drift into disagreeing about the same file.

    ``None`` means there is no `workflow.json` here — the only "does not
    exist". Anything present but unreadable comes back as a `_broken` row, so
    a caller can tell "gone" from "damaged"; a file caught mid-write is
    damaged, not deleted.
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"top level is a {type(payload).__name__}, not an object")
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return _broken(slug, f"workflow.json is unreadable: {exc}")
    document = payload.get("document", payload)
    if not isinstance(document, dict):
        return _broken(slug, "workflow.json holds no document object")
    return WorkflowSummary(
        slug=slug,
        name=str(payload.get("name") or document.get("name") or slug),
        saved_at=str(payload.get("savedAt") or ""),
        node_count=len(document.get("nodes") or []),
        edge_count=len(document.get("edges") or []),
        published=payload.get("published") is not False,
        hidden=payload.get("hidden") is True,
    )


class WorkflowNotFoundError(Exception):
    pass


class SlugMintingError(Exception):
    """Raised when :meth:`WorkflowStore.create` cannot claim any candidate.

    Never expected in practice — the disambiguator has a billion values — so
    it means the workflows root is unwritable or something is racing the
    process. Its own exception rather than a silent overwrite: this is exactly
    the condition the old code resolved by writing over somebody's workflow.
    """


class InvalidSlugError(Exception):
    """Raised for a slug that cannot be a directory name under the workflows
    root — most importantly, one attempting to escape it (`..`, an absolute
    path, a path separator). Never trust a slug read from a request without
    this check; it is the one thing standing between "delete a workflow" and
    "delete an arbitrary directory this process can reach."
    """


@dataclass(frozen=True)
class WorkflowSummary:
    slug: str
    name: str
    saved_at: str
    node_count: int
    edge_count: int
    #: Ticket 04 (launch-readiness): drafts by default, publish gates /chat.
    #: An envelope without the field counts as published — back-compat for
    #: every workflow that predates the lifecycle.
    published: bool = True
    #: Why this row could not be read, for the callers that ask to see rubble
    #: (`list(include_broken=True)`). Empty on every healthy row, which is what
    #: lets `if summary.error:` be the whole check.
    error: str = ""
    #: The concierge-gateway flag (ticket 67): loadable by slug, never
    #: advertised. Always ``False`` on a row that came out of :meth:`list`,
    #: because that method filters hidden packages out — it is meaningful only
    #: on :meth:`describe`, which answers *existence* rather than visibility.
    hidden: bool = False


class WorkflowStore:
    """CRUD over `workflows/<slug>/workflow.json`.

    The root is injectable — never a module-level constant baked into the
    methods — so a test operates on a throwaway directory rather than this
    developer's real `workflows/` tree, the same reasoning `NodeRuntime`'s
    injectable tool registry and `WorkflowCompiler`'s injectable port resolver
    already follow.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        # `Path(root)`, not `root`, because a caller with a string root used to
        # get a `TypeError: unsupported operand type(s) for /: 'str' and 'str'`
        # from `directory_for` — one call later, in a different module.
        self.root = Path(root) if root else workflows_root()

    def directory_for(self, slug: str) -> Path:
        """The validated, resolved directory a slug maps to.

        Public — capability discovery (ticket 18) needs the directory to scan
        `tools/`/`functions/` under, and reaching for a `_`-prefixed method
        from outside the class would be the wrong kind of coupling for a
        genuinely reusable operation.
        """
        if not slug or slug != slugify(slug) or "/" in slug or "\\" in slug:
            raise InvalidSlugError(f"{slug!r} is not a valid workflow slug")
        candidate = (self.root / slug).resolve()
        if candidate.parent != self.root.resolve():
            raise InvalidSlugError(f"{slug!r} escapes the workflows root")
        return candidate

    def list(
        self,
        *,
        published_only: bool = False,
        include_broken: bool = False,
        include_hidden: bool = False,
    ) -> list[WorkflowSummary]:
        """Every listable package. **Reads `workflow.json` and nothing else.**

        This is the cheap half of the store, and it is cheap on purpose: it is
        what draws a picker, and compiling twenty packages to draw one is the
        cost `Workflows.list()` exists to refuse. Nothing here imports the
        runtime, executes a `tools/*.py`, or builds a model.

        `include_broken` chooses what an unreadable package *is*, and the two
        callers genuinely want opposite answers. The HTTP listing omits it — a
        customer surface must not show rubble, and the row would be
        unopenable anyway. A developer's catalogue (`Workflows.list()`) gets
        it as a row carrying `error`, because "what have I got" is exactly the
        question you ask when something is broken, and a silent omission is
        the answer that sends you looking in the wrong place.
        """
        if not self.root.exists():
            return []
        summaries: list[WorkflowSummary] = []
        for entry in sorted(self.root.iterdir()):
            summary = _summarize(entry.name, entry / "workflow.json")
            if summary is None:
                continue
            if summary.error:
                # One unreadable workflow must not blank the whole list —
                # the same reasoning `workflowStore.ts`'s `listWorkflows`
                # already applies on the frontend's own (soon to be former)
                # localStorage store.
                if include_broken:
                    summaries.append(summary)
                continue
            # A hidden workflow (the concierge gateway, ticket 67) is loadable
            # by slug but never advertised to a **customer**.
            #
            # `hidden` is a customer-surface rule, and it was being applied to
            # the developer's own catalogue too — so a developer who owns
            # `concierge` and `workflow-architect` could not see that they
            # exist, from the editor that edits them. That is ticket 21's
            # "visibility is not existence" one level up: the flag answers
            # *should a customer be offered this*, and the editor was reading
            # it as *is there anything here*.
            if summary.hidden and not include_hidden:
                continue
            # Draft → publish lifecycle (ticket 04): `published` is a sibling
            # of `hidden` on the envelope. A missing field means published —
            # the back-compat default — and `hidden` above trumps it.
            if published_only and not summary.published:
                continue
            summaries.append(summary)
        return sorted(summaries, key=lambda s: s.saved_at, reverse=True)

    def describe(self, slug: str) -> WorkflowSummary | None:
        """What this **one** package is — or ``None`` when there is no such
        package on disk.

        The existence question, kept apart from :meth:`list`'s visibility
        question (ticket 21). `list` answers *what a surface advertises*, and
        it is right to omit hidden packages and rubble from that answer; but
        absence from a surface is not absence from the disk, and a caller that
        reads it as such reports a live file as deleted. `concierge` and
        `workflow-architect` are `hidden: true`, served 200 by
        ``GET /api/workflows/{slug}``, and were exactly what the editor's file
        watch kept declaring "deleted on disk".

        So this reports every package the store can name: hidden ones with
        ``hidden=True``, unreadable ones as a `_broken` row carrying `error`.
        Only "there is no `workflow.json` under this slug" is ``None``, and
        that is the one condition a caller may treat as deletion.

        Raises `InvalidSlugError` rather than answering ``None`` for a slug
        that cannot name a directory at all: "you asked a malformed question"
        and "the package is gone" are the two answers this method exists to
        keep apart, so it must not collapse them either.
        """
        return _summarize(slug, self.directory_for(slug) / "workflow.json")

    def load(self, slug: str) -> dict[str, Any]:
        path = self.directory_for(slug) / "workflow.json"
        if not path.is_file():
            raise WorkflowNotFoundError(slug)
        payload = json.loads(path.read_text())
        # Documents saved before the envelope existed (or a hand-authored
        # workflow.json with no envelope at all) are the document itself.
        document: dict[str, Any] = payload.get("document", payload)
        return document

    def create(self, *, name: str, document: dict[str, Any], saved_at: str) -> str:
        """Mint an unused slug for `name`, write the package, return the slug.

        **This is the only way to bring a workflow into existence**, and it
        exists because the alternative was silent data loss (ticket 20): the
        editor used to `slugify` a name client-side and PUT to it, so a second
        workflow named "My Workflow" landed on the first one's `my-workflow`
        directory and overwrote it with no error, no prompt and no trace.

        The claim is `mkdir(exist_ok=False)`, and that choice is the whole
        safety argument. Asking first and writing second — `describe(slug) is
        None`, then write — is a check-then-act race: two requests can both
        find the slug free. `mkdir` *is* the check, performed by the
        filesystem, atomically. It also answers the question a listing cannot:
        `list()` omits hidden packages by design (ticket 21), so scanning it
        for a free name would happily mint `concierge` on top of the live
        gateway; a directory has no opinion about visibility.

        Rubble counts as taken. A directory holding no readable
        `workflow.json` is still somebody's half-written package or a `tools/`
        folder created by hand, and quietly moving in on top of it is the
        behaviour this method exists to remove.
        """
        for slug in _candidate_slugs(name):
            directory = self.directory_for(slug)
            try:
                directory.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                continue
            # A package, not a lone document. `openstategraph new` lays these
            # out and the editor did not, so the two doors onto "make me a new
            # workflow" disagreed — and the palette tells a developer that
            # "Python tools in its tools/ folder show up here", advice naming a
            # directory the editor never created.
            #
            # Read from `scaffold`, never re-listed: a second copy is a copy
            # that drifts the day a directory is added.
            for name_of in WORKFLOW_DIRECTORIES:
                (directory / name_of).mkdir(exist_ok=True)
            self._write(directory, name=name, document=document, saved_at=saved_at, is_new=True)
            return slug
        raise SlugMintingError(
            f"could not find a free directory for {slugify(name)!r} "
            f"after {_MINT_ATTEMPTS + 1} attempts"
        )

    def save(self, slug: str, *, name: str, document: dict[str, Any], saved_at: str) -> None:
        """Overwrite the package at `slug` — a slug the caller already holds.

        Deliberately still create-or-overwrite, because the slug is in the
        path: naming a directory explicitly is how a script, the CLI or a test
        writes a package it intends to own. What must never mint a slug by
        guessing is the editor, and it no longer does — it calls
        :meth:`create` and is told which slug it got.
        """
        directory = self.directory_for(slug)
        # The *package*, not the directory, is what already exists: ticket 20's
        # `create` claims the directory before anything is written into it, and
        # a directory somebody made by hand for `tools/` is not a workflow
        # either. Both used to count as "not new", so neither got its
        # `AGENTS.md` or its draft flag.
        is_new = not (directory / "workflow.json").is_file()
        directory.mkdir(parents=True, exist_ok=True)
        self._write(directory, name=name, document=document, saved_at=saved_at, is_new=is_new)

    def _write(
        self,
        directory: Path,
        *,
        name: str,
        document: dict[str, Any],
        saved_at: str,
        is_new: bool,
    ) -> None:
        """The bytes, once — shared by :meth:`create` and :meth:`save`.

        The two differ only in how the directory came to be claimed; what a
        `workflow.json` looks like is one piece of knowledge and lives here.
        """
        slug = directory.name
        payload = {"version": 1, "name": name, "savedAt": saved_at, "document": document}
        if is_new:
            # Ticket 04: a workflow born in the editor is a DRAFT. Publishing
            # (set_published) is a deliberate, separate act.
            payload["published"] = False
        else:
            # A resave must not churn lifecycle fields it does not own: carry
            # `published`/`hidden` over exactly as they were — including their
            # absence, so a pre-lifecycle envelope stays implicitly published.
            try:
                previous = json.loads((directory / "workflow.json").read_text())
            except (json.JSONDecodeError, OSError):
                previous = {}
            for key in ("published", "hidden"):
                if key in previous:
                    payload[key] = previous[key]
        # Two-space indent, trailing newline, sorted-by-the-serializer-not-here
        # keys: `workflow.json`'s own determinism is ticket 19's job upstream
        # of this — this just needs to not *add* nondeterminism on top of a
        # document that already sorts its own nodes/edges.
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        (directory / "workflow.json").write_text(text)

        if is_new:
            # Cheapest thing that makes the directory legible to a coding
            # agent, per ticket 14's own recommendation — deliberately not
            # `graph.py`: an empty or stub entry point invites exactly the
            # "assumed load-bearing, found nothing" trap the ticket warns
            # against. Generation is a separate, explicit export step
            # (ticket 15), not something a save silently produces.
            (directory / "AGENTS.md").write_text(_agents_md(name, slug))

    def duplicate(self, slug: str, *, name: str, saved_at: str) -> str:
        """Copy the whole package at `slug` to a freshly minted slug (ticket 01).

        **A backend operation, because only this side can copy the package.**
        The client-side alternative — load the document, create a new workflow
        from it — copies `workflow.json` and nothing else, producing a
        workflow whose nodes bind to tools that are not there. That fails at
        *run* time, long after the copy appeared to succeed.

        Three things the copy deliberately does not inherit:

        - **The slug**, which is frozen at creation and is the package's
          identity. A duplicate is a new package, never a second name for one
          directory.
        - **`published`**, because publishing is a decision about a specific
          package and inheriting it silently puts something on `/chat` that
          nobody chose to put there. `_write(is_new=True)` marks it a draft.
        - **`AGENTS.md`**, which names its own slug and would otherwise tell a
          coding agent to open the original. It is rewritten, not copied.

        Mounts inside the copied document are left exactly as they are: they
        reference *other* packages by slug, and the copy legitimately shares
        them.

        The claim on the new directory is `create`'s — `mkdir(exist_ok=False)`
        walking `_candidate_slugs` — so two duplicates racing for one name
        cannot land on the same directory. Everything is copied **into** that
        claimed directory rather than the tree being copied wholesale, because
        the claim has to come first to be worth anything.
        """
        source = self.directory_for(slug)
        if not (source / "workflow.json").is_file():
            raise WorkflowNotFoundError(slug)
        document = self.load(slug)

        for candidate in _candidate_slugs(name):
            directory = self.directory_for(candidate)
            try:
                directory.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                continue
            shutil.copytree(
                source,
                directory,
                dirs_exist_ok=True,
                # Bytecode compiled against the original's path: not source,
                # and noise in a package that is one second old.
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            # Last, and over whatever was copied: this is what makes the copy a
            # draft under its own name, and rewrites `AGENTS.md` for the new
            # slug.
            self._write(directory, name=name, document=document, saved_at=saved_at, is_new=True)
            return candidate
        raise SlugMintingError(
            f"could not find a free directory for {slugify(name)!r} "
            f"after {_MINT_ATTEMPTS + 1} attempts"
        )

    def set_published(self, slug: str, published: bool) -> None:
        """Flip the draft→publish flag in place, touching nothing else.

        Rewrites only the envelope's `published` field; `savedAt`, `hidden`
        and the document stay byte-identical apart from that one key, so the
        editor's file watch never mistakes a publish for a content change it
        must reload.
        """
        path = self.directory_for(slug) / "workflow.json"
        if not path.is_file():
            raise WorkflowNotFoundError(slug)
        payload = json.loads(path.read_text())
        payload["published"] = published
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def delete(self, slug: str) -> None:
        directory = self.directory_for(slug)
        if not directory.exists():
            raise WorkflowNotFoundError(slug)
        shutil.rmtree(directory)


def _agents_md(name: str, slug: str) -> str:
    return (
        f"# {name}\n\n"
        f"An OpenStateGraph workflow. `workflow.json` in this directory is the "
        "source of truth for its nodes and edges — edit it through the "
        "editor, not by hand, unless you know the canonical serialization "
        "rules (ticket 19: sorted nodes, content-addressed edges, no "
        "written edge ids).\n\n"
        f"- **Run it**: `POST /api/runs` or `/api/runs/stream` with this "
        f"directory's `workflow.json` as the `workflow` field, or open "
        f"`{slug}` in the editor and use Chat.\n"
        "- **Tools / functions** this workflow's nodes can bind to live in "
        "`tools/` and `functions/` alongside this file, once added.\n"
        "- **Tests** for any hand-written tool/function code belong in "
        "`tests/`.\n"
    )


# No `__all__` here on purpose. In Python `__all__` reads as "this is the
# public surface", and this module is Tier 3 — internal, no stability
# guarantee (see `openstategraph/api/__init__.py`). The names it exported
# were the ones it hands its own siblings, and a third party would have read
# that as a promise. `openstategraph.__all__` and `openstategraph.abc` are
# the promises.


def validate_package(workflow_dir: Path) -> list[str]:
    """Findings for one workflow package against the contract (ticket 49).

    The contract: `workflow.json` (envelope) required; `AGENTS.md` expected;
    `tools/ functions/ middlewares/ skills/ tests/ data/` optional and
    discovered by convention. Findings are strings a human acts on —
    "error: ..." blocks running, "warning: ..." is advice. Never raises:
    a broken package must be reportable, not un-listable.
    """
    findings: list[str] = []
    manifest = workflow_dir / "workflow.json"
    if not manifest.is_file():
        return [f"error: no workflow.json in {workflow_dir.name}/"]
    try:
        payload = json.loads(manifest.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return [f"error: workflow.json unreadable ({exc})"]
    document = payload.get("document", payload)
    if not isinstance(document.get("nodes"), list):
        findings.append("error: document has no nodes list")
    if not (workflow_dir / "AGENTS.md").is_file():
        findings.append("warning: no AGENTS.md — collaborators (and agents) have no orientation")
    if (workflow_dir / "tools").is_dir() and not (workflow_dir / "tests").is_dir():
        findings.append("warning: tools/ without tests/ — hand-written code with no guard")
    return findings
