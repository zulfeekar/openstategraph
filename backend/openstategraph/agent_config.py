"""One command line, rendered into the four files four coding agents read.

**Tier 2, provisional** (`docs/stability.md`).

`osg-agent-experience/25` slice 2, on `27`'s research note. A project-local
stdio MCP server is configured in a different file, under a different key, for
every agent a reader might be using:

| Agent | File | Key |
| --- | --- | --- |
| Claude Code | `.mcp.json` at the project root | `mcpServers` |
| VS Code (+ Copilot) | `.vscode/mcp.json` | **`servers`**, not `mcpServers` |
| Cursor | `.cursor/mcp.json` | `mcpServers` |
| OpenAI Codex CLI | `.codex/config.toml` | `[mcp_servers.<name>]` |

`docs/mcp.md` used to hand a reader one JSON block to paste. That block is the
same command line as the other three, so an adopting repository ended up with
four hand-maintained copies of it — and the one thing the block carries that a
reader would not think to type, `OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`, is exactly
the line dropped when somebody edits a copy. So there is **one**
`ServerDescriptor` here and four thin renderers, and `init` calls them.

**The merge rule: merge, never refuse.** An agent config is a machine registry
with a natural merge key, and this is the agents' own model of the file —
`claude mcp add --scope project` "automatically creates *or updates*"
`.mcp.json`. So an existing file is parsed, our one entry inserted, and
everything else — other servers, unknown top-level keys, and in TOML the
existing text with its comments — written back untouched.

Two cases decline to write, and both are the same principle:

- an `openstategraph` entry that already exists and **differs** is somebody's
  deliberate customisation (`ALLOW_RUNS=1` is the one that matters), and an
  overwrite would silently disarm their choice;
- a file that will not parse is left exactly as it is. A writer that repairs
  broken JSON by replacing it is a writer that eats somebody's work.

Both are reported as `KEPT` with a note saying what differed, because a file
we declined to write is a sentence `init` has to be able to print truthfully —
the same discipline `agent_brief.write_into` already applies to `AGENTS.md`.

This module deliberately does **not** know the Agent Plugins format. That
spec's strings (`plugin.json`, `mcp.json`, `${PLUGIN_ROOT}`) belong to
`plugin_interop.py` and nowhere else; the two renderers meet at the descriptor
below, never at each other's files.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from importlib.util import find_spec
from pathlib import Path
from types import MappingProxyType

#: The environment block every rendered entry carries. `run_workflow` is the
#: one MCP tool that reaches a model and therefore spends money; `0` removes
#: it from the registry. Written by default so that the safe configuration is
#: the one a reader gets without knowing the variable exists.
DEFAULT_ENV: Mapping[str, str] = MappingProxyType({"OPENSTATEGRAPH_MCP_ALLOW_RUNS": "0"})


@dataclass(frozen=True)
class ServerDescriptor:
    """This project's MCP server, as the one fact the renderers read.

    `command` is a single executable token on purpose — a console script, not
    `python3 -m …`: that spelling needs a `PYTHONPATH` the reader has to know,
    and it is the shape that rots when the checkout moves.

    The *default* is the bare name, because a descriptor built with no argument
    is describing the shape of an entry rather than one machine. `init` does
    not use the default: it calls `resolve_server_command()`, and
    `docs-onramp/10` is the reason — see that function.
    """

    name: str = "openstategraph"
    command: str = "openstategraph"
    args: tuple[str, ...] = ("mcp",)
    env: Mapping[str, str] = field(default_factory=lambda: DEFAULT_ENV)
    # `default_factory`, not the proxy itself: CPython 3.11 refuses any
    # unhashable default on a dataclass field, and a `mappingproxy` is one.
    # 3.13 lets it through, which is how this shipped and how CI, which
    # runs 3.11 first, was the instrument that caught it (osg-agent-experience/44).
    description: str = "OpenStateGraph — local workflow compiler, validator and board"

    def entry(self) -> dict[str, object]:
        """The stdio entry body, in the shape all four files agree on."""
        return {"command": self.command, "args": list(self.args), "env": dict(self.env)}


class AgentFileState(Enum):
    """What happened to one agent's file. Four states, four sentences.

    The same vocabulary `agent_brief` and `bundled_skills` already print, plus
    `KEPT` — the state those two do not need, because neither of them can find
    a file that says something different from what it would write.
    """

    CREATED = "created"
    MERGED = "merged"
    CURRENT = "current"
    KEPT = "kept"


@dataclass(frozen=True)
class AgentFileAction:
    """One file, and what `init` is entitled to say about it."""

    #: `claude-code` | `vscode` | `cursor` | `codex`.
    agent: str
    path: Path
    state: AgentFileState
    #: Why, when the answer is `KEPT`. Empty otherwise.
    note: str = ""


def missing_server_note(server: ServerDescriptor | None = None) -> str | None:
    """The sentence for a config file naming a command that cannot start.

    `osg-agent-experience/24`, and `19`'s failure caught at the friendliest
    possible moment. Every rendered entry runs `openstategraph mcp`, which
    lives behind the `[mcp]` extra; on an installation without it the four
    files are written, `init` reports that the agent can reach this project's
    server, and the developer finds out from a non-zero exit inside their
    agent's own start-up log, where our name appears and our install line does
    not.

    A spec lookup rather than an import: this runs on the happy path of every
    `init`, and importing the SDK to find out whether it is there would cost
    every reader the start-up of a server nobody asked to run. `None` when
    there is nothing to say — a report that always prints its advice is one a
    reader learns to skip.
    """
    server = server or ServerDescriptor()
    try:
        present = find_spec("mcp") is not None
    except (ImportError, ValueError):  # a broken or half-installed distribution
        present = False
    if present:
        return None

    from openstategraph._extras import install_hint

    command = " ".join((server.command, *server.args))
    return f"`{command}` is not installed here yet — {install_hint('mcp')}"


def resolve_server_command(name: str = "openstategraph") -> str:
    """The command an agent launched from *this* installation can actually run.

    `docs-onramp/10`. Every entry named `openstategraph` bare, resolved against
    the agent's `PATH`. That is correct for the `uv tool install` route README
    leads with — the shim lands in `~/.local/bin` and stays valid when the
    project moves — and wrong for every other install this project documents:
    a project venv, `pip install -e "backend[…]"` from a checkout, `pipx` in a
    shell nobody re-sourced. There the name is not on the agent's `PATH`, the
    server never starts, and the agent shows no tools and says nothing, which
    reads as *this project's MCP layer is broken*.

    So the bare name is **preferred and not assumed**. It is kept whenever the
    environment `init` runs in can resolve it, because an absolute path pins the
    config to one venv and a rebuilt venv is a silently dead entry. Only when
    the name resolves to nothing does this fall back to the console script
    beside the running interpreter — `sys.argv[0]` when that *is* the script,
    else `sys.prefix/bin` — which is the one executable we can name and be sure
    of.

    And when there is neither, the bare name comes back unchanged. Nothing to
    point at is not a licence to invent a path, and an entry naming the bare
    name is at least the case `missing_server_note` already has a sentence for.

    A future reader will want to "fix" this to always write the absolute path,
    or always write the name. Both were considered here and both lose one of
    the two installs; that is why the branch exists and why `command_note`
    prints which way it went.
    """
    import shutil
    import sys

    if shutil.which(name):
        return name

    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None and argv0.name in (name, f"{name}.exe") and argv0.is_file():
        return str(argv0.resolve())

    for folder in ("bin", "Scripts"):
        for filename in (name, f"{name}.exe"):
            candidate = Path(sys.prefix) / folder / filename
            if candidate.is_file():
                return str(candidate)

    return name


def command_note(server: ServerDescriptor) -> str:
    """What `init` says about the command it just wrote into four files.

    The sentence exists because the resolution above is invisible in the report
    otherwise: a reader who sees `.mcp.json  created` learns nothing about which
    entry they got, and they behave differently the next time that environment
    is rebuilt or moved.

    **Three outcomes, not two**, and the third is the one this function got
    wrong first. Asking only whether the command is absolute collapses *found
    on PATH* with *nothing to point at*, and the bare name that comes back from
    the third case was then announced as found — a false sentence, printed at
    exactly the reader who most needs a true one. Caught walking the fix as a
    user with `~/.local/bin` off the `PATH`.

    `shutil.which` is asked a second time here rather than threaded out of
    `resolve_server_command`. Both calls happen inside one `init`, against one
    environment, so they cannot disagree; a resolver returning a command *and*
    a reason would make every caller that wants only the command unpack one.
    """
    import shutil

    if Path(server.command).is_absolute():
        return (
            f"the four files run {server.command} — an absolute path, because "
            f"`{ServerDescriptor.command}` is not on this shell's PATH. Rebuild or move that "
            "environment and re-run init."
        )
    if shutil.which(server.command):
        return (
            f"the four files run `{server.command}`, found on PATH — so they keep working "
            "wherever that install moves to."
        )
    return (
        f"the four files run `{server.command}`, which is not on this shell's PATH and has "
        "no console script beside this interpreter either — your agent will not be able to "
        "start it. Install the wheel (or `uv tool install openstategraph`) and re-run init."
    )


#: One row per agent: the file, and the top-level key its servers live under.
#: `None` marks the TOML one, which has a table path rather than a key.
AGENT_FILES: tuple[tuple[str, str, str | None], ...] = (
    ("claude-code", ".mcp.json", "mcpServers"),
    ("vscode", ".vscode/mcp.json", "servers"),
    ("cursor", ".cursor/mcp.json", "mcpServers"),
    ("codex", ".codex/config.toml", None),
)

#: Codex's own table path — `[mcp_servers.<name>]`, underscored, unlike every
#: JSON key above.
CODEX_TABLE = "mcp_servers"


def merge_json_servers(
    existing: dict[str, object], key: str, entry: dict[str, object], *, servers_key: str
) -> tuple[dict[str, object], AgentFileState]:
    """Insert one server into a parsed agent config, preserving everything.

    Returns the document to write and what happened. On `CURRENT` and `KEPT`
    the document returned is the one that came in — the caller writes nothing
    in either case, and returning it rather than `None` keeps the one return
    shape.
    """
    servers = existing.get(servers_key, {})
    if not isinstance(servers, dict):
        # A shape we do not understand. Read tolerantly, trust strictly: this
        # is reported, never repaired.
        return existing, AgentFileState.KEPT
    if key in servers:
        if servers[key] == entry:
            return existing, AgentFileState.CURRENT
        return existing, AgentFileState.KEPT
    merged = dict(existing)
    merged[servers_key] = {**servers, key: entry}
    return merged, AgentFileState.MERGED


def merge_codex_toml(existing_text: str, server: ServerDescriptor) -> tuple[str, AgentFileState]:
    """Append our table to a Codex config, at the level of *text*.

    Deliberately not a parse-and-rewrite. `tomllib` reads and does not write,
    and any round trip through a writer would lose the comments and the key
    order of a file somebody hand-wrote — which is most `config.toml`s. So the
    parse is used only to *ask* whether our table is already there, and the
    write is an append.

    Raises `tomllib.TOMLDecodeError` on a file that will not parse; the caller
    turns that into `KEPT` with the message.
    """
    data = tomllib.loads(existing_text)
    table = data.get(CODEX_TABLE, {})
    if isinstance(table, dict) and server.name in table:
        if table[server.name] == server.entry():
            return existing_text, AgentFileState.CURRENT
        return existing_text, AgentFileState.KEPT
    separator = "" if not existing_text else ("\n" if existing_text.endswith("\n") else "\n\n")
    return existing_text + separator + _codex_table(server), AgentFileState.MERGED


def render_all(
    project: Path | str, server: ServerDescriptor | None = None
) -> tuple[AgentFileAction, ...]:
    """Write (or merge into) all four files, and say what happened to each.

    Unconditional, rather than detecting which agents a project uses: a
    detector would be wrong exactly when it matters — the reader who has not
    opened their agent in this directory yet — and each file is a few lines
    naming one command.
    """
    # `None` rather than a descriptor default evaluated at import: the command
    # is a fact about the environment `init` is running in (`docs-onramp/10`),
    # and an import-time default would answer for the environment that imported
    # this module. One descriptor still drives all four files — the resolution
    # happens once, here, above the loop.
    server = server or ServerDescriptor(command=resolve_server_command())
    target = Path(project)
    actions: list[AgentFileAction] = []
    for agent, relative, servers_key in AGENT_FILES:
        path = target / relative
        if servers_key is None:
            actions.append(_render_codex(agent, path, server))
        else:
            actions.append(_render_json(agent, path, server, servers_key=servers_key))
    return tuple(actions)


# --------------------------------------------------------------------- #
# The renderers
# --------------------------------------------------------------------- #


def _entry_for(agent: str, server: ServerDescriptor) -> dict[str, object]:
    """VS Code is the one that wants the transport named.

    Its documented entry carries `"type": "stdio"`; the others infer stdio
    from the presence of `command`. One extra key rather than a second
    descriptor — the command line is still stated once.
    """
    entry = server.entry()
    if agent == "vscode":
        return {"type": "stdio", **entry}
    return entry


def _render_json(
    agent: str, path: Path, server: ServerDescriptor, *, servers_key: str
) -> AgentFileAction:
    entry = _entry_for(agent, server)
    if not path.exists():
        _write(path, json.dumps({servers_key: {server.name: entry}}, indent=2) + "\n")
        return AgentFileAction(agent, path, AgentFileState.CREATED)

    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        existing = json.loads(text)
    except json.JSONDecodeError as exc:
        return AgentFileAction(agent, path, AgentFileState.KEPT, f"it is not valid JSON: {exc}")
    if not isinstance(existing, dict):
        return AgentFileAction(agent, path, AgentFileState.KEPT, "its top level is not an object")

    merged, state = merge_json_servers(existing, server.name, entry, servers_key=servers_key)
    if state is AgentFileState.MERGED:
        _write(path, json.dumps(merged, indent=2) + "\n")
    note = ""
    if state is AgentFileState.KEPT:
        servers = existing.get(servers_key)
        theirs = servers.get(server.name) if isinstance(servers, dict) else None
        note = _conflict_note(theirs, entry, servers_key)
    return AgentFileAction(agent, path, state, note)


def _render_codex(agent: str, path: Path, server: ServerDescriptor) -> AgentFileAction:
    if not path.exists():
        _write(path, _codex_table(server))
        return AgentFileAction(agent, path, AgentFileState.CREATED)

    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        merged, state = merge_codex_toml(text, server)
    except tomllib.TOMLDecodeError as exc:
        return AgentFileAction(agent, path, AgentFileState.KEPT, f"it is not valid TOML: {exc}")
    if state is AgentFileState.MERGED:
        _write(path, merged)
    note = ""
    if state is AgentFileState.KEPT:
        theirs = tomllib.loads(text).get(CODEX_TABLE, {}).get(server.name)
        note = _conflict_note(theirs, server.entry(), CODEX_TABLE)
    return AgentFileAction(agent, path, state, note)


def _codex_table(server: ServerDescriptor) -> str:
    """`[mcp_servers.<name>]`, hand-rendered because `tomllib` cannot write.

    `json.dumps` does the quoting: a TOML basic string and a JSON string agree
    on escapes, and the values here are a command token, flags and environment
    names.
    """
    env = ", ".join(f"{key} = {json.dumps(value)}" for key, value in server.env.items())
    return (
        f"# {server.description}\n"
        f"[{CODEX_TABLE}.{server.name}]\n"
        f"command = {json.dumps(server.command)}\n"
        f"args = [{', '.join(json.dumps(arg) for arg in server.args)}]\n"
        f"env = {{ {env} }}\n"
    )


def _conflict_note(theirs: object, ours: Mapping[str, object], where: str) -> str:
    """What differed, named — never "a conflict"."""
    if not isinstance(theirs, dict):
        return f"{where}.openstategraph is already there in a shape we do not recognise"
    differing = sorted(
        key for key in set(theirs) | set(ours) if theirs.get(key) != dict(ours).get(key)
    )
    named = ", ".join(differing) if differing else "something"
    return f"an openstategraph entry is already there and yours differs ({named}) — left alone"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


__all__ = [
    "AGENT_FILES",
    "AgentFileAction",
    "AgentFileState",
    "ServerDescriptor",
    "merge_codex_toml",
    "missing_server_note",
    "merge_json_servers",
    "command_note",
    "render_all",
    "resolve_server_command",
]
