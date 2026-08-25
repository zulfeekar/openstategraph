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
