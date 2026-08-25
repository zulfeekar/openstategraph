# What the zee-lab already tried

Mined read-only from `.../cpl-intelligence/backend/_r&d/zee-lab` (an Equinor employer
repository — nothing there was changed). Findings below are labelled **[doc]** for a
design document's claim or **[code]** for something an actual file implements.

## MCP-agnostic design — not the same problem we have

**[doc]** `MCP_AGNOSTIC_DESIGN.md`'s actual argument is about *server selection*, not
*framework portability*. Their goal: zee should know no MCP server until a user
registers one via a `#` command and locks it for the session — no hardcoded server,
tools not baked into the graph at import time. Their chosen mechanism, **[code]**
confirmed in `server/agui_app.py`: hot-swap `_agent.graph` on `POST /mcp/select`,
rebuilding the compiled graph with the locked server's tools rather than gating tool
visibility per turn with `wrap_model_call` middleware (they considered the
middleware route and rejected it as "fiddly and hard to test without the live UI").
This says nothing about running the same tool surface on a non-LangGraph host — it
never questions LangGraph as the runtime. Our portability rule (`workflow.json` as
the vendor-neutral layer, no `IOrchestrator`) is unaffected; this lab did not attempt
the thing that would test it.

## Gap analysis — a gap already measured elsewhere

**[doc]** `GAP_ANALYSIS.md` compares zee against the LangChain deep-agents harness
checklist and finds these missing: filesystem `permissions=`, a code-execution
sandbox, `skills=`/`memory=` (progressive disclosure), a durable checkpointer
(theirs is in-memory `MemorySaver`, lost on restart), `SummarizationMiddleware`
(named as the actual cause of Ollama-cloud 500s from context bloat), HITL
`interrupt_on` (documented as unwired at the time the gap doc was written), and
`HarnessProfile` per-model bundles. Most of these are things we already have a
answer for (retry/timeout/cache as graph-assembly params, our own middleware
slot-table) or don't need (we're a compiler, not a harness runtime) — the
summarization-vs-context-bloat gap is the one worth flagging as a live risk class
for any long agent run against a lakehouse, ours included.

## HITL / resume — real code, distinct from a resume-the-run mechanism

**[code]** `core/hitl.py` + `_smoke_hitl.py` prove an actual interrupt/resume cycle
against `deepagents.create_deep_agent`: `interrupt_on={tool: True}` pairs with a
durable checkpointer (here `AsyncSqliteSaver`); resume re-invokes the **same**
`thread_id` with `Command(resume={"decisions":[{"type":"approve"}]})`. Two rules
worth adopting verbatim: **fail-closed** — `require_checkpointer_or_refuse` raises
if a capability declares `hitl_tool_names` but no checkpointer is wired, so an
interrupt can never silently no-op into "ran anyway"; and decisions are matched to
gated calls **in action order**, not by id, so a batched interrupt resumes
correctly. This is proven by the smoke script actually running two passes
(pre-interrupt, then resumed) and asserting `__interrupt__` clears.

**[doc/naming trap]** `_smoke_resume.py` is not about run-resume at all — it exercises
`capabilities/job_application.tailor_resume` (rewriting a candidate's CV PDF against
a job description). Worth noting only so nobody else goes looking for a second
interrupt-resume pattern here and wastes time on a misnamed file.

## capabilities/ and extensions/ — a real registry, matching our own shape

**[code]** `core/registry.py` + `capabilities/__init__.py` is a genuine registry, and
its shape lines up with ours: a frozen, primitive-only `CapabilityDescriptor`
(Pydantic, `extra="forbid"`) is `register()`ed into a plain `dict[str, ...]` keyed by
id, duplicate id raises `ValueError`, and `capabilities/__init__.py::load_all()`
auto-discovers every module in the package exposing a `DESCRIPTOR` via
`pkgutil.iter_modules` — "drop a module in `capabilities/`, zero edits to the
supervisor." The descriptor is deliberately data-only (no `BaseTool`, no callables)
so the registry module imports without dragging in `deepagents`/`langchain_core`,
mirroring our own registries-are-data-not-code discipline. `extensions/` was not
inspected beyond its directory listing (`zee-copilot-proxy`) — no doc explains its
registration path, so nothing to report there.

## Pattern store / few-shot cache — a name only, no implementation

**[doc]** `mcp_lookup_few_shot` appears in three places: a narration string in
`server/narration_middleware.py` ("Looking up a verified query example for this
question"), a skill doc telling the agent never to name the tool aloud, and
`PLAN.md`, which lists it among MCP SQL tools to **reuse** ("already shipped,
T-SQL-aware, exercised by the live MCP servers"). In every case the store itself
lives on an external MCP server this lab calls but does not implement — there is no
admission rule, no staleness check, no schema for an entry anywhere in this
repository. This settles nothing for `launch-readiness/99`: it is evidence that the
tool *name* is a known convention across at least two Equinor-adjacent projects, not
evidence of how an entry gets verified or expired.

## Offload backend and skills loading — the two things the last pass missed

**[test-proven]** `server/offload_backend.py::OffloadLogMiddleware` is a
**transparent logging wrapper**, not the offload mechanism itself. Per its own
docstring and `tests/test_offload_backend.py`: the authoritative store for
`/large_tool_results/` is `StateBackend` — LangGraph's per-thread checkpointed
state, in-memory/state-backed exactly like ours, not real files. The
middleware only (a) emits grep-friendly log lines (`[OFFLOAD WRITE]` /
`READ`/`LS`/`GLOB`/`GREP`, thread-scoped) and (b) optionally **mirrors**
`write_file` content to `.dev-offload/<thread_id>/<relative_path>` on disk for
an operator to inspect after the fact — `mirror_root=None` disables the mirror
entirely (log-only mode, proven by `test_no_mirror_when_root_is_none`). The
mirror is written but never read back by the agent; retrieval during a run
still goes through the state-backed `ls`/`grep`/`read_file` tools, matching
`skills/reuse-fetched-data/SKILL.md`'s instructions. So: **what/when/where** —
the agent writes when it offloads a large tool result; middleware observes
every `write_file`/`read_file`/`ls`/`glob`/`grep` call whose path starts with
`/large_tool_results/` and no others (`TestNoNoise`, test-proven); the
authoritative copy stays in LangGraph state, the disk copy is a side-channel
mirror. **What stays in context** in place of content: nothing special beyond
the normal tool-call/result exchange — the model still calls `write_file` with
the full content itself; the offload discipline is "write it out, then refer
to it by path," enforced only by skill-doc instruction (see below), not by
middleware substitution.

**[test-proven]** `.dev-offload/` on disk is real and does survive a
process/run — three thread-id directories with real `.json`/`.geojson`/`.txt`
files sit there right now — but this does **not** touch `launch-readiness/99`.
It is an operator debug artefact (namespaced by `thread_id`, one dir per
session, files named exactly as the agent named them), not a queryable,
cross-session store the *agent* reads from on a later run: nothing in this
repo lists, greps, or loads `.dev-offload/` back into an agent's context.
`launch-readiness/99`'s "verified pattern store" (admitted only on
success+grader-pass, with a staleness sweep) is a different, unbuilt thing;
this mirror has no admission rule and no reader. No update to ticket 99 is
warranted.

**[test-proven]** `core/sandbox.py::GeneratedArtifactBackend` is the actual
jail (`tests/test_sandbox_jail.py`, all green-path assertions are direct calls
into `_validate`, not mocks): normalises the path, rejects any component equal
to `..`, rejects `~`, rejects escapes above the `/zee/` virtual root, and
rejects any extension outside `ALLOWED_WRITE_EXTS` (`.pdf .json .md .csv .txt
.html .docx .pptx .xlsx` — explicitly excludes `.py`/`.exe`/`.sh`). A refusal
returns a `WriteResult(error=...)`, never raises — the agent sees a
ToolMessage, not a stack trace (`test_write_file_refuses_bad_path_without_raising`).
This is **disk**, separate from the `/large_tool_results/` offload path
entirely: it mounts real deepagents `FilesystemBackend(virtual_mode=True)` at
`/zee/<safe_user>/` in a `CompositeBackend`, rooted per authenticated user
(`safe_user()` sanitises the email to `[A-Za-z0-9._-]`, defaults to `"zee"`
for anonymous). The jail is enforced by `virtual_mode=True` (deepagents' own
path normalisation/sandboxing) plus this project's own extension allow-list
and traversal checks layered on top — belt and suspenders, both test-proven.

**[test-proven]** Skills are loaded through `deepagents.middleware.skills.SkillsMiddleware`
(a library feature, not custom code) via the *same* `CompositeBackend` routing
mechanism as everything else: `/skills/` routes to a `FilesystemBackend`
rooted at the `skills/` dir. Each skill is a directory containing exactly one
`SKILL.md` with YAML frontmatter (`name`, `description`, optionally
`allowed-tools`) followed by Markdown body — a plain file, i.e. **data, not
code**. At startup only the **name + description** of every skill go into the
system prompt (confirmed by reading
`deepagents/middleware/skills.py`: "progressive disclosure — you see their
name and description above, but only read full instructions when needed").
The model then **chooses at runtime**, based on whether the task matches a
skill's description, to `read_file` the full `SKILL.md` body — there is no
keyword router and no capability-based scoping; selection is entirely
model-judgement over the description string, and `using-mcp/SKILL.md`'s own
frontmatter leans on this by writing `description: "MANDATORY: Read this
skill file BEFORE calling ANY MCP server tool..."` to bias the model into
reading it. This directly contrasts with our own approach: we attach all
twelve Markdown files at once, unconditionally, with no equivalent selection
step and no per-skill token cost only paid when relevant. Here only the
short descriptions are a fixed system-prompt cost; the body is loaded lazily,
per skill, only when the model decides it applies — which is exactly the
scaling lever our flat-attachment design lacks. Cost/tradeoff worth noting
plainly: this shifts the failure mode from "always paying the tokens" to
"sometimes the model doesn't recognise a skill applies and never reads it" —
untested here, no eval of skill-selection recall exists in this repo.
