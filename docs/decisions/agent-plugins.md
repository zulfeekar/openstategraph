# Agent Plugins v1.0.0 — research and verdict

**Status: accepted (research + implementation, 2026-08-09).**
**Verdict: (a) adopt as an EXPORT/IMPORT interop format at a seam module —
never as our package format, never inside `workflow.json`.**

Sources (all primary): the announcement
<https://developers.googleblog.com/agent-plugins-package-your-skills-tools-and-more/>,
the normative spec `spec/1.0.0.md` in
<https://github.com/agentplugins/agent-plugins-spec>, its
`schemas/1.0.0/{plugin,mcp}.schema.json`, `LICENSE.md`, `MAINTAINERS.md`, and
the Agent Skills specification <https://agentskills.io/specification> which
Agent Plugins delegates to for `SKILL.md`.

## 1. What the thing actually is

> "A plugin is a directory."

That is the whole format, and the restraint is the point. Normative facts:

**Manifest — `plugin.json` at the plugin root, required.** The schema is
**closed**: the only permitted top-level fields are `$schema`, `name`,
`version`, `description`, `author`, `homepage`, `repository`, `license`,
`keywords`, `extensions`. Required: `$schema` (MUST be exactly
`https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`) and `name`
(1–64 chars, `[a-z0-9.-]`, alphanumeric first and last, no `--`, no `..`).
An unknown top-level field is reported-and-ignored; any *other* schema
violation is fatal to the whole plugin. Clients MUST NOT fetch the schema
while loading.

**Exactly two portable component types in v1**, discovered from **fixed
locations** that the manifest cannot override or inline:

| Component | Location | Rule |
| --- | --- | --- |
| Skills | `skills/` | each *immediate* child dir containing a regular-file `SKILL.md`; no recursion |
| MCP servers | `mcp.json` | closed object: `$schema` + `mcpServers` only |

`SKILL.md` is governed by the **Agent Skills** spec, not this one: YAML
frontmatter with required `name` (≤64, lowercase/digits/hyphens, must equal
the directory name) and `description` (≤1024), optional `license`,
`compatibility`, `metadata`, `allowed-tools`; optional `scripts/`,
`references/`, `assets/` loaded progressively.

`mcp.json` server entries are a **closed union on `type`**: `stdio`
(`command` as a single executable token — bare name or `./`-relative — plus
`args`/`env`/`cwd`), `streamable-http` and legacy `sse` (`url` absolute, HTTPS
unless loopback, `headers` literal). Only `${PLUGIN_ROOT}` and
`${PLUGIN_DATA}` expand, and only in `args`/`env`/`cwd`. Secrets in `env` or
`headers` are forbidden — they are visible package data.

**Client extensions** are the escape hatch: reverse-domain namespaces, either
as `extensions["com.example.client"]` in the manifest, or as a **top-level
directory** named exactly that namespace, or both. Contents are entirely
client-defined and other clients MUST ignore them without validating.

**Containment**: everything the client reads MUST resolve inside the plugin
root; the spec enumerates *narrowest applicable failure boundaries* (bad
`plugin.json` → reject plugin; bad `skills/` → that component type invalid;
bad one skill → skip that skill; bad one server → skip that server). Partial
failure is designed-in, never fatal.

**Explicit non-goals for v1**: commands, hooks, agents, rules, LSP servers
(named as "too client-specific"), OAuth/credential references, schema
downloads at load time, subprocess sandboxing.

## 2. Coupling, license, maturity — the honest read

- **Not Google-coupled.** Google is *joining* an existing TSC. The Core
  Maintainers are Amazon (Clare Liguori), Cursor (Roshan Sadanani), Microsoft
  (Harald Kirschner), OpenAI (Gav Verma), Vercel (Jonathan Hefner, lead).
  Google's own consumers (Agents CLI, Data Agent Kit) are *clients*, not the
  authority. The format has no Google-specific field anywhere.
- **License is split and permissive**: spec text and docs **CC-BY-4.0**;
  schemas, code, scripts **Apache-2.0**. Both are compatible with this repo's
  MIT backend. Consuming the schema identifiers and shape carries no
  copyleft obligation; we do not vendor their files.
- **Maturity: young but real.** Repo created 2026-04-03, v1.0.0 published
  August 2026, ~766 stars, a GOVERNANCE.md technical charter, a
  FUTURE_CONSIDERATIONS.md. Version is frozen-by-construction: a schema change
  requires a new spec release and published identifiers are never reassigned.
  That is exactly the property an interop target needs.
- **The real risk is not vendor capture, it is scope.** v1 standardizes the
  *box*, and the box holds only skills and MCP. Everything that makes an
  OpenStateGraph workflow a workflow — the graph, tools, functions,
  middleware slots, knowledge — is outside the portable format. Any adoption
  that pretends otherwise would be lossy in the direction that matters.

## 3. Point-by-point against our package format

`workflows/<slug>/`, contract in `api/workflow_store.py::validate_package`:

| Ours | Theirs | Fidelity |
| --- | --- | --- |
| `workflow.json` (envelope + document) | — | **no equivalent**; v1 has no graph concept |
| `AGENTS.md` | — (`description` in manifest, loosely) | lossy summary only |
| `skills/*.md` (flat, concatenated into every agent's prompt) | `skills/<name>/SKILL.md` (dir per skill, frontmatter, progressive) | **structurally mappable, semantically richer on their side** |
| `knowledge/*.md` (on-demand `knowledge_lookup`, index-tier hints) | — | **no equivalent**; flattening into `skills/` would recreate exactly the context bloat `knowledge.py` exists to prevent |
| `tools/*.py`, `functions/*.py` (in-process Python, discovered) | `mcp.json` servers (out-of-process) | **not the same thing**; a Python callable is not an MCP server |
| `middlewares/<slot>.py` (slot table) | — (v1 non-goal: "hooks") | none |
| `tests/`, `data/` | — | none (plain files) |
| — | `mcp.json` | **nothing reads one.** This said *"we have no MCP client at all"* until 2026-08-16, which stopped being true when `tool.mcp` shipped: `prebuilt_mcp.py` is a live `MultiServerMCPClient`. What is missing is the **wiring** — no importer turns an `mcp.json` entry into a `tool.mcp` node — so the gap is real and its name was wrong |

Two genuine convergences worth naming: both are **directory-as-package,
git-diffable, no archive format, no registry required**; and both put
skills in a `skills/` directory. That is convergent evolution on the same
constraints, not a reason to believe the rest maps.

## 4. Verdict

**(a) — export/import interop, implemented at a seam, with the mapping
confined to one module.** Reasoning against the alternatives:

- *Adopt as our format* is rejected outright. It would either drop the graph,
  tools, functions, middleware and knowledge, or smuggle them into a
  reverse-domain extension directory and call that "the format" — which is
  our format wearing their filename. And CLAUDE.md's portability rule is
  law: `workflow.json` is the vendor-neutral layer, and no Agent Plugins
  vocabulary (`plugin.json`, `$schema`, `mcpServers`, `PLUGIN_ROOT`) may
  appear in it or in `core/`.
- *(b) conventions only* undersells it. The manifest is genuinely cheap,
  genuinely closed, and genuinely multi-vendor; publishing a workflow's
  skills so Claude Code / Cursor / Agents CLI can load them is real value we
  get for ~300 lines.
- *(c) reject* would be a fashion statement. Nothing here costs us anything
  we would not pay anyway.

**The seam rule**: `backend/openstategraph/plugin_interop.py` is the *only*
file in this repo that knows the strings `plugin.json`, `mcp.json`,
`SKILL.md`, `${PLUGIN_ROOT}` or the schema identifiers. Delete that file and
nothing else changes shape.

**Our extension namespace: `org.openstategraph`.** Placeholder-grade — the
spec SHOULDs a domain we control, so pin this before publishing anything
public. Everything of ours that v1 cannot express travels there, honestly
labelled as non-portable, rather than being mangled into a portable slot.

## 5. The mapping, with every lossy edge named

### Export (`export_plugin`)

| Our thing | Plugin path | Loss |
| --- | --- | --- |
| slug | `plugin.json` `name` | rejected if it violates §5.5 (we never silently rewrite identity) |
| `AGENTS.md` first paragraph | `description` | truncated at 1024 |
| `skills/<x>.md` | `skills/<x>/SKILL.md` + frontmatter | **description is synthesized** from the doc's first meaningful line; our flat file has no declared description. `<x>` must satisfy the Agent Skills name rule or the skill is skipped with a finding |
| `knowledge/*.md` | `org.openstategraph/knowledge/*.md` | **portable to no other client.** On-demand lookup semantics do not survive; a foreign client sees inert Markdown it will not load |
| `workflow.json`, `tools/`, `functions/`, `middlewares/`, `tests/` | `org.openstategraph/…` | same: carried, not portable |
| `data/`, `__pycache__` | not exported | deliberate — fixtures and binaries are not distribution payload |
| — | `mcp.json` | **never emitted.** We model no MCP servers; inventing one from a Python tool would be a lie |

### Import (`import_plugin`)

| Plugin thing | Our package | Loss |
| --- | --- | --- |
| `plugin.json` | validated; `name`/`description` seed the workflow envelope | unknown top-level fields reported and ignored, per §5.2 |
| `skills/<x>/SKILL.md` | `skills/<x>.md` (frontmatter stripped, body kept) | frontmatter metadata (`allowed-tools`, `compatibility`, `license`) is **dropped** — our loader has nowhere to put it |
| `skills/<x>/{scripts,references,assets}/…` | copied under `skills/<x>/` | **our `discover_skills` globs `skills/*.md` only, so these files are inert.** Reported, not hidden |
| `mcp.json` | nothing | Every server is reported as unsupported; none is silently dropped. Not for want of a client — `tool.mcp` binds MCP servers to agents today — but because no importer maps an `mcp.json` entry onto one |
| `org.openstategraph/…` | restored in place | round-trips our own exports losslessly |
| other `com.*` extension dirs | ignored | per §8.1, without validating |
| absent `workflow.json` | a **skeleton** envelope (zero nodes/edges) | an imported plugin is a *package to open in the editor*, never a runnable graph |

Import returns a **plan**, and materializing it is a separate call with an
explicit destination. Nothing writes into `workflows/` implicitly.

## 6. What was built

- `backend/openstategraph/plugin_interop.py` — `export_plugin`,
  `write_export`, `import_plugin`, `write_import`, plus `PluginExport` /
  `ImportPlan` carrying `notes` (the lossy edges, surfaced at runtime rather
  than only in this document).
- `GET /api/workflows/{slug}/plugin-export` — returns manifest + layout +
  notes as JSON (a preview/report, no bytes written to disk by a GET).
- `backend/tests/test_plugin_interop.py` — spec-conformance, containment,
  lossy-edge and round-trip tests, all against tmp-dir fixtures with
  invented slugs (`workflows/` is untouched).

Deliberately **not** built: an editor affordance. The Export dialog already
exists and this is a report-level capability; a button is cheap to add later
against the endpoint and expensive to design now.

## 7. Re-open this decision when…

- v1.1+ standardizes **agents, commands or rules** — the FUTURE_CONSIDERATIONS
  list. Agents standardizing would be the first time their box could hold
  something shaped like a workflow node.
- ~~We gain an MCP client.~~ **We have one** (`tool.mcp`, `prebuilt_mcp.py`).
  The re-open trigger is therefore already pulled: what remains is mapping an
  `mcp.json` entry onto a `tool.mcp` node so it becomes a real import target
  instead of a reported gap, and export could publish our tools as MCP servers.
- We publish plugins publicly — at which point `org.openstategraph` must be
  replaced by a namespace on a domain we actually control.
