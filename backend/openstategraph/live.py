"""Compiled workflows a host may hold, dropped the moment their package moves.

**Tier 1, semver-public.** `scale-and-adopt/14`.

`Workflows.list()` re-reads on every call, so a catalogue is live. `load()` is
not: it imports the package's `tools/*.py`, builds a model and assembles a
graph, which is per-process work, so a host that serves requests holds the
result. `docs/adoption.md` said as much — *"if you cache the compiled object
(and you should), an edit reaches your service when you drop that cache, and
otherwise on restart"* — and gave nobody anything to drop it with. The loop
that leaves is `edit -> restart -> look`, which is the difference between a
workflow editor and a workflow file editor.

    from openstategraph import LiveWorkflows

    live = LiveWorkflows("./workflows", model="anthropic:claude-sonnet-4-5")

    with live.use("billing") as billing:          # compiles, or reuses
        print(billing.ask("How much did we invoice in March?"))

---

## This is not the cache that was declined

`docs/decisions/per-request-compile-cost.md` measured **our own** request path
at 27 ms warm and refused to buy that back with a staleness class. Nothing here
changes it: `api/routes/runs.py` still compiles per request and this module is
never in that path. What ships here is for the process that was *already*
holding a compiled object for its whole life, whether it chose to or not — a
host is not paying 27 ms, it is paying a restart, and the trade the decision
refused was never the one it faced.

That decision also wrote down the invalidation list, and said a cache missing
**any** of it is worse than no cache. This module is measured against that
list rather than against a shorter one of its own.

## What decides freshness: everything under the package directory

Not the document, not a table of the globs the compiler reads. **Every file
under `<root>/<slug>/`, digested by content.**

A table would be the second copy of a set of globs `api/capability_discovery.py`
already owns (`tools/*.py`, `functions/*.py`, `middlewares/*.py`,
`skills/*.md`) and `knowledge.py` owns another row of — and this repository has
a named recurring defect about exactly that: two descriptions of one thing,
drifting, with the eighth entry added to only one of them. A subset that goes
stale by omission is the failure this whole module exists to remove.

So the digest over-includes on purpose. Editing a package's `README.md`
recompiles it. That costs 27 ms of work nobody needed; the alternative costs a
developer an afternoon on an edit that silently did not apply. The asymmetry is
not close.

**Content, never mtime.** `_import_module`'s docstring has the measurement:
`__pycache__`'s key is `(source mtime in whole seconds, size in bytes)`, and an
edit that keeps a file's length and lands in the same second as the last one is
invisible to it — `"Greets someone by name."` to `"Greets someone, warmly."`,
or `<` to `>`. A stamp built on that key would reintroduce one layer up exactly
the staleness that function bypasses the interpreter's own cache to remove.
Measured here too, on the largest shipped package (1 MB, mostly a sqlite
fixture): **1.7 ms** to digest, against 27 ms to recompile.

**Transitively, through the mounts the compiler actually reached.** A mount is
by reference, so a child's document, tools, skills and knowledge are inputs to
the parent's graph. The set comes from `CompiledWorkflow._mounts` — what the
compiler recorded while it built — rather than from re-walking the document for
`workflow.subgraph` nodes, which would be a second traversal that can disagree
with the first.

**Plus the root's own entry names.** One `scandir`, so that a mount which
resolved to nothing — the child package did not exist yet — is noticed when the
child appears. The parent's document did not change and its mount is in no
`_mounts` map, so nothing else in the stamp could see it. The cost is that
adding or deleting any package retires every held workflow, which is one
recompile each, at human-click frequency.

## What it does not cover, stated rather than discovered

- **A module a package's code imports.** `tools/f.py` is re-executed from its
  source bytes on every compile and never enters `sys.modules`, so editing
  *it* takes effect here. `import myapp.rules` inside it does not:
  `sys.modules` holds that module for the life of the process, and
  `importlib.reload` on it is refused for the reason `_import_module` records
  — a reloaded base class stops `isinstance`-matching the instances made from
  the old one. **A change to code outside the package directory needs a
  restart.** So does a `pip install`, whose entry points are discovered once
  (`extensions._CACHE`), and a rebuilt `compile/port_specs.json`, which is a
  build artifact imported at startup.
- **Provider and credential state**, item 8 of that invalidation list. The
  resolved model is built into the graph's closures and none of it is a file
  under the package. `invalidate()` is the answer for a host that rotates a
  key.

## A file watcher was not built, and this is why

A watcher is a second mechanism with a lifecycle of its own — a thread or an
inotify handle to start, to stop, and to notice has died. When it fails it
fails **silently**, which is the same failure this module exists to remove,
arriving by a different road. A `scandir` and a read on ask has no lifecycle,
cannot be orphaned, and cannot be running-but-deaf.

The in-process seam was not enough by itself either, and `api/catalogue_events`
says so in its own words: *"Only writes through the API emit."* A hand edit, a
`git pull`, or a second process serving the same directory publishes nothing.
Since the second arrangement is the one an adopter actually runs — the editor
in one process, the service in another, over one directory — a mechanism that
covered only the first would cover the easy half. The disk covers both with one
mechanism, so there is one.

`invalidate(slug)` is still there for a host that *does* have the signal, and
it is the plain callback `scale-and-adopt/12` recorded as missing: subscribe to
`GET /api/events`, or reach the broadcaster in-process through
`mounted.state.services`, and call it. It can only force a miss — it can never
keep a change from being noticed, because the stamp still decides on the next
`use()`. One truth, two ways to reach it.

## A run in flight is never disturbed

`use()` is a context manager because a *lease* is the only honest way to say
"this graph is in use". While one is open the object it yielded is never
closed, never replaced and never mutated: an edit retires the entry from the
map so the next asker compiles a fresh one, and the retired object is released
when its last lease ends. A run therefore finishes on the graph it started
with, which is the difference between an edit and a wrong answer.

Closing it any earlier would close the sqlite handles a live run is
checkpointing against — a defect that appears as a failed run, or worse a
half-written thread, rather than as anything a test of the happy path would
see.

## Concurrency

One lock per slug, held **across the compile**, so two requests arriving during
an invalidation do not both compile and cannot see two different graphs: the
second blocks, then finds the entry the first installed and reuses it. The map
lock is held only for dictionary operations and never across a compile, so a
slow package does not serialise a fast one.

**The stamp is taken before the compile, not after.** A save that lands while a
compile is running is therefore recorded as *not yet included*, and the next
`use()` compiles again. Taking it afterwards would bank the new bytes under a
graph built from the old ones and lose that edit for the life of the process —
a stale graph that no further edit can dislodge.

`use()` is synchronous, exactly like the `Workflows.load()` it wraps. An async
host calls it the way it already calls `load()`: off the event loop, through
`run_in_threadpool` or `asyncio.to_thread`. A lock that is *sometimes* awaited
would be a second concurrency model for one cache.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.store.base import BaseStore

    from openstategraph.catalogue import Workflows
    from openstategraph.loader import CompiledWorkflow

#: Directory names the digest walks past. Every one of them is something a
#: *tool* generates rather than something a developer wrote, so including them
#: would retire a package because it ran, not because it changed.
_UNSTAMPED = frozenset({"__pycache__", ".git", ".hg", ".svn", ".mypy_cache", ".pytest_cache"})

#: How many bytes are read at a time. Large enough that a 1 MB fixture is a
#: handful of reads, small enough that a package carrying something enormous
#: does not arrive in memory whole.
_CHUNK = 1 << 20


def package_stamp(directory: Path) -> str:
    """A digest of everything under one package directory. Empty if absent.

    Public because a host may want the same fact for its own reasons, and
    because a stamp nobody can print is a mechanism nobody can debug. Absent
    reads as the empty string rather than raising: a package that has been
    deleted has changed, and that is an ordinary answer.
    """
    digest = hashlib.blake2b(digest_size=16)
    for path in _walk(directory):
        digest.update(str(path.relative_to(directory)).encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _walk(directory: Path) -> Iterator[Path]:
    """Every readable file under `directory`, in one stable order.

    Sorted, because a digest that depends on the filesystem's enumeration order
    would change without the package changing. A file that vanishes between the
    listing and the read is simply skipped: the next stamp sees it gone, which
    is the same answer one instant later.
    """
    if not directory.is_dir():
        return
    for parent, directories, files in os.walk(directory, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in _UNSTAMPED)
        for name in sorted(files):
            path = Path(parent) / name
            if path.is_file() and not path.is_symlink():
                yield path


def _root_stamp(root: Path) -> str:
    """The root's own entry names — what packages exist at all.

    Names only, never their contents: what this answers is "did a package
    appear or vanish", and every package's own contents are already stamped by
    the walk above.
    """
    try:
        names = sorted(entry.name for entry in os.scandir(root))
    except OSError:
        return ""
    return hashlib.blake2b("\0".join(names).encode("utf-8", "surrogateescape"),
                           digest_size=8).hexdigest()


@dataclass
class _Held:
    """One compiled workflow, its stamp, and how many runs are inside it."""

    workflow: "CompiledWorkflow"
    #: slug -> stamp for this package and every mount the compiler reached,
    #: plus one entry for the root's listing under the empty key.
    stamps: dict[str, str]
    leases: int = 0
    #: True once something newer took its place in the map. A retired entry is
    #: handed to nobody new and closed when its last lease ends.
    retired: bool = False


class LiveWorkflows:
    """A directory of packages, compiled on ask and recompiled on change.

    Four public members and the context-manager pair, because this is a
    *holder*, not a runtime: it hands back the same `CompiledWorkflow`
    `Workflows.load()` returns, from the same function, and everything a run
    can do it does on that object.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        catalogue: "Workflows | None" = None,
        checkpointer: "BaseCheckpointSaver[Any] | None" = None,
        store: "BaseStore | None" = None,
        **defaults: Any,
    ) -> None:
        """`root` is the directory holding `<slug>/workflow.json`.

        Every other keyword is `Workflows`', with the same meaning — this
        object *is* a `Workflows` with a memory, and a second spelling of any
        of its arguments would be a second wiring path. Pass `catalogue=` to
        hand over one you already built; `root` and the rest are then ignored,
        because that object already answered them.

        **One checkpointer and one memory Store for every compile**, built here
        unless the caller supplies them. Not tidiness: an edit briefly leaves
        two compiled workflows alive for one slug, and two `SqliteSaver`s over
        one file are two `threading.Lock`s guarding nothing — the reason
        `WorkflowServices.checkpointer_for` caches at all. Sharing removes the
        overlap rather than shortening it. They are closed by `close()` when
        they are ours and left alone when they are yours.
        """
        from openstategraph.catalogue import Workflows

        if catalogue is None:
            catalogue = Workflows(root, **defaults)
        self._catalogue = catalogue
        self._checkpointer = checkpointer
        self._store = store
        self._owns_resources = checkpointer is None and store is None
        self._held: dict[str, _Held] = {}
        #: slug -> the lock that serialises compiling it. Keyed by slug rather
        #: than kept on the entry, because the case that needs it most is the
        #: one where there IS no entry yet: four requests for a package nobody
        #: has compiled would otherwise each mint a private lock and each
        #: compile. Entries are packages on disk, so it is bounded the way
        #: `WorkflowServices._workflow_checkpointers` is, and a lock is two
        #: words.
        self._gates: dict[str, threading.Lock] = {}
        self._map_lock = threading.Lock()

    @property
    def catalogue(self) -> "Workflows":
        """The `Workflows` underneath — `list()`, `published()` and `root`.

        Exposed rather than mirrored: re-declaring three methods here would be
        a second surface that can disagree with the first about what is on
        disk, and a listing was never the thing that needed a memory.
        """
        return self._catalogue

    @contextmanager
    def use(self, slug: str) -> Iterator["CompiledWorkflow"]:
        """The compiled package, for the duration of the block.

        Compiles when nothing is held for `slug`, or when anything under its
        directory — or under any package it mounts — has changed since the last
        compile. Otherwise it is the same object, and `is` says so.

        A block is a lease: the object it yields is never closed or replaced
        while you are inside it, however many edits land meanwhile. That is the
        whole reason this is a context manager and not a getter.
        """
        held = self._entry(slug)
        try:
            yield held.workflow
        finally:
            self._release(held)

    def invalidate(self, slug: str | None = None) -> None:
        """Retire what is held for `slug`, or everything when it is omitted.

        For a host that has its own signal — the `workflows.changed` frame on
        `GET /api/events`, its own save handler, a rotated credential. It can
        only force the next `use()` to compile: it is not a second source of
        truth about freshness, because the stamp still decides. Nothing is
        closed while a run is inside it.
        """
        with self._map_lock:
            retiring = list(self._held.values()) if slug is None else (
                [self._held[slug]] if slug in self._held else []
            )
            for entry in retiring:
                self._held.pop(entry.workflow.slug, None)
                entry.retired = True
            releasable = [entry for entry in retiring if entry.leases == 0]
        for entry in releasable:
            entry.workflow.close()

    def close(self) -> None:
        """Release every compiled workflow, and the two handles we opened.

        Idempotent. A workflow still leased is closed when its last lease ends,
        not here — `close()` on a holder is not a licence to break a run that
        is still going.
        """
        self.invalidate()
        if self._owns_resources:
            from openstategraph.memory import close_resource

            for resource in (self._checkpointer, self._store):
                if resource is not None:
                    close_resource(resource)
            self._checkpointer = None
            self._store = None

    def __enter__(self) -> "LiveWorkflows":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # -- internals ---------------------------------------------------------

    def _entry(self, slug: str) -> _Held:
        """The held entry for `slug`, compiled or recompiled as the stamps say.

        Two phases on purpose. The map lock answers "is there one, and is it
        still current" and is released before any compiling happens; the entry
        lock serialises the compile itself, so four requests arriving at once
        produce one graph and four leases on it.
        """
        while True:
            with self._map_lock:
                held = self._held.get(slug)
                if held is not None and self._current(held):
                    held.leases += 1
                    return held
                gate = self._gate(slug)
            with gate:
                with self._map_lock:
                    current = self._held.get(slug)
                    if current is not None and current is not held:
                        # Somebody else installed one while we waited. Ask
                        # again rather than compiling on top of it.
                        continue
                    if current is not None and self._current(current):
                        current.leases += 1
                        return current
                # Before the compile, never after: a save landing during it
                # must read as "not yet included".
                stamps = self._stamps(slug, ())
                workflow = self._catalogue.load(
                    slug,
                    checkpointer=self._resolved_checkpointer(),
                    store=self._resolved_store(),
                )
                stamps = self._stamps(slug, _mounted_slugs(workflow), taken=stamps)
                fresh = _Held(workflow=workflow, stamps=stamps, leases=1)
                with self._map_lock:
                    superseded = self._held.get(slug)
                    if superseded is not None:
                        superseded.retired = True
                        releasable = superseded.leases == 0
                    else:
                        releasable = False
                    self._held[slug] = fresh
                if superseded is not None and releasable:
                    superseded.workflow.close()
                return fresh

    def _gate(self, slug: str) -> threading.Lock:
        """The one lock compiles of `slug` queue on. Called under the map lock."""
        gate = self._gates.get(slug)
        if gate is None:
            gate = self._gates[slug] = threading.Lock()
        return gate

    def _release(self, held: _Held) -> None:
        with self._map_lock:
            held.leases -= 1
            closing = held.retired and held.leases == 0
        if closing:
            held.workflow.close()

    def _current(self, held: _Held) -> bool:
        """Does every package this graph was built from still hash the same?"""
        return all(
            self._stamp_of(slug) == stamp for slug, stamp in held.stamps.items()
        )

    def _stamps(
        self, slug: str, mounts: "tuple[str, ...]", *, taken: dict[str, str] | None = None
    ) -> dict[str, str]:
        stamps = dict(taken or {})
        for name in (slug, *mounts):
            stamps.setdefault(name, self._stamp_of(name))
        stamps.setdefault("", self._stamp_of(""))
        return stamps

    def _stamp_of(self, slug: str) -> str:
        """`""` is the root's listing; anything else is a package directory.

        A slug that will not resolve to a directory under the root — one that
        was deleted, or one a document names and nothing supplies — stamps
        empty, which is a value like any other and changes the moment a
        directory appears there.
        """
        root = self._catalogue.root
        if not slug:
            return _root_stamp(root)
        from openstategraph.api.workflow_store import InvalidSlugError

        try:
            directory = Path(root) / slug
            directory.relative_to(root)
        except (ValueError, InvalidSlugError):  # pragma: no cover - defensive
            return ""
        return package_stamp(directory)

    def _resolved_checkpointer(self) -> "BaseCheckpointSaver[Any]":
        if self._checkpointer is None:
            from openstategraph.memory import build_checkpointer

            self._checkpointer = build_checkpointer(self._catalogue.root)
        return self._checkpointer

    def _resolved_store(self) -> "BaseStore":
        if self._store is None:
            from openstategraph.memory import build_store

            self._store = build_store(self._catalogue.root)
        return self._store


def _mounted_slugs(workflow: "CompiledWorkflow") -> tuple[str, ...]:
    """Every package the compiler reached under this one, to any depth.

    Read off `MountedGraph`, which is recursive by construction, rather than
    re-walked from the document — the compiler's own account of what it built
    is the honest key, and a re-derivation is a second traversal that can
    disagree with the first.
    """
    found: list[str] = []

    def descend(mounts: Any) -> None:
        for mount in (mounts or {}).values():
            slug = getattr(mount, "slug", "")
            if slug and slug not in found:
                found.append(slug)
            descend(getattr(mount, "mounts", None))

    descend(getattr(workflow, "_mounts", None))
    return tuple(found)


__all__ = ["LiveWorkflows", "package_stamp"]
