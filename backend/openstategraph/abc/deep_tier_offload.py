"""Progressive skill loading and tool-result offload — the deep-tier seam.

`launch-readiness/101` and `102` share one seam: `AbstractAgentNode.SLOT_ORDER`
already names `"skills"` and `"filesystem"` and nothing fills either. Both
built here as plain functions/middleware that a compiler contributes into
`resolve_middleware()`'s slot table — never a new base member, never a new
node type. `docs/decisions/nl2sql-lens-layer.md` records why `create_deep_agent`'s
own `skills=` kwarg is not the seam (it wants `StateBackend` + `invoke(files=)`,
which nothing provisions for a compiled node).

Both middlewares are built on `deepagents.backends.FilesystemBackend` in its
default `virtual_mode=True`, which is the jail: path traversal (`..`, `~`)
and root escapes are rejected, and every operation returns a result object
with `.error` set rather than raising — confirmed by reading
`FilesystemBackend._resolve_path` and its callers (`write_file`, `read_file`,
`edit_file`, `grep`, `glob`) in the installed `deepagents==0.7.5`. This module
does not reimplement that guarantee; it only relies on it.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from deepagents.backends import FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

#: Default: a tool result whose text exceeds this many characters is a
#: candidate for offload. Below it, inlining is cheaper than a file written
#: and read back (`launch-readiness/102`, "Watch for").
DEFAULT_OFFLOAD_THRESHOLD_CHARS = 4000


def build_skills_middleware(
    *, backend: Any, sources: Sequence[str | tuple[str, str]]
) -> SkillsMiddleware:
    """Fills the `"skills"` slot: name + description now, body on demand.

    `SkillsMiddleware` accepts any `BackendProtocol`, not only `StateBackend`
    — `FilesystemBackend` reads skill files straight off disk, so no caller
    has to provision `invoke(files={...})`. The library's own system prompt
    fragment lists each skill's name and description; the body is read later
    by the agent's own `read_file` tool, on the path shown in that list.

    It takes the **store**, not a directory, and takes the *same* one the
    offload seam and the tier's own file tools were given
    (`launch-readiness/149`). The library lists skills in `before_agent`, at
    run time, so a second backend of its own would list a different thread's
    store than the one the paths it prints resolve in — the dangling-pointer
    failure `surface_can_dereference` exists to prevent, reintroduced one
    layer down.
    """
    return SkillsMiddleware(backend=backend, sources=list(sources))


class OffloadMiddleware(AgentMiddleware):
    """Fills the `"filesystem"` slot: large tool results go to disk, not the transcript.

    Prefix-filtered, never blanket (`launch-readiness/102`): only tool calls
    whose name starts with one of `tool_name_prefixes` are even considered,
    and only a result whose text exceeds `threshold_chars` is written out —
    a short result stays inline, because a store of one-line files makes
    `grep` useless. A written result is replaced with a pointer naming the
    path and instructing the agent to use `grep`/`read_file` on the backend,
    so retrieval is a real capability and not a promise the model must recall
    unprompted.
    """

    def __init__(
        self,
        *,
        backend: FilesystemBackend,
        tool_name_prefixes: Sequence[str] = (),
        threshold_chars: int = DEFAULT_OFFLOAD_THRESHOLD_CHARS,
        path_for: Callable[[ToolCallRequest], str] | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._prefixes = tuple(tool_name_prefixes)
        self._threshold = threshold_chars
        self._path_for = path_for or _default_path_for

    def _eligible(self, tool_name: str) -> bool:
        if not self._prefixes:
            return False
        return any(tool_name.startswith(p) for p in self._prefixes)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        return self._offloaded(handler(request), request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        """The same decision, with the one `await` the async path needs.

        `async-first/06`: a deep-tier agent is reached through `ainvoke` once
        `_agent`'s node body is `async def`, and `awrap_tool_call` has no
        usable default — LangChain raises `NotImplementedError` naming the
        sync method, so a deep agent without this would die on its first tool
        call. Nothing about *what* to offload is written twice; that lives in
        `_offloaded`.
        """
        return self._offloaded(await handler(request), request)

    def _offloaded(self, result: Any, request: ToolCallRequest) -> Any:
        if not isinstance(result, ToolMessage):
            return result
        tool_name = request.tool_call.get("name", "")
        if not self._eligible(tool_name):
            return result
        text = result.text if hasattr(result, "text") else str(result.content)
        if len(text) <= self._threshold:
            return result
        path = self._path_for(request)
        try:
            write_result = self._backend.write(path, text)
        except (ValueError, OSError, RuntimeError):
            # `FilesystemBackend.write` (deepagents==0.7.5) only catches
            # `(OSError, RuntimeError)` around path resolution — a
            # traversal path (`..`) makes `_resolve_path` raise
            # `ValueError`, uncaught, straight out of `write`. That
            # contradicts "refuse via a result, not a raise": recorded as
            # a finding in `launch-readiness/102`, not re-implemented
            # here. This `except` is *this middleware's* seam keeping its
            # own promise regardless — a bad path is a recoverable,
            # un-offloaded message, never a dead run.
            return result
        if write_result.error:
            # An ordinary write failure the backend *did* catch and
            # report as a result.
            return result
        pointer = (
            f"[offloaded: {len(text)} chars written to path={path!r}. "
            f"Use grep(path={path!r}, ...) or read_file({path!r}) to inspect it.]"
        )
        return result.model_copy(update={"content": pointer})


def _default_path_for(request: ToolCallRequest) -> str:
    name = request.tool_call.get("name", "tool")
    call_id = request.tool_call.get("id", "0")
    return f"/offload/{name}/{call_id}.txt"


#: The tools that can follow a pointer. A disclosed skill and an offloaded
#: tool result are the same artefact — a path into a store — and `read_file`
#: is what turns either back into text. `grep` is here because
#: `launch-readiness/102` is explicit that reading a file back whole costs
#: what not offloading cost; a surface with only `read_file` still works, it
#: is merely the expensive shape of working.
FILE_READ_TOOL_NAMES = frozenset({"read_file", "grep"})

#: What `create_deep_agent` assembles for itself. `FilesystemMiddleware` is
#: part of its fixed slot assembly, so a deep-tier node's effective surface is
#: always wider than the tools the canvas wired to it — read off the installed
#: `deepagents==0.7.5` rather than asserted from memory.
DEEP_TIER_FILE_TOOLS: tuple[str, ...] = (
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
)


def surface_can_dereference(
    tool_surface: Iterable[str], *, shares_backend: bool
) -> bool:
    """**The one condition that gates both disclosure and offload.**

    Progressive disclosure puts a skill's *path* in the prompt; offloading
    replaces a large result with a *pointer to a path*. Both hand the model a
    reference, and a reference is only worth handing over when the model can
    dereference it — which takes two facts, not one:

    - the surface contains a file-read tool at all, and
    - that tool reads the store this seam writes to.

    The second is the half a naive adoption drops. A workflow may perfectly
    well wire a tool of its own called ``read_file``; it reads its own store,
    and a pointer into ours means nothing to it. Today only the deep tier can
    satisfy it, because ``create_deep_agent(backend=...)`` is the only
    constructor in the ladder that lets a caller say which store the harness'
    own file tools read.

    A comparative read of a neighbouring system found the same lever from the
    other side: it defaults its deep tier **off** for data questions, because
    a virtual-FS toolset makes even a strong model wander into ``grep``/
    ``glob`` instead of the data tools, and a prompt cannot reliably stop it —
    removing the tools does. Whichever way it is pointed, the tool surface is
    the control, not the prompt.
    """
    if not shares_backend:
        return False
    return bool(FILE_READ_TOOL_NAMES.intersection(tool_surface))


#: **What the harness is, told to the model that is inside it**
#: (`launch-readiness/120`). Locked, core-owned, and domain-free: every word
#: here is about OSG's own machinery, so it can ride every deep-tier agent in
#: every workflow without describing anything a package author owns.
#:
#: The middle paragraph is the one the ticket was filed for. `OffloadMiddleware`
#: above already tells the model *where* a large result went — the pointer names
#: the path and the two tools that open it. Nothing told it the **habit**: that
#: the fetch already happened, so the way to see that data again is to read the
#: file, not to call the tool a second time. A harness whose whole premise is
#: read-then-write had never said so.
#:
#: The last paragraph points the other way on purpose, and it is the half a
#: preamble written only to advertise the filesystem would miss. A virtual-FS
#: toolset invites a model to search files for facts that live in a database
#: (`launch-readiness/146`: a dozen file reads answering one question, seven of
#: them after the query had already returned its rows). The neighbouring system
#: takes the tools away; this at least says what the files are for.
HARNESS_PREAMBLE = (
    "You are running inside a harness that gives you a virtual filesystem. "
    "`ls`, `read_file`, `write_file` and `grep` reach it and nothing else: it "
    "is private to this conversation and confined to it — no other "
    "conversation and no other person can read what you write — no path you "
    "write is visible to the person asking, and it is a workspace for large "
    "material rather than the place your answer goes.\n\n"
    "A large tool result is not returned to you in full. It is written to a "
    "file and you are handed the path instead, in a line reading `[offloaded: "
    "N chars written to path=...]`. That path is the result — the data was "
    "fetched and it is still there. To see any part of it again, `grep` that "
    "path for what you need or `read_file` it; never call the tool a second "
    "time to look at data you already have.\n\n"
    "Prefer the tool that answers the question over the filesystem. The files "
    "hold what your tools returned; they are not a source of facts on their "
    "own, and searching them is never a substitute for asking the tool that "
    "knows. A file you find may have been written earlier in this "
    "conversation, in answer to a different question: it is what a tool "
    "returned then, not what it would return now."
)

#: The sentence that is only true once skills were actually disclosed
#: (`launch-readiness/111`). Kept apart from `HARNESS_PREAMBLE` rather than
#: folded into it, because a package with no `skills/` discloses nothing and
#: would otherwise be told to go and read files that do not exist — the same
#: lie as describing a filesystem to an agent that has none, one paragraph
#: smaller.
SKILL_DISCLOSURE_PREAMBLE = (
    "Some of your instructions are not in this prompt. They are listed by name "
    "and description, and you open the one you need with `read_file` — read it "
    "before acting on the task it covers, rather than working from its "
    "one-line description."
)


def harness_preamble(
    tool_surface: Iterable[str],
    *,
    shares_backend: bool,
    skills_disclosed: bool = False,
) -> str:
    """The harness contract this agent has earned, or ``""``.

    **The same condition, not a second one.** `surface_can_dereference` is what
    decides whether the offload and skills middlewares are contributed at all
    (`plan_disclosure`), so it is also exactly what decides whether there is
    anything true to say about them. A separate check here would be a second
    place for the answer to be decided and therefore a second place for it to
    drift — and drift in the expensive direction: a preamble describing a
    filesystem to an agent that has none is a lie the platform tells on every
    turn, and a package author can neither see it nor fix it.
    """
    if not surface_can_dereference(tool_surface, shares_backend=shares_backend):
        return ""
    if skills_disclosed:
        return f"{HARNESS_PREAMBLE}\n\n{SKILL_DISCLOSURE_PREAMBLE}"
    return HARNESS_PREAMBLE


@dataclass(frozen=True)
class DeepTierDisclosure:
    """What one node's tool surface earned it — decided in one place.

    `contributions` are slot-named, never positional, so a compiler merges
    them into `resolve_middleware()`'s table exactly as it merges `rubric` and
    `summarization` (CLAUDE.md: *the base does not own a hardcoded middleware
    list*).
    """

    #: Slot name -> middleware. Empty when the surface cannot dereference.
    contributions: Mapping[str, Any]
    #: The store both middlewares use, to be handed to the tier's constructor
    #: so its own `read_file`/`grep` read what this seam wrote. `None` when
    #: nothing was contributed.
    backend: Any = None
    #: The skills whose bodies were moved out of the prompt, by name. The
    #: caller keeps flat-injecting **everything else**: disclosure is decided
    #: per skill, not per package, because a skill the library refuses to list
    #: (see `_disclosable`) would otherwise vanish from the prompt entirely —
    #: no body, and no line saying it exists.
    disclosed: tuple[str, ...] = ()
    #: Why, in one sentence, when nothing was disclosed. Empty otherwise.
    reason: str = ""

    @property
    def flat_injection(self) -> bool:
        """Whether the caller's whole `discover_skills` text is still needed.

        **True is the safe answer**, and it is the answer whenever nothing was
        disclosed — including for a package with no `skills/` at all — so the
        state that needs no decision is the state that loses nothing.
        """
        return not self.disclosed


def plan_disclosure(
    *,
    package_dir: Any,
    tool_surface: Iterable[str],
    shares_backend: bool,
    offload_prefixes: Sequence[str] = (),
    threshold_chars: int = DEFAULT_OFFLOAD_THRESHOLD_CHARS,
) -> DeepTierDisclosure:
    """Decide, once, what a node's tool surface earns it.

    One function rather than two gates, because `launch-readiness/111` is
    explicit that splitting them breaks the "land together or not at all" that
    `102` argued for: disclosure and offload share a precondition, and either
    one wired without it produces an agent holding a reference it cannot
    dereference.

    The two slots are *gated* together and *filled* independently — a package
    with no `skills/` still offloads, and `flat_injection` stays true because
    nothing was withheld from the prompt.
    """
    surface = tuple(tool_surface)
    if not surface_can_dereference(surface, shares_backend=shares_backend):
        return DeepTierDisclosure(
            contributions={},
            reason=(
                "this agent's tool surface has no file-read tool it shares with the "
                "run's store, so a disclosed skill path or an offload pointer would "
                "be a reference it could not follow"
            ),
        )

    # Decided here, projected later. The decision is what the *prompt* needs
    # — which skills leave the flat injection — and it is the same in every
    # conversation; the copy on disk belongs to whichever store this run
    # opens, and `ThreadScopedBackend` writes it as that store is created.
    disclosed = [skill.name for skill in _worth_disclosing(package_dir)]
    backend = ThreadScopedBackend(
        package_dir=package_dir, project_skills=bool(disclosed)
    )
    contributions: dict[str, Any] = {}
    if disclosed:
        contributions["skills"] = build_skills_middleware(
            backend=backend, sources=[SKILLS_VIRTUAL_ROOT]
        )
    contributions["filesystem"] = OffloadMiddleware(
        backend=backend,
        tool_name_prefixes=tuple(offload_prefixes),
        threshold_chars=threshold_chars,
    )
    return DeepTierDisclosure(
        contributions=contributions,
        backend=backend,
        disclosed=tuple(disclosed),
    )


#: Where a projected skill lives inside the run's own store.
SKILLS_VIRTUAL_ROOT = "/skills"

#: How long a conversation's store survives with nothing touching it. A store
#: nobody has read or written for an hour belongs to a conversation nobody is
#: in; keeping it is `launch-readiness/96` in another costume — an unbounded
#: directory of dead runs — and the only thing lost by removing it is a
#: dereference in a conversation that has already stopped.
THREAD_ROOT_TTL_SECONDS = 3600.0

#: And a ceiling, for the burst the TTL cannot see: a server answering
#: hundreds of conversations inside one TTL window would otherwise hold every
#: one of their stores at once. The least-recently-touched go first.
MAX_LIVE_THREAD_ROOTS = 64

#: One directory per package, holding one subdirectory per conversation. The
#: package level exists so a sweep has somewhere to sweep and so a process
#: leaves one tree per package rather than one per conversation.
_PACKAGE_BASES: dict[str, Path] = {}

#: **One root per package per THREAD, not per process** (`launch-readiness/149`).
#:
#: The comment that stood here argued the per-process store from one run: a
#: second root would give the same agent two stores and make the pointer it
#: was handed unresolvable in the other. That is true and is still why the
#: *same* store is handed to the skills middleware, the offload middleware and
#: the tier's own file tools. It was never an argument for sharing a writable
#: scratch directory between two different conversations, which is what it
#: silently bought: three consecutive runs of one question on one server, and
#: run 2 answered out of the files run 1 wrote, having called no query at all.
#:
#: The key is `thread_id` because that is the identifier the graph actually
#: carries — on the installed `langgraph 1.2.10` a node's config exposes
#: `execution_info.run_id` as `None`, while `configurable["thread_id"]` is
#: always there, is what the checkpointer keys on, and is what
#: `POST /api/runs/resume` demands back. It is also the narrowest scope that
#: does not invent a second bug: a resume is the same thread, and its
#: transcript still carries offload pointers that have to resolve.
#:
#: The empty key is the store for a caller with no run config at all — a
#: script, a unit test, a tool called off the graph. It is one store, not
#: everyone's.
_ROOTS: dict[tuple[str, str], Path] = {}

#: When each root was last resolved, for the sweep. In-process bookkeeping
#: rather than directory mtimes, which do not move when a nested file is
#: written.
_TOUCHED: dict[tuple[str, str], float] = {}


def _scope_key() -> str:
    """The conversation this call belongs to, or `""` off the graph.

    `run_identity` is the one place the four identity keys are read
    (`run_identity.py`), and it already answers `{}` rather than raising when
    there is no runnable context. A caller with no thread is a normal caller,
    not an error.
    """
    from openstategraph.run_identity import run_identity

    return run_identity().get("thread_id", "")


def _package_base(key: str) -> Path:
    base = _PACKAGE_BASES.get(key)
    if base is None or not base.is_dir():
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        base = Path(tempfile.mkdtemp(prefix=f"osg-disclosure-{digest}-")).resolve()
        _PACKAGE_BASES[key] = base
    return base


def _sweep(now: float) -> None:
    """Remove the stores of conversations that have stopped.

    Runs when a new one is opened, which is the only moment the count can
    grow, so nothing schedules anything and nothing runs on a quiet server.
    """
    for key in [k for k, seen in _TOUCHED.items() if now - seen > THREAD_ROOT_TTL_SECONDS]:
        _forget(key)
    if len(_ROOTS) >= MAX_LIVE_THREAD_ROOTS:
        oldest = sorted(_TOUCHED, key=lambda k: _TOUCHED[k])
        for key in oldest[: len(_ROOTS) - MAX_LIVE_THREAD_ROOTS + 1]:
            _forget(key)


def _forget(key: tuple[str, str]) -> None:
    root = _ROOTS.pop(key, None)
    _TOUCHED.pop(key, None)
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)


def _disclosure_root(package_dir: Any, *, project_skills: bool = False) -> Path:
    """A writable store the model is jailed inside, never the package itself.

    Rooting the backend at the package directory would have been shorter and
    is wrong twice: an offloaded result would be written *into* someone's
    source tree, and the agent's own `read_file`/`grep` would be pointed at
    every file in the package rather than at the skills its prompt lists. A
    scratch root holds exactly what this seam put there.

    Scoped to the calling conversation — see `_ROOTS`. Skills are projected
    into each new store as it is opened, because isolation is of what the
    *agent wrote* and never of what it was *given*: a read-only projection
    absent from the second conversation's store would leave every path in the
    disclosure prompt dangling, which is the same defect pointed backwards.
    """
    package_key = str(package_dir or "")
    key = (package_key, _scope_key())
    root = _ROOTS.get(key)
    now = time.monotonic()
    if root is None or not root.is_dir():
        _sweep(now)
        digest = hashlib.sha256(key[1].encode("utf-8")).hexdigest()[:12]
        root = _package_base(package_key) / (digest if key[1] else "no-thread")
        root.mkdir(parents=True, exist_ok=True)
        # Resolved, because `FilesystemBackend` compares a resolved path
        # against its root and `/var` is a symlink to `/private/var` on
        # macOS — an unresolved root refuses every path under itself.
        root = root.resolve()
        _ROOTS[key] = root
        if project_skills:
            _project_skills(package_dir, root)
    _TOUCHED[key] = now
    return root


class ThreadScopedBackend(FilesystemBackend):
    """`FilesystemBackend` whose root is *this conversation's* store.

    A subclass rather than a factory, and that is the installed library's
    choice rather than ours: the docs show `create_deep_agent(backend=lambda
    runtime: ...)` resolving a per-thread sandbox, but `deepagents==0.7.5`
    raises `TypeError` on a callable backend — *"Backend factories were
    removed in deepagents 0.7"*. Where the docs and the installed version
    disagree, the installed version wins.

    So the scoping goes where the state is. `FilesystemBackend` keeps exactly
    one attribute that says where it reads and writes — `cwd` — and every
    operation resolves through it, so a property is the whole of the change
    and none of the library's path jailing is re-implemented or weakened.
    """

    def __init__(self, *, package_dir: Any, project_skills: bool) -> None:
        self._package_dir = package_dir
        self._project_skills = project_skills
        super().__init__(root_dir=tempfile.gettempdir(), virtual_mode=True)

    @property
    def cwd(self) -> Path:  # type: ignore[override]
        return _disclosure_root(
            self._package_dir, project_skills=self._project_skills
        )

    @cwd.setter
    def cwd(self, _value: Any) -> None:
        """Swallow the base constructor's one assignment.

        `FilesystemBackend.__init__` writes `self.cwd` from `root_dir`; there
        is no root to fix here, because the answer depends on who is asking.
        """


def _disclosable(package_dir: Any) -> list[Any]:
    """The skills this package can disclose **without losing one**.

    `SkillsMiddleware` requires `name` *and* `description` in the frontmatter
    and silently skips a file carrying neither — it logs and moves on. Two of
    this repository's own three shipped skills
    (`workflows/workflow-architect/skills/*.md`) have no frontmatter at all,
    so disclosing the package wholesale would have deleted them from the
    prompt: no body, and no line saying they exist. Measured, not assumed —
    that is what `launch-readiness/111`'s recall requirement is for.

    A skill with no description is therefore not disclosable, and stays in the
    flat injection where it works. Writing a description is how its author
    opts it in, which is also the lever the library's own progressive
    disclosure runs on: the description is the *only* thing the model judges
    from.
    """
    if package_dir is None:
        return []
    source = Path(package_dir) / "skills"
    if not source.is_dir():
        return []
    from openstategraph.skills import SkillDocument

    return [
        skill
        for skill in (SkillDocument.load(path) for path in sorted(source.glob("*.md")))
        if skill.body and skill.name and skill.description
    ]


def _skills_prompt_fixed_cost() -> int:
    """What the library's skills instructions cost before any skill is listed.

    Read off the installed package rather than guessed, because it is the
    break-even below which disclosure is a **loss**: `workflows/concierge`
    carries one 1,970-byte skill, and disclosing it made the system prompt
    134 bytes *larger*. A change filed to reduce prompt size must not enlarge
    it for the smallest package we ship.
    """
    defaults = SkillsMiddleware.__init__.__kwdefaults__ or {}
    return len(defaults.get("system_prompt") or "")


def _worth_disclosing(package_dir: Any) -> list[Any]:
    """The skills that will be projected — decided, never written.

    Split from `_project_skills` by `launch-readiness/149`: the *decision*
    belongs to the compiler, once, because it is what the prompt is built
    from; the *copy* belongs to each conversation's store, because that is
    where the paths in that prompt have to resolve.

    Disclosure is only worth doing when it saves more than it costs. The
    bodies leave the prompt; the library's instructions and one name +
    description per skill arrive.
    """
    candidates = _disclosable(package_dir)
    if not candidates:
        return []
    saved = sum(len(skill.body) for skill in candidates)
    added = _skills_prompt_fixed_cost() + sum(
        len(skill.name) + len(skill.description) for skill in candidates
    )
    return candidates if saved > added else []


def _project_skills(package_dir: Any, root: Path) -> list[str]:
    """Project `<package>/skills/*.md` into `<root>/skills/<name>/SKILL.md`.

    Two layouts, and only one of them is authoritative. This project's
    packages carry flat `skills/*.md` — what `discover_skills` globs and what
    every shipped package has on disk — while `SkillsMiddleware` reads
    `<source>/<name>/SKILL.md` directories. Pointing the library straight at
    `<package>/skills` finds nothing and says nothing, which is the exact
    silent-nothing `docs/decisions/deep-agent-slots.md` measured `skills=`
    doing.

    So this is a **projection, not a second source**: `skills/*.md` stays the
    only place anybody edits, and the copy is rebuilt from it, inside a
    scratch root nothing else reads.
    """
    candidates = _worth_disclosing(package_dir)
    if not candidates:
        return []
    projected: list[str] = []
    target_root = root / "skills"
    if target_root.exists():
        shutil.rmtree(target_root)
    for skill in candidates:
        target = target_root / skill.name
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(skill.render(), encoding="utf-8")
        projected.append(skill.name)
    return projected


__all__ = [
    "DEEP_TIER_FILE_TOOLS",
    "HARNESS_PREAMBLE",
    "SKILL_DISCLOSURE_PREAMBLE",
    "DEFAULT_OFFLOAD_THRESHOLD_CHARS",
    "FILE_READ_TOOL_NAMES",
    "DeepTierDisclosure",
    "MAX_LIVE_THREAD_ROOTS",
    "OffloadMiddleware",
    "SKILLS_VIRTUAL_ROOT",
    "THREAD_ROOT_TTL_SECONDS",
    "ThreadScopedBackend",
    "build_skills_middleware",
    "harness_preamble",
    "plan_disclosure",
    "surface_can_dereference",
]
