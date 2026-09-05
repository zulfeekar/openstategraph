"""The Agent Plugins v1.0.0 seam — and the only file that knows their words.

Research and verdict: `docs/decisions/agent-plugins.md`. In one line: Agent
Plugins standardizes *the box* (a directory with `plugin.json`, `skills/`,
`mcp.json`), it is genuinely multi-vendor (Amazon, Cursor, Microsoft, OpenAI,
Vercel on the TSC; Google joining), and its v1 scope holds two component types
only — Agent Skills and MCP servers. A workflow is not in that scope.

So this is **interop, not adoption**. Nothing else in the repo may learn the
strings ``plugin.json``, ``mcp.json``, ``SKILL.md``, ``${PLUGIN_ROOT}`` or the
schema identifiers; CLAUDE.md's portability rule makes ``workflow.json`` the
vendor-neutral layer, and a compile-style seam is one-directional by design.
Delete this module and no other file changes shape.

Two directions, both pure: ``export_plugin``/``import_plugin`` compute a
*plan* (manifest, path → text layout, and the honest list of what was lost);
``write_export``/``write_import`` are the only calls that touch a disk, and
only at a destination the caller names.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openstategraph._extras import document_extras, install_hint
from openstategraph.agent_config import ServerDescriptor
from openstategraph.skills import SkillDocument, has_frontmatter

#: Canonical schema identifiers (spec §5.2, §7.2.1). They MUST be exact — a
#: client selects its validation rules from the literal string, and MUST NOT
#: fetch it. We never retrieve them either.
PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

#: Our reverse-domain client namespace (spec §8). Everything of ours that v1
#: cannot express travels here — labelled non-portable rather than mangled
#: into a portable slot.
#:
#: **Pinned, and the domain is ours** (owner decision 2026-08-16, ticket 32).
#: Until then this comment called the value "placeholder-grade" and said to
#: pin it before publishing anything public, while `backend/pyproject.toml`'s
#: release checklist already called it pinned and `gap-register.md` PK-03
#: rated it a 1.0 blocker. All three described the same string and disagreed,
#: because two different things were being called "pinned": the *value* never
#: wobbled, and the *domain* was the open question. §8 asks for a
#: reverse-domain namespace on a domain the publisher controls, and
#: `openstategraph.org` now is one.
#:
#: Do not change this string casually. `export_plugin()` writes an
#: `org.openstategraph/` directory into every bundle a user exports, and those
#: bundles land in other people's repositories — the cost of changing it grows
#: with every export, which is why it was worth settling before 1.0 rather
#: than after.
EXTENSION_NAMESPACE = "org.openstategraph"

#: Permitted top-level manifest fields — the schema is *closed* (§5.2).
_MANIFEST_FIELDS = frozenset(
    {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "extensions",
    }
)

#: §5.5 plugin name, and the Agent Skills name rule (which additionally
#: forbids periods and must equal the skill's directory name).
_PLUGIN_NAME_RE = re.compile(r"^(?!.*--)(?!.*\.\.)[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
_SKILL_NAME_RE = re.compile(r"^(?!.*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

_DESCRIPTION_MAX = 1024

#: Package directories carried into our extension directory on export. `data/`
#: is fixtures and binaries, not distribution payload; `__pycache__` is noise.
_CARRIED_DIRS = ("knowledge", "tools", "functions", "middlewares", "tests")
_CARRIED_FILES = ("workflow.json", "AGENTS.md")
_EXCLUDED = ("__pycache__", ".pytest_cache")


class InvalidPluginError(Exception):
    """A package or plugin that cannot be represented in the other format.

    Raised only for *fatal* boundaries — an unrepresentable identity, a
    manifest violation the spec calls fatal (§5.3, §11.3), a destination that
    already holds a package. Everything narrower is a note, never an
    exception: the spec's own failure model is "skip the component, keep
    loading, report it", and an interop tool that raises where the spec skips
    would be less usable than the format it bridges.
    """


@dataclass(frozen=True)
class PluginExport:
    """One workflow package rendered as an Agent Plugins v1 layout."""

    manifest: dict[str, Any]
    #: Plugin-relative path -> file text. `plugin.json` is *not* in here; it
    #: is `manifest`, serialized by `write_export`, so a caller can inspect
    #: the manifest as data rather than reparse it.
    files: dict[str, str]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImportPlan:
    """One plugin rendered as a workflow package skeleton."""

    name: str
    #: Package-relative path -> file text, `workflow.json` included: unlike
    #: the export direction, the envelope here is *synthesized*, so it is
    #: content rather than metadata.
    files: dict[str, str]
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------- export


def export_plugin(workflow_dir: Path, *, name: str | None = None) -> PluginExport:
    """Render `workflows/<slug>/` as an Agent Plugins v1 layout.

    The slug *is* the plugin name: identity is never silently rewritten to
    satisfy a foreign naming rule, so a slug that cannot be a plugin name is
    an error the human resolves, not a rename this function invents.
    """
    workflow_dir = Path(workflow_dir)
    plugin_name = name or workflow_dir.name
    if not _PLUGIN_NAME_RE.match(plugin_name):
        raise InvalidPluginError(
            f"{plugin_name!r} cannot be an Agent Plugins name: lowercase alphanumerics, "
            "'-' and '.', 1-64 chars, alphanumeric at both ends, no '--' or '..'"
        )

    notes: list[str] = []
    files: dict[str, str] = {}

    manifest: dict[str, Any] = {"$schema": PLUGIN_SCHEMA_ID, "name": plugin_name}
    description = _description_from_agents_md(workflow_dir / "AGENTS.md")
    if description:
        manifest["description"] = description

    _export_skills(workflow_dir / "skills", files, notes)
    _export_extension(workflow_dir, files, notes)

    notes.append(
        "No mcp.json emitted: this runtime models no MCP servers, and a Python tool in "
        "tools/ is not one. Emitting a server entry would be a fabrication."
    )
    # Last, and it has to be: the README renders `notes` as its "did not come
    # with it" section, so composing it earlier would publish a shorter list
    # than the one the caller is handed.
    files["README.md"] = _readme(workflow_dir, plugin_name, files, notes)
    return PluginExport(manifest=manifest, files=files, notes=notes)


def _export_skills(skills_dir: Path, files: dict[str, str], notes: list[str]) -> None:
    """`skills/<x>.md` -> `skills/<x>/SKILL.md`.

    The header is composed by `SkillDocument.render`, never assembled here:
    that format has exactly one implementation (`openstategraph.skills`), and
    this function used to be a second one. Reading before writing is what the
    consolidation buys — a doc that already declares a `description` keeps it
    instead of having the line `---` synthesized over the top of it.
    """
    if not skills_dir.is_dir():
        return
    synthesized = False
    for path in sorted(skills_dir.glob("*.md")):
        stem = path.stem
        if not _SKILL_NAME_RE.match(stem):
            notes.append(
                f"skill {stem!r} skipped: an Agent Skills name is lowercase alphanumerics and "
                "hyphens only, and must equal its directory name"
            )
            continue
        text = _read_text(path)
        if text is None:
            notes.append(f"skill {stem!r} skipped: not readable as UTF-8 text")
            continue
        doc = SkillDocument.parse(text, name=stem)
        description = doc.description
        if not description:
            synthesized = True
            description = _first_meaningful_line(doc.body)[:_DESCRIPTION_MAX] or (
                f"The {stem} skill."
            )
        # The directory name is the skill's name in v1 (§7.1), so `stem` wins
        # over any name the file declares for itself.
        files[f"skills/{stem}/SKILL.md"] = SkillDocument(
            name=stem, description=description[:_DESCRIPTION_MAX], body=doc.body
        ).render()
    if synthesized:
        notes.append(
            "Some skill descriptions are synthesized from the doc's first line — a flat "
            "skills/*.md that declares no frontmatter has none. Review them before publishing."
        )


def _export_extension(workflow_dir: Path, files: dict[str, str], notes: list[str]) -> None:
    """Everything v1 has no component type for, into our namespace directory."""
    carried: list[str] = []
    for filename in _CARRIED_FILES:
        text = _read_text(workflow_dir / filename)
        if text is not None:
            files[f"{EXTENSION_NAMESPACE}/{filename}"] = text
            carried.append(filename)
    for dirname in _CARRIED_DIRS:
        source = workflow_dir / dirname
        if not source.is_dir():
            continue
        found = False
        for path in sorted(source.rglob("*")):
            if not path.is_file() or any(part in _EXCLUDED for part in path.parts):
                continue
            text = _read_text(path)
            if text is None:
                notes.append(f"{path.relative_to(workflow_dir)} skipped: not UTF-8 text")
                continue
            files[f"{EXTENSION_NAMESPACE}/{path.relative_to(workflow_dir).as_posix()}"] = text
            found = True
        if found:
            carried.append(f"{dirname}/")
    if carried:
        note = (
            f"Carried into {EXTENSION_NAMESPACE}/ (no portable v1 component type, so no other "
            f"client will load it): {', '.join(carried)}."
        )
        if "knowledge/" in carried:
            note += (
                " knowledge/ in particular loses its on-demand lookup semantics and reads as "
                "inert Markdown elsewhere."
            )
        notes.append(note)
    if (workflow_dir / "data").is_dir():
        notes.append("data/ excluded: fixtures and binaries are not distribution payload.")


#: The package directories wired by discovery rather than by the document. A
#: bundle carrying one of these is a bundle whose recipient can lose the wiring
#: silently, which is the only reason the README says anything about them.
_WIRED_DIRS = ("tools", "functions", "middlewares", "knowledge")


def _readme(
    workflow_dir: Path, plugin_name: str, files: dict[str, str], notes: list[str]
) -> str:
    """The bundle's README: what to install, and what did not survive the crossing.

    Every line here is false for some package. The install line is derived from
    the document's own model strings and tiers (`_extras.document_extras`), the
    "did not come with it" bullets *are* `notes` rendered as Markdown rather
    than prose composed beside them — so they cannot drift from the refusals
    that produced them — and the discovery-convention warning appears only when
    the bundle actually carries a directory that discovery wires. A package
    without a thing is not told about it (`export-and-eject/12`).
    """
    document = _document_of(workflow_dir)
    needs = document_extras(document)
    lines = [f"# {plugin_name}", ""]
    lines.append(
        "Exported from OpenStateGraph as an Agent Plugins v1 bundle. This file is "
        "generated by the export; edit the package, not this."
    )
    lines += ["", "## What this needs", ""]
    if needs.extras:
        lines += ["```", install_hint(",".join(needs.extras)), "```", ""]
        lines.append("Each extra, and what in this document asks for it:")
        lines += [f"- `[{extra}]` — {why}" for extra, why in needs.reasons]
    else:
        lines += [
            "```",
            "pip install openstategraph",
            "```",
            "",
            "This document names no provider, no deep-tier node and no sqlite "
            "checkpointer, so it asks for no extra.",
        ]
    if needs.unknown_providers:
        lines += [
            "",
            "Not recognised by this installation's provider catalogue, so no install "
            "line is guessed for them: "
            + ", ".join(f"`{prefix}`" for prefix in needs.unknown_providers)
            + ".",
        ]
    workflow_path = f"{EXTENSION_NAMESPACE}/workflow.json"
    if workflow_path in files:
        from openstategraph.api.workflow_store import is_slug

        # `load_workflow` refuses a directory whose name is not a slug, because
        # the slug is what scopes tool, function, skill and knowledge discovery
        # — and `org.openstategraph` has a period in it by construction (§8
        # wants a reverse domain). So the payload directory is *not* loadable
        # under its own name, and a recipe that pretended otherwise would be
        # the one kind of line this README exists to prevent: verified, it
        # raises `InvalidPackageName`.
        lines += ["", f"The workflow itself is `{workflow_path}`."]
        if is_slug(plugin_name):
            lines += [
                "`load_workflow` needs a slug-shaped directory name and "
                f"`{EXTENSION_NAMESPACE}` is not one (a period cannot appear in a "
                "package slug), so copy it out under this plugin's own name first:",
                "",
                "```sh",
                f"cp -R {EXTENSION_NAMESPACE} {plugin_name}",
                "```",
                "",
                "```python",
                "from openstategraph import load_workflow",
                "",
                f'workflow = load_workflow("{plugin_name}")',
                "```",
            ]
        else:
            lines += [
                "`load_workflow` needs a directory whose name is a slug (lowercase "
                f"letters, digits and hyphens), and neither `{EXTENSION_NAMESPACE}` "
                f"nor `{plugin_name}` is one — copy the directory out under a name "
                "that is before loading it.",
            ]
    lines += ["", "## What did not come with it", ""]
    lines += [f"- {note}" for note in notes]
    wired = _wired_dirs_in(files)
    if wired:
        lines += [
            "",
            "This bundle carries "
            + ", ".join(f"`{name}/`" for name in wired)
            + ", and those are wired by OpenStateGraph's own discovery conventions "
            "rather than by anything in the document. Compile the document by hand, "
            "or load it with anything but `load_workflow`, and the failure is silent: "
            "the agent is drawn with three tools, bound to none, and confidently "
            "answers from parametric memory. `load_workflow` reports that on "
            "`.warnings`, and `openstategraph validate` answers the same question "
            "before a run costs anything.",
        ]
    return "\n".join(lines) + "\n"


def _wired_dirs_in(files: dict[str, str]) -> list[str]:
    """Which discovery-wired directories this bundle actually carries."""
    prefixes = {f"{EXTENSION_NAMESPACE}/{name}/": name for name in _WIRED_DIRS}
    carried = {name for path in files for prefix, name in prefixes.items() if path.startswith(prefix)}
    if any(path.startswith("skills/") for path in files):
        carried.add("skills")
    return [name for name in (*_WIRED_DIRS, "skills") if name in carried]


def _document_of(workflow_dir: Path) -> dict[str, Any]:
    """The `document` inside `workflow.json`, or an empty one.

    Tolerant on purpose: a package whose envelope will not parse still gets a
    bundle and a README, and the README then claims no extras rather than
    refusing to exist. The document is the only thing a missing file costs.
    """
    text = _read_text(workflow_dir / "workflow.json")
    if text is None:
        return {}
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(envelope, dict):
        return {}
    document = envelope.get("document")
    return document if isinstance(document, dict) else envelope


# ------------------------------------------------- export: the toolkit


#: The bundle's own name — a directory somebody installs, not the key an
#: `mcpServers` object is indexed by. The two read the same today and are
#: deliberately separate values: `ServerDescriptor.name` is what an agent
#: config calls our server, and renaming one has no business renaming the
#: other.
TOOLKIT_PLUGIN_NAME = "openstategraph"


def export_toolkit(
    *, server: ServerDescriptor | None = None, name: str = TOOLKIT_PLUGIN_NAME
) -> PluginExport:
    """This installation's skills and its MCP server, as one plugin directory.

    `osg-agent-experience/28`. The other export function above renders a
    *workflow package*, which has no server, so it emits no `mcp.json` and
    says so in a note. This one is the opposite shape: no graph, no tools, no
    knowledge — the wheel's three skills and the one stdio server `init`
    already configures four agents to launch.

    **The command line is not written here.** `agent_config.ServerDescriptor`
    is the single fact the four `init` renderers read, and it is the single
    fact this one reads too; a literal `"openstategraph"` and `["mcp"]` in
    this module would be the fifth hand-maintained copy of exactly the block
    `agent_config` was written to stop copying — and the line a copy drops is
    always `OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`.

    The seam rule holds in the direction it was written: this module reads the
    descriptor, `agent_config` never reads a plugin directory.
    """
    from openstategraph.bundled_skills import bundled_skill_files

    if not _PLUGIN_NAME_RE.match(name):
        raise InvalidPluginError(f"{name!r} cannot be an Agent Plugins name")
    descriptor = server if server is not None else ServerDescriptor()

    notes: list[str] = []
    files: dict[str, str] = {}
    for (_skill, relative), source in bundled_skill_files().items():
        text = _read_text(source)
        if text is None:
            notes.append(f"{relative} skipped: not readable as UTF-8 text")
            continue
        files[f"skills/{relative}"] = text

    files["mcp.json"] = (
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                # `type` is stated rather than inferred: §7.2.2's entry is a
                # closed union on it, and the one agent config that also names
                # a transport (VS Code) proves nothing else about the other
                # three — they infer stdio from `command`, a plugin client
                # selects its rules from the literal.
                "mcpServers": {descriptor.name: {"type": "stdio", **descriptor.entry()}},
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    notes.append(
        "No workflow travels in this bundle: it is the toolkit, not a package. "
        "`openstategraph export plugin <package>` is the other direction."
    )
    notes.append(
        "The server entry launches the console script this wheel installs. A machine "
        "that installs the plugin and not the wheel has a bundle that cannot start."
    )
    return PluginExport(
        manifest={
            "$schema": PLUGIN_SCHEMA_ID,
            "name": name,
            "description": descriptor.description[:_DESCRIPTION_MAX],
        },
        files=files,
        notes=notes,
    )


def write_export(export: PluginExport, destination: Path) -> Path:
    """Materialize a `PluginExport` at `destination`. The only disk write."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "plugin.json").write_text(
        json.dumps(export.manifest, indent=2, ensure_ascii=False) + "\n"
    )
    _write_files(export.files, destination)
    return destination


# --------------------------------------------------------------- import


def import_plugin(plugin_dir: Path) -> ImportPlan:
    """Render an Agent Plugins v1 package as a workflow package skeleton.

    A *skeleton*: the plugin carries no graph, so the synthesized
    `workflow.json` has zero nodes and zero edges. An imported plugin is a
    package to open in the editor, never a runnable workflow.
    """
    plugin_dir = Path(plugin_dir)
    root = plugin_dir.resolve()
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.is_file():
        raise InvalidPluginError(f"no plugin.json in {plugin_dir.name}/")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise InvalidPluginError(f"plugin.json unreadable ({exc})") from exc
    if not isinstance(manifest, dict):
        raise InvalidPluginError("plugin.json must contain a top-level object")

    notes: list[str] = []
    # §5.2: an unknown top-level field is reported and ignored; every other
    # violation of §5.3 is fatal to the whole plugin.
    unknown = sorted(set(manifest) - _MANIFEST_FIELDS)
    if unknown:
        notes.append(f"ignored unknown plugin.json fields (not in the closed schema): {unknown}")
    if manifest.get("$schema") != PLUGIN_SCHEMA_ID:
        raise InvalidPluginError(
            f"unsupported Agent Plugins version: $schema must be {PLUGIN_SCHEMA_ID}"
        )
    name = manifest.get("name")
    if not isinstance(name, str) or not _PLUGIN_NAME_RE.match(name):
        raise InvalidPluginError(f"invalid plugin name: {name!r}")

    files: dict[str, str] = {}
    _import_extension(plugin_dir, root, files, notes)
    _import_skills(plugin_dir / "skills", root, files, notes)
    _import_mcp(plugin_dir / "mcp.json", notes)

    files.setdefault(
        "workflow.json",
        json.dumps(
            {
                "version": 1,
                "name": name,
                "savedAt": "",
                "document": {"nodes": [], "edges": []},
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )
    files.setdefault("AGENTS.md", _imported_agents_md(name, manifest.get("description")))
    for entry in sorted(plugin_dir.iterdir()) if plugin_dir.is_dir() else []:
        if entry.is_dir() and _is_extension_namespace(entry.name) and entry.name != EXTENSION_NAMESPACE:
            notes.append(f"ignored client extension directory {entry.name}/ (§8: not ours)")
    return ImportPlan(name=name, files=files, notes=notes)


def _import_skills(skills_dir: Path, root: Path, files: dict[str, str], notes: list[str]) -> None:
    """`skills/<x>/SKILL.md` -> our flat `skills/<x>.md`, frontmatter dropped."""
    if not skills_dir.is_dir():
        return
    inert: list[str] = []
    dropped = False
    # §7.1: immediate children only, never a recursive search.
    for child in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        if not _within(skill_md, root):
            notes.append(f"skill {child.name!r} skipped: SKILL.md resolves outside the plugin root")
            continue
        text = _read_text(skill_md)
        if text is None:
            notes.append(f"skill {child.name!r} skipped: SKILL.md is not UTF-8 text")
            continue
        if has_frontmatter(text):
            dropped = True
        files[f"skills/{child.name}.md"] = SkillDocument.parse(text).body + "\n"
        for path in sorted(child.rglob("*")):
            if not path.is_file() or path == skill_md or not _within(path, root):
                continue
            resource = _read_text(path)
            if resource is None:
                continue
            relative = path.relative_to(skills_dir).as_posix()
            files[f"skills/{relative}"] = resource
            inert.append(relative)
    if dropped:
        notes.append(
            "SKILL.md frontmatter (name/description/allowed-tools/compatibility/license) is "
            "dropped: our skills loader concatenates plain Markdown and has nowhere to put it."
        )
    if inert:
        notes.append(
            "carried but inert — discover_skills globs skills/*.md only, so these are never "
            f"loaded: {sorted(inert)}"
        )


def _import_extension(plugin_dir: Path, root: Path, files: dict[str, str], notes: list[str]) -> None:
    """Restore our own extension directory — this is what round-trips."""
    source = plugin_dir / EXTENSION_NAMESPACE
    if not source.is_dir():
        return
    restored = False
    for path in sorted(source.rglob("*")):
        if not path.is_file() or not _within(path, root):
            continue
        text = _read_text(path)
        if text is None:
            continue
        files[path.relative_to(source).as_posix()] = text
        restored = True
    if restored:
        notes.append(f"restored this workflow's own parts from {EXTENSION_NAMESPACE}/")


def _import_mcp(mcp_path: Path, notes: list[str]) -> None:
    """Report every server. Nothing maps one onto a node, and silence would be a lie.

    This docstring said "we have no MCP client" until 2026-08-16, and the note
    below said it to the user. It stopped being true when `tool.mcp` shipped:
    `prebuilt_mcp.py` wraps a real `MultiServerMCPClient` and binds every tool
    a server offers onto an agent. What is genuinely missing is the *importer*
    — nothing turns an `mcp.json` entry into a `tool.mcp` node — which is a
    smaller gap and, unlike the old wording, one the reader can act on: the
    node type they need already exists.
    """
    if not mcp_path.is_file():
        return
    try:
        config = json.loads(mcp_path.read_text())
        servers = config["mcpServers"]
        assert isinstance(servers, dict)
    except (json.JSONDecodeError, OSError, KeyError, AssertionError):
        notes.append("mcp.json present but unreadable or malformed; MCP disabled for this plugin")
        return
    for server, entry in sorted(servers.items()):
        transport = entry.get("type") if isinstance(entry, dict) else "?"
        notes.append(
            f"MCP server {server!r} ({transport}) not imported: nothing maps an "
            "mcp.json entry onto a node yet. Nothing was dropped silently — add a "
            "'MCP server' (tool.mcp) card and name this server on it, or see "
            "docs/decisions/agent-plugins.md §7."
        )


def write_import(plan: ImportPlan, destination: Path) -> Path:
    """Materialize an `ImportPlan` at `destination`, refusing to clobber."""
    destination = Path(destination)
    if (destination / "workflow.json").exists():
        raise InvalidPluginError(
            f"{destination} already holds a workflow package; import into a fresh directory"
        )
    destination.mkdir(parents=True, exist_ok=True)
    _write_files(plan.files, destination)
    return destination


# --------------------------------------------------------------- shared


def _write_files(files: dict[str, str], destination: Path) -> None:
    root = destination.resolve()
    for relative, text in files.items():
        target = (destination / relative).resolve()
        if not _within(target, root):
            raise InvalidPluginError(f"{relative!r} escapes {destination}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def _within(path: Path, root: Path) -> bool:
    """§4.1 containment: the *resolved* path must stay inside the root."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def _description_from_agents_md(path: Path) -> str:
    text = _read_text(path)
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    body = [line for line in lines[1:] if line] if lines and lines[0].startswith("#") else [
        line for line in lines if line
    ]
    return (body[0] if body else "")[:_DESCRIPTION_MAX]


def _is_extension_namespace(name: str) -> bool:
    return "." in name and name.split(".")[0] in {"com", "org", "io", "net", "dev", "ai"}


def _imported_agents_md(name: str, description: str | None) -> str:
    return (
        f"# {name}\n\n"
        f"{description or 'Imported from an Agent Plugins v1 package.'}\n\n"
        "Imported as a **skeleton**: an Agent Plugins package carries skills and MCP servers, "
        "never a graph, so `workflow.json` has no nodes yet. Open it in the editor and build "
        "one. See `docs/decisions/agent-plugins.md` for what the import could and could not "
        "carry across.\n"
    )


__all__ = [
    "EXTENSION_NAMESPACE",
    "MCP_SCHEMA_ID",
    "PLUGIN_SCHEMA_ID",
    "ImportPlan",
    "InvalidPluginError",
    "PluginExport",
    "export_plugin",
    "import_plugin",
    "write_export",
    "write_import",
]
