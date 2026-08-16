"""Writing `mcp_servers:` back into the project's config file.

mcp-connect ticket 03. `config_file` reads; this module is the only thing in
the repository that *writes* a config file a human also edits, and its whole
design is that constraint.

**One block, not one document.** `openstategraph.yaml` is YAML because it
carries the reasoning next to the line it applies to — that is the argument
`config_file`'s own docstring makes for the format over JSON. A
`yaml.safe_load` → `yaml.safe_dump` round trip is a correct rewrite that
deletes every comment in the file, silently, on the first Save press. So the
writer finds the `mcp_servers:` block textually, replaces exactly that, and
leaves every other byte where it was. The block itself is emitted by
`yaml.safe_dump`, so quoting and escaping are still the library's problem and
not a regex's.

**The loader is the only judge.** Nothing here re-implements the secret rules.
A write is rendered, written, and immediately read back through `load_config`;
if the loader refuses it — a `token_env` holding a pasted key, a URL that is a
credential, anything the raw-document walk catches — the previous bytes are
restored and the loader's own message is raised. A second copy of the rules
would be the duplicated knowledge the DRY rule is about, and it would drift in
exactly one direction: the writer's copy would be the lenient one.

**JSON is written whole**, because `openstategraph.json` has no comments to
lose. `pyproject.toml` is refused outright with a message naming the table:
editing a TOML document in place needs a round-tripping TOML writer this
project does not depend on, and rewriting somebody's `pyproject.toml` from a
parsed dict is the comment-eating failure with higher stakes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openstategraph.config_file import (
    CONFIG_ENV_VAR,
    CONFIG_FILENAMES,
    PYPROJECT_FILENAME,
    SUPPORTED_VERSION,
    ConfigError,
    McpServerConfig,
    find_config_file,
    load_config,
    reset_active_config,
)

#: The key this module owns. Nothing else in the file is ever rewritten.
BLOCK_KEY = "mcp_servers"

#: A top-level `mcp_servers:` line — column zero, which is what makes it the
#: document's own key rather than a string inside somebody else's block.
_BLOCK_START = re.compile(rf"^{BLOCK_KEY}\s*:")

_BLOCK_HEADER = (
    "# MCP servers this project can bind, by name. A workflow's tool.mcp card\n"
    "# NAMES one of these; the definition lives here so a copied package\n"
    "# carries no URL of yours. `token_env` is a variable NAME — the value\n"
    "# belongs in .env. `enabled: false` removes a built-in default.\n"
)

#: The header's own lines, so a rewrite can recognise and replace the copy it
#: wrote rather than stacking another one on top of it.
_HEADER_LINES = frozenset(f"{line}\n" for line in _BLOCK_HEADER.splitlines())


def writable_config_path(root: Path | str | None = None) -> Path:
    """Where a write would land — which may not exist yet.

    `OPENSTATEGRAPH_CONFIG` wins, as it does for reading, and it is honoured
    even when the file it names is absent: a deployment that points at a path
    is naming the file it wants written, not asking us to invent another one
    beside it.
    """
    import os

    explicit = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if explicit:
        return _refuse_pyproject(Path(explicit).expanduser())

    found = find_config_file(root)
    if found is not None:
        return _refuse_pyproject(found)

    base = Path(root).expanduser() if root is not None else Path.cwd()
    return base / CONFIG_FILENAMES[0]


def _refuse_pyproject(path: Path) -> Path:
    if path.name == PYPROJECT_FILENAME:
        raise ConfigError(
            f"{path}: this project is configured through pyproject.toml "
            f"[tool.openstategraph], which this editor does not rewrite — editing it in "
            f"place would need a TOML writer that preserves comments. Add the server "
            f"under [tool.openstategraph] by hand, or move the configuration into "
            f"openstategraph.yaml."
        )
    return path


def declared_mcp_servers(path: Path) -> list[McpServerConfig]:
    """What the file itself declares — entries only, defaults excluded.

    A tombstone (`enabled: false`) is one of these: it is a line in the file
    and the editor has to be able to see it in order to replace it.
    """
    if not path.is_file():
        return []
    return list(load_config(path).mcp_servers)


def upsert_mcp_server(entry: McpServerConfig, *, path: Path | None = None) -> Path:
    """Add or replace one server, by name. Returns the file it wrote.

    Replace rather than append, because the name is the identity: two entries
    named the same thing is a file whose meaning depends on which one the
    loader happens to read last.
    """
    target = path or writable_config_path()
    declared = [item for item in declared_mcp_servers(target) if item.name != entry.name]
    declared.append(entry)
    return _write(target, declared)


def remove_mcp_server(name: str, *, path: Path | None = None) -> Path:
    """Delete a project entry, or tombstone a built-in default.

    The two cases look identical to the person pressing the button and are
    different files on disk: a project entry has a line to remove, and a
    built-in has none, so removing it means *writing* one that says so.
    """
    from openstategraph.prebuilt_mcp import DEFAULT_MCP_SERVERS

    target = path or writable_config_path()
    declared = declared_mcp_servers(target)
    kept = [item for item in declared if item.name != name]
    builtin = next((item for item in DEFAULT_MCP_SERVERS if item.name == name), None)

    if len(kept) == len(declared) and builtin is None:
        raise ConfigError(
            f'No MCP server named "{name}" is registered, so there is nothing to remove.'
        )

    if builtin is not None:
        # The URL is carried so the tombstone reads as a decision about a
        # specific server rather than as a bare name, and so re-enabling it is
        # editing one word rather than looking the address up again.
        kept.append(McpServerConfig(name=builtin.name, url=builtin.url, enabled=False))
    return _write(target, kept)


def hidden_default_mcp_servers(*, path: Path | None = None) -> list[str]:
    """The built-in defaults this project has tombstoned, by name.

    The read side of `remove_mcp_server`'s write, and the reason it exists is
    mcp-connect ticket 06: every route already filters `enabled` out before
    anything leaves the backend (`mcp_server_catalogue`), which is correct for
    "what can a workflow bind" and left the editor unable to know a default had
    ever existed. So Delete on a `default` row destroyed it as far as any user
    could tell, with no confirmation and nothing offering it back.

    Only built-ins, deliberately. A deleted *project* entry leaves no line and
    no URL, so there is nothing to restore it from — offering to would promise
    something this module cannot keep.
    """
    from openstategraph.prebuilt_mcp import DEFAULT_MCP_SERVERS

    target = path or writable_config_path()
    builtin_names = {server.name for server in DEFAULT_MCP_SERVERS}
    return [
        item.name
        for item in declared_mcp_servers(target)
        if not item.enabled and item.name in builtin_names
    ]


def restore_mcp_server(name: str, *, path: Path | None = None) -> Path:
    """Lift a tombstone, putting a built-in default back as a default.

    Deleting the line rather than flipping `enabled` to `true`: an entry that
    merely re-states the shipped default is a second copy of a URL that then
    cannot follow it when it changes. With no line at all, the built-in is the
    built-in again — including its `origin`, which is what the row's badge
    reads. Re-adding by hand through `upsert_mcp_server` resurrects the server
    but stamps it `project`, so the badge said the wrong thing about a server
    the product ships.
    """
    target = path or writable_config_path()
    declared = declared_mcp_servers(target)
    tombstoned = [item for item in declared if item.name == name and not item.enabled]
    if not tombstoned:
        raise ConfigError(
            f'No MCP server named "{name}" is hidden in this project, so there is '
            f"nothing to restore."
        )
    return _write(target, [item for item in declared if item.name != name])


# --------------------------------------------------------------------- #
# The write itself
# --------------------------------------------------------------------- #


def _write(path: Path, entries: list[McpServerConfig]) -> Path:
    """Render, write, and re-read through the loader — or put it all back."""
    existed = path.is_file()
    before = path.read_text(encoding="utf-8") if existed else ""

    if path.suffix == ".json":
        rendered = _rendered_json(before, entries)
    else:
        rendered = _rendered_yaml(before if existed else _blank_yaml(), entries)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    try:
        load_config(path)
    except ConfigError:
        # The file is a human's, and it was valid a moment ago. Restoring it
        # is not politeness: leaving a refused document on disk would break
        # every subsequent read for a mistake made in one field.
        if existed:
            path.write_text(before, encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        raise

    # `active_config` is memoised on the path of every run, so a write nobody
    # invalidates is a write the next request cannot see.
    reset_active_config()
    return path


def _blank_yaml() -> str:
    return f"version: {SUPPORTED_VERSION}\n"


def _as_mapping(entry: McpServerConfig) -> dict[str, Any]:
    """The smallest true entry — defaults omitted rather than restated.

    A file full of `enabled: true` and `kind: none` teaches a reader that
    those are decisions somebody made, when they are the absence of one.
    """
    body: dict[str, Any] = {"name": entry.name, "url": entry.url}
    if entry.transport != "streamable_http":
        body["transport"] = entry.transport
    auth: dict[str, Any] = {}
    if entry.auth.kind and entry.auth.kind != "none":
        auth["kind"] = entry.auth.kind
    if entry.auth.header_name:
        auth["header_name"] = entry.auth.header_name
    if entry.auth.token_env:
        auth["token_env"] = entry.auth.token_env
    if auth:
        body["auth"] = auth
    if not entry.enabled:
        body["enabled"] = False
    return body


def _rendered_block(entries: list[McpServerConfig]) -> str:
    if not entries:
        return ""
    import yaml

    body = yaml.safe_dump(
        [_as_mapping(entry) for entry in entries],
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    # `safe_dump` puts a sequence's items at column zero under their key, which
    # is legal YAML and reads badly next to a hand-written file. Indented, the
    # block also has one shape — everything under the key is indented — which
    # is what makes finding it again a rule rather than a special case.
    items = "".join(f"  {line}\n" if line else "\n" for line in body.splitlines())
    return f"{_BLOCK_HEADER}{BLOCK_KEY}:\n{items}"


def _rendered_yaml(text: str, entries: list[McpServerConfig]) -> str:
    block = _rendered_block(entries)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    index = 0
    replaced = False

    while index < len(lines):
        if _BLOCK_START.match(lines[index]):
            index += 1
            # The block is everything indented under it, plus the un-indented
            # `- ` items PyYAML's own dumper produces — a dash at column zero
            # can only belong to the key above it. Anything else at column
            # zero ends the block, a comment included: a comment flush left is
            # somebody introducing the next section, not annotating this one.
            while index < len(lines) and (
                lines[index].strip() == "" or lines[index][:1] in " \t-"
            ):
                index += 1
            if not replaced:
                # Drop the header this module wrote last time, or a second
                # copy of it lands above the block on every save — found by
                # writing twice, which is what a panel does.
                while out and out[-1] in _HEADER_LINES:
                    out.pop()
                out.append(block)
                replaced = True
            continue
        out.append(lines[index])
        index += 1

    rendered = "".join(out)
    if not replaced and block:
        separator = "" if rendered.endswith("\n\n") else "\n" if rendered.endswith("\n") else "\n\n"
        rendered = f"{rendered}{separator}{block}"
    # A removed block can leave the file ending in the blank line that used to
    # separate it from what came before.
    return rendered.rstrip("\n") + "\n"


def _rendered_json(text: str, entries: list[McpServerConfig]) -> str:
    document: Any = json.loads(text) if text.strip() else {"version": SUPPORTED_VERSION}
    if not isinstance(document, dict):
        raise ConfigError("The top level of a config file must be a mapping.")
    if entries:
        document[BLOCK_KEY] = [_as_mapping(entry) for entry in entries]
    else:
        document.pop(BLOCK_KEY, None)
    return json.dumps(document, indent=2) + "\n"


__all__ = [
    "BLOCK_KEY",
    "declared_mcp_servers",
    "remove_mcp_server",
    "upsert_mcp_server",
    "writable_config_path",
]
