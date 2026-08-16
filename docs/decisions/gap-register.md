# The gap register — every known deferral, in one place

**Status: in force from 2026-08-10.** Resolves wayfinder ticket 02 of
`.scratch/docs-and-gaps/`. This file replaces "it's recorded somewhere in a
session report" as the answer to *what is not done?*

## How to read this

Every entry names its evidence — a `file:line`, a doc section, or a commit —
because **a gap without evidence is not a gap, it is a worry**.

> **Fourteen entries currently cite `.scratch/**/tickets/*.md` as their only
> evidence** (2026-08-13). `.scratch/` is session planning, not a published
> artifact — so for anyone but the author those entries fail this file's own
> rule. Either the claim can be restated against code, or the ticket's reasoning
> belongs in a `decisions/` document. Recorded here rather than silently
> tolerated, because the rule is the reason this register is worth reading. Where a reason
for the deferral was recorded at the time, it is quoted verbatim rather than
paraphrased, so nobody has to re-derive the argument before overturning it.

Sizes are engineering-days-of-one-person, not story points: **S** ≤ 1 day,
**M** 1–4 days, **L** ≥ 1 week or "needs a design first".

Verdicts are three, and only three:

| Verdict | Meaning |
| --- | --- |
| **blocks 1.0** | 1.0 would be a false claim with this outstanding. |
| **should precede public launch** | Shippable, but the first outside user meets it and it costs trust. |
| **fine to carry** | Recorded, understood, cheap to leave. Revisit on demand, not on schedule. |

**45 gaps · 4 blocks-1.0 · 10 should-precede-launch · 31 fine-to-carry.**
*(Recounted 2026-08-13 by parsing this file. The old line said 38/24 and
disagreed with its own section headers, which summed to 45.)*
(RC-01 closed 2026-08-10 by ticket 04, RC-02 by ticket 05, both of
`.scratch/docs-and-gaps/`; PK-06, UX-01 and UX-02 closed 2026-08-10 — the
last two together, since they were one ticket: the terminal-frame contract.
UX-03 closed 2026-08-11 by ticket 08, PF-01 by ticket 10, and UX-06, PK-09 and
PF-02 by ticket 12 — the last three together, since they were one ticket: the
dead-surface sweep.)

| Theme | Total | blocks 1.0 | precede launch | carry |
| --- | --- | --- | --- | --- |
| A. Runtime correctness & capability | 14 | 0 | 3 | 11 |
| B. Packaging & release | 10 | 4 | 2 | 4 |
| C. UX | 8 | 0 | 2 | 6 |
| D. Docs | 4 | 0 | 2 | 2 |
| E. Security & ops | 4 | 0 | 1 | 3 |
| F. Performance | 5 | 0 | 0 | 5 |

Six items on the intake list for this register were checked and found
**already done** — they are listed at the bottom under "Verified closed", not
silently dropped. Entries closed since are appended to that list when they were
ever externally visible.

---

## A. Runtime correctness & capability (14)

### Blocks 1.0

*(None. RC-02 was the last one in this theme — closed 2026-08-10, see
"Verified closed".)*

### Should precede public launch

**RC-04 — A tool that overrides `run` instead of `_execute` is discovered as
nothing, silently.** `BaseTool._execute` is `@abstractmethod`
(`backend/openstategraph/abc/tool.py:83-85`), and discovery skips abstract
classes with no warning
(`backend/openstategraph/api/capability_discovery.py`, the
`inspect.isabstract(obj)` guard in `discover_tool_instances`). A third party
who overrides the *documented-looking* `run(**kwargs)` from `ITool`
(`abc/tool.py:57`) gets a workflow that loads, validates and runs — with their
tool absent. Not previously recorded anywhere; found in this sweep. **Size S**
(one `logger.warning` naming the class and the fix). **Risk:** the worst
failure shape we have — a plugin that installs cleanly and does nothing.
**Verdict: should precede public launch** — entry-point plugins (ticket 05)
made third-party `BaseTool` subclasses a supported path, so this footgun is now
aimed outward.

**RC-05 — Hand-written node types never reach the palette.** Discovery
describes them; nothing consumes the description. Evidence:
`backend/openstategraph/api/capability_discovery.py:15-16` — *"frontend
`NodeTypeRegistry.upsert()` consumer, neither of which exists yet. That half is
left open, not fabricated as done."* The frontend works around it by polling
(`src/app/capabilityRefresh.test.ts:30`, *"Ticket 18's hot-reload gap"*), and
`src/nodes/workflowScoped.ts:23-33` states the same boundary: *"What this is
not: the full generic mechanism ticket 18 designs… That is real,
separately-scoped work… and remains an honest gap."* **Size L** (a manifest, an
SSE push, and dynamic field rendering from an arbitrary Pydantic schema).
**Risk:** authoring a tool is a two-place job — **and, since PK-06 closed, no
longer one with no error message when you do half of it**: the capabilities
response names every tool node type the runtime can bind that has no editor
card, and the palette shows it. What remains open here is the rest of RC-05's
scope: a *hand-written node type* (not a tool) reaching the palette, and the
SSE push that would make either appear without asking. **Verdict: should
precede public launch**, at reduced risk.

**RC-06 — No MCP or OpenAPI knowledge adapters.** *Design settled
2026-08-11* by ticket 11 of `.scratch/docs-and-gaps/`; still open as
implementation, and re-sized. `docs/decisions/knowledge-architecture.md`,
"Which of those two, for MCP and OpenAPI", records the answer to the ticket's
actual question: **neither belongs under `IEngineAdapter`**, whose three
abstract members (`list_tables`, `table_schema`, `sample`) are a SQL contract
rather than a generic source one. The rung that is already generic is
`BaseKnowledgeBuilder`; each source family gets its own sibling adapter ladder
in its own vocabulary and is composed by its own builder concrete, meeting the
others only at `BUILDERS`. Re-sized against the gaps rather than around them:
**MCP was blocked** on there being no MCP client at all
(`docs/decisions/agent-plugins.md` §7, whose own re-open trigger was "we gain
an MCP client"). *Amended 2026-08-16: that trigger has been pulled.* `tool.mcp`
is a registered node type over a live `MultiServerMCPClient`
(`prebuilt_mcp.py`), so the blocker is gone and the remaining reason not to
rush is the original one — a knowledge adapter must not be the product's first
MCP integration by the back door; **OpenAPI is unblocked but is not an adapter
drop-in** — recognition-from-wiring needs a spec path *declared on the canvas*
and no node type declares one, so it starts as a new TypeScript node type.
Original entry: The trainer recognises SQL
sources (sqlite/postgres/mssql —
`backend/openstategraph/knowledge_engines.py:112,247,291`) and has the agentic
explorer and codebase builder
(`knowledge_explorer.py:265,441`), but `BUILDERS` is
`[SqlKnowledgeBuilder(), RootKnowledgeBuilder()]`
(`knowledge_builders.py:476`). Evidence for the intent:
`docs/decisions/knowledge-architecture.md` "Build order" — *"(SQLite exists;
Postgres/MSSQL next; MCP and OpenAPI adapters after)"*; commit `76535b9` —
*"BUILDERS list is the registration point; Codebase and Api builders documented
as next concretes."* **Size M each** (the adapter shape is settled; MCP
`list_tools` is self-describing by protocol). **Risk:** the "generic over
sources" claim in the architecture doc is currently true of one source family.
**Verdict: should precede public launch** — the claim is in a public doc.

### Fine to carry

**RC-17 — The catalogue-events fan-out has no cross-process transport.**
`api/catalogue_events.py` is an in-process deque, so a publish on one process
never reaches a subscriber on another. Today this costs nothing, because
`deployment.py` refuses the only configuration in which it would matter. It is
the one thing standing between here and supported multi-worker: Postgres
`LISTEN`/`NOTIFY` or Redis behind `CatalogueBroadcaster`'s existing
`publish`/`subscribe` pair, with the endpoint and both clients unchanged.
**Size M.** **Risk:** none today — the refusal is what makes that true, so this
entry and the refusal have to be closed or removed together. **Verdict: fine to
carry** until someone actually needs a second worker.

**RC-07 — The `node_runtime.py` split is planned and not executed.** 1639
lines (`backend/openstategraph/compile/node_runtime.py`), no `compile/nodes/`
package. The full four-part plan — `compile/state.py`, `compile/context.py`,
`compile/nodes/{io,agents,deciders,fanout,mounting,functions}.py`, and a
re-exporting `node_runtime.py` — is written out in
`docs/decisions/architecture-audit-2026-08.md` §"node_runtime split — PLANNED,
not executed". Deferred because *"the builders are closures over `NodeRuntime`
state… so the mechanical move rewrites every `self.` reference in ~900 lines
during the same session that changed turn-reset and feedback semantics. Two
behavioural fixes and a structural rewrite in one change set is exactly the
churn the tests-before-refactor rule exists to prevent."* The same doc judges
it *"borderline rather than violating"* against the god-class rule. **Size M**
(mechanical, zero behavioural diff, seams already named). **Risk:** navigation
cost, not correctness. **Verdict: fine to carry** — but it is the single
best-specified ticket in this register, and it gets cheaper the sooner it runs.

**RC-08 — No checkpoint-preserving stop (`RunControl.request_drain`).** Stop
means "nothing further is scheduled"; work already dispatched finishes and is
discarded. Evidence: `backend/openstategraph/api/streaming.py:456-470` —
*"There is no cancellation seam inside a superstep at this version:
`RunControl.request_drain()` (langgraph 1.2) stops at exactly the same boundary
— 'after the current superstep completes' — and buys a resumable checkpoint
rather than a faster stop."* Measured residuals: ~15s early, ~75s mid-fan-out
(`.scratch/launch-readiness/tickets/10-stop-button.md`). **Size S** once the
dependency moves to ≥1.2. **Risk:** none — the current behaviour is honest and
the tooltip says so. **Verdict: fine to carry.**

**RC-09 — Repeated approval rejection replans forever.** Evidence:
`.scratch/launch-readiness/tickets/11-persona-sweep-both-flows.md`, "NOT
changed, deliberately" — *"the grader's `attempts` cap has already force-passed
by then so each rejection returns straight to the human. Not fixed: a human
rejecting each round is in control and can stop, and inventing a budget for it
would be a guess."* **Size S.** **Verdict: fine to carry** — the reason is
still correct.

**RC-10 — No parallel-interrupt resume map.** LangGraph can resume several
simultaneous interrupts by `{interrupt_id: value}`; we run one `human.approval`
at a time. Evidence: `docs/decisions/architecture-audit-2026-08.md` "Deferred"
— *"Defer until the canvas can express that shape; the API layer is where it
lands."* **Size M.** **Verdict: fine to carry** — the shape is undrawable, so
the plumbing would have no caller.

**RC-11 — `cache_policy` and per-`Send` `timeout` are unused.** Evidence: same
"Deferred" section — caching model-driven nodes *"is wrong"* and the
deterministic `function.*` nodes are cheap; a per-subtask timeout has *"no card
[that] expresses"* it, so *"adding the plumbing without a UI field is
speculative."* **Size S.** **Verdict: fine to carry.**

**RC-12 — Durability modes (`sync`/`async`/`exit`) not exposed.** Evidence:
same section — *"A server-run concern… not a compile concern; current default
(`async`) is acceptable for editor runs. Note for the eventual deploy story."*
**Size S.** **Verdict: fine to carry.**

**RC-13 — No aggregation policy for the voting flavour of parallelization.**
`orchestrate.format-report` concatenates; majority / best-of / mean-score is
unbuilt. Evidence:
`.scratch/launch-readiness/tickets/07-research-workflows-agents-doc.md` —
*"Recommendation: **skip for launch.** It is a `format-report` field (`mode:
concatenate | vote | best-of`) whenever someone asks, not a new node, and no
launch example needs it."* **Size S.** **Verdict: fine to carry.**

**RC-14 — `chinook_tool_registry()` reads a path that exists only in this
checkout.** `backend/openstategraph/api/registries.py:61` reaches into
`workflows/chinook-assistant/tools`, wrapped in `try/except` with a debug log.
Evidence: `docs/decisions/framework-packaging.md` §2.5 — *"the default tool
registry outside the repo is therefore quietly different from the one inside
it. Any adopter whose document binds a `chinook.*` node type inherits a warning
instead of a tool."* **Size S** (the honest fix is to stop shipping a
repo-relative default). **Risk:** small and warned. **Verdict: fine to carry.**

**RC-15 — Chinook's `graph.py` sets `retry_policy` per node instead of once.**
Evidence: `workflows/chinook-assistant/graph.py:300` — *"Collapse this into one
call when the dependency moves to >= 1.2."* (`set_node_defaults` is absent in
langgraph 1.0.3.) **Size S.** **Verdict: fine to carry** — pairs with RC-08 as
"things that unlock on the 1.2 bump".

**RC-16 — Three connection-rule classes named but unbuilt.** Evidence:
`src/core/validation/ConnectionValidator.ts:54-55` — *"and later: tool-only
buses, scoped links, licence-gated nodes"*. **Size M.** **Risk:** none; these
are speculative extension points, not missing behaviour. **Verdict: fine to
carry** — and do not build them until something asks.

---

## B. Packaging & release (10)

### Blocks 1.0

**PK-01 — The wheel has never been uploaded, and the name is unverified.**
`backend/dist/openstategraph-0.3.0-py3-none-any.whl` exists and passes `twine
check`; nothing has been published. Evidence:
`.scratch/framework-packaging/tickets/06-publish-pipeline.md` — *"**No upload
was attempted: there are no credentials in this environment** (no
`TWINE_*`/`PYPI_*` variables, no `~/.pypirc`), and inventing one would be the
opposite of proving anything. The upload is the owner's step"*; and
*"Unverified, and it stays that way until someone with an account runs it:
whether the name `openstategraph` is free on PyPI."* **Size S** (owner action,
one command — plus a name collision contingency that has never been checked).
**Risk:** every `pip install openstategraph` line in the docs and on the site
is currently a promise. **Verdict: blocks 1.0.**

**PK-02 — There is no git remote, so `project.urls` is `PLACEHOLDER`.**
Evidence: `backend/pyproject.toml:44-62` — *"PROVISIONAL, and deliberately
un-mistakable. This checkout has no configured git remote, so the canonical
host is not a fact yet"*; verified live (`git remote -v` → empty). The same
literal appears **31 times** in `site/index.html` (recounted 2026-08-13; this said ~12) plus 6 in `backend/pyproject.toml` (e.g. `:802`, `:873`, `:1049`,
`:1331`). **Size S** (owner action; `grep -rn PLACEHOLDER` is the whole
checklist). **Risk:** a published PyPI page with four dead links. **Verdict:
blocks 1.0.**

**PK-03 — `EXTENSION_NAMESPACE = "org.openstategraph"` is a placeholder.**
Evidence: `backend/openstategraph/plugin_interop.py:37-39` — *"Placeholder-grade:
the spec SHOULDs a domain we control, so pin this before publishing anything
public."* Restated in `docs/decisions/agent-plugins.md` §4 and §7, and in
`.scratch/framework-packaging/tickets/05-extension-entry-points.md` (*"pinning
it needs a domain the project actually controls"*). **Size S**, gated on owning
a domain. **Risk:** exported plugins carry a reverse-domain directory we do not
own — a spec violation baked into artifacts already in other people's repos.
**Verdict: blocks 1.0.**

**PK-04 — `RunResult` is a `str` subclass, and its 1.0 successor is a
different type.** Evidence:
`.scratch/framework-packaging/tickets/08-adoption-interface.md` — *"The 1.0
successor (a plain frozen dataclass) is recorded in the module docstring and
`docs/stability.md` as a plan, not a regret."* It is Tier 1
(`docs/stability.md`), so the swap is a breaking change to the most-imported
name we have. **Size M.** **Risk:** doing it *after* 1.0 costs a major; doing
it before costs nothing. **Verdict: blocks 1.0** — this is precisely the kind
of decision 1.0 is supposed to close.

### Should precede public launch

**PK-05 — Trusted Publishing (OIDC) is not configured; release runs on
long-lived tokens.** Evidence:
`.scratch/framework-packaging/tickets/06-publish-pipeline.md` — *"**Required
repository secrets: `PYPI_API_TOKEN` and `TEST_PYPI_API_TOKEN`.** Trusted
Publishing (OIDC) remains the preferred successor per §3.6… it cannot be
configured before the project exists on PyPI under a real repository."*
Blocked by PK-01 and PK-02. **Size S.** **Risk:** a long-lived publish token in
repository secrets. **Verdict: should precede public launch.**

**PK-06 — A published atom is bindable but has no editor card.**
**Closed 2026-08-10** — see the closed list at the foot of this file.

### Fine to carry

**PK-07 — There is no upgrade command for fork/checkout adopters.** Evidence:
commit `04b7b0d` — *"fork/checkout (the repo IS the workspace; upgrade friction
named honestly, incl. that there is no upgrade command)"*. **Size M.**
**Verdict: fine to carry** — named honestly in `docs/adoption.md`, and the
wheel is the answer for anyone who wants upgrades.

**PK-08 — `document.compiledBy` (artifact telemetry) deferred.** Evidence:
`.scratch/framework-packaging/tickets/04-schema-versioning.md` — *"**Deferred,
deliberately.** §3.4's `document.compiledBy` stamp is telemetry rather than
policy, is not in this ticket's scope, and touches the store and the MCP write
path."* Also the framework-packaging map's "Not yet specified" item 3. **Size
S.** **Verdict: fine to carry.**

**PK-09 — ~~`openstategraph/middleware/` is an empty leftover directory.~~
Closed 2026-08-11** by ticket 12 of `.scratch/docs-and-gaps/` — deleted.
Original entry: verified: contains only `__pycache__`, tracked by nothing, correctly absent
from the wheel. Evidence:
`.scratch/framework-packaging/tickets/06-publish-pipeline.md` — *"it is an
empty leftover directory holding only `__pycache__`, tracked by nothing."*
**Size S** (delete it). **Verdict: fine to carry.**

**PK-10 — `--strict` (exit code 4) dropped from the CLI.** Evidence:
`.scratch/framework-packaging/tickets/08-adoption-interface.md` — *"a CI gate
needs 'did it work' to be one code, and warnings are already printed to stderr
on every run. **If `--strict` is wanted later it is additive.**"* **Size S.**
**Verdict: fine to carry** — and the exit-code contract in `docs/stability.md`
is what makes it additive rather than breaking.

---

## C. UX (8)

### Should precede public launch

**UX-03 — ~~Tabular / CodeWorkshop node stubs are orphaned.~~ Closed
2026-08-11** by ticket 08 of `.scratch/docs-and-gaps/`: **deleted**, both
families, with their tests and their `port_specs.json` entries. The deciding
evidence was the backend, not the palette — a `tool.*` node resolves through
`NodeRuntime._bound_tool`, which looks the type up in the shared registry and,
finding nothing, appends it to `unresolved_tools` and binds no capability at
all. So every one of these eight palette entries produced a node that an agent
could be wired to and would silently gain nothing from. Neither family had a
backend tool, a workflow, or (for Tabular) even the DuckDB dependency its own
docstring named. Original entry:
`src/nodes/tools/TabularDataNode.ts` and `CodeWorkshopNode.ts` (plus their
tests) define palette entries with no backend tools and no workflow that uses
them — `workflows/` holds only `chinook-assistant`, `concierge` and
`workflow-architect`. Evidence: commit `0d1b2d7` — *"Follow-up recorded:
Tabular/CodeWorkshop TS stubs are orphaned once the scope-badge session lands
its protected files."* That scope-badge work is currently uncommitted in the
working tree (`src/nodes/workflowScoped.ts`, `NodeCard.tsx`). **Size S**
(delete, or wire a backend). **Risk:** palette entries that produce a node
which cannot run. **Verdict: should precede public launch.**

**UX-04 — Browser `localStorage` persistence is a stopgap that can lose
work.** Evidence: `src/app/workflowStore.ts:7-8` — *"A stopgap until the Python
backend owns persistence (tickets 07/10/16), but a stopgap that can lose a
user's work, so it is built to be tested rather than trusted."* **Size M.**
**Verdict: should precede public launch.**

**Status: the three ways it lost work are closed; durability is not, and the
design for that is below.** "A stopgap that can lose work" was a label, not a
diagnosis, so the first job was to name the actual failures. Reading
`workflowStore.ts` against its only consumer (`useWorkflowSession` in
`WorkbenchContext.tsx`) found three, each with a different fix:

1. **The silent write.** `saveWorkflow` returned a `SaveOutcome` and the
   autosave call site **discarded it** — a quota failure (or Safari private
   mode, where *every* `setItem` throws) left the user editing a document
   nothing was recording, with no signal at all. A store that reports to a
   caller that ignores it fails silently. Now: a typed `kind`
   (`quota | too-large | conflict | error`), a full sentence per kind, and the
   hook raises a toast — once per distinct failure, cleared by the next
   success, because autosave fires per edit. An oversized document is rejected
   *before* the write, so the message names the document rather than blaming
   the disk.
2. **The corrupt payload.** The reader returned `null`, indistinguishable from
   "nothing saved" — the user silently got the seeded demo instead of their
   graph. Now `readWorkflow` returns `ok | missing | corrupt`, the corrupt case
   is reported to the user, and the unreadable bytes are **quarantined** under
   a separate `openstategraph-corrupt-workflow-` prefix rather than deleted
   (they are that user's only copy) or left in place (they would fail every
   subsequent load identically).
3. **The second tab.** Two tabs adopted one id and the last write won —
   recorded in the old code as an accepted trade ("a smaller problem than
   unbounded duplicate entries"). It is not one: the losing tab shows the user
   work it is simultaneously overwriting. Closed twice over, because one
   mechanism is not enough. A **claim** (`openstategraph-claim-<id>`, refreshed
   on a 10s heartbeat, believed for 30s) stops a second live tab adopting the
   id at all — it mints a blank one and says so, rather than restoring a copy,
   which would be the duplication bug in new clothing. A **compare-and-set** on
   every write catches what the claim cannot (two tabs opening in the same
   instant, a slept laptop). The CAS rule is deliberately *"newer than the
   version this tab last saw"*, not *"written by someone else"* — the naive
   identity check locks a workflow forever the first time its author closes the
   tab, since no new tab's id ever matches the stored one.

33 tests in `src/app/workflowStore.test.ts` cover these, including a throwing
store (quota *and* wholly-unavailable), a corrupt payload, and two guards
writing against one store.

> **Superseded in part, 2026-08-14.** The paragraph below argues against
> autosaving to `workflows/<slug>/workflow.json`. The owner asked for exactly
> that, three times, as the thing they expected as a developer — and the
> counter-argument, "an experiment becomes indistinguishable from a commit",
> answers a question `git` already answers better than a persistence design
> can: an unwanted autosave is `git checkout`, and an autosave you *did* want
> but never made is gone. So the editor now writes the package on every edit
> (`src/app/diskAutosave.ts`, the-editor-makes-a-real-package ticket 02), and
> the browser draft is demoted to crash recovery rather than the record.
>
> What survives from the paragraph is its premise, and it is worth keeping in
> view: a workflow with **no slug yet** has nowhere on disk to be written, so
> it still lives in `localStorage` alone until one explicit Save mints its
> folder. That window — a brand-new canvas, before its first save — is the
> only place the durability gap below still applies. The separate draft store
> is no longer the plan for the rest.

**What is still open, and the design for it.** None of the above makes the data
*durable*: clearing site data, a different browser, or a different machine
still loses whatever was never saved to the backend. The editor now says this
out loud in the Workflows panel rather than implying a durability it does not
have. The remaining work is server-side session persistence, and it is
deliberately **not** "autosave to `workflows/<slug>/workflow.json`" — that
directory is the *published* artifact, tracked in git and read by the runtime,
and streaming every keystroke into it would make an experiment indistinguishable
from a commit. The shape:

- **A separate draft store.** `PUT/GET /api/drafts/{workflowId}` writing
  `.openstategraph/drafts/<id>.json` outside `workflows/`, gitignored. A draft
  is promoted to a workflow only by the existing explicit Save.
- **The browser keeps its copy.** `localStorage` becomes the offline tier, not
  the record: write locally first (fast, works offline), then push. The
  reconciliation on load is `savedAt` comparison with an explicit
  "this browser has a newer/older copy — keep which?" prompt. Silent
  last-write-wins across *devices* is the same defect as across tabs, one
  network away.
- **The claim generalises to a lease.** The same `writerId`/`lastSeenAt` pair
  becomes an ETag on the draft endpoint, so a 412 is the server-side spelling
  of the `conflict` outcome already implemented. This is why the CAS was built
  as compare-a-version rather than compare-an-owner.
- **Identity needs an owner first.** *(Amended 2026-08-13: both halves arrived
  and this bullet contradicted SEC-01 in this same file, which records the
  shared token as shipped.)* **Admission** exists — `api/auth.py`, a shared
  bearer token, every holder the same principal. **Identity** exists too —
  `openstategraph/principal.py`, resolved server-side, and it is what keys a
  per-person memory namespace. What is still absent is per-user
  *authorization*: nothing decides that person A may not open person B's draft.
  So a draft store today is per-installation, not per-user. That is
  acceptable for a single-developer local editor and unacceptable for anything
  hosted — so the draft endpoint must not ship as a hosted feature ahead of
  auth. **Size M** for the draft store, **L** with auth. **Verdict on the
  remainder: fine to carry** — the failure modes that silently destroyed work
  are gone, and what is left is a documented limit the UI now states.

### Fine to carry

**UX-05 — ~~No per-field inherited-vs-overridden chips on a mount card.~~ CLOSED 2026-08-13.**
The drill-in landed: `src/core/model/MountContext.ts` provides
`isOverridden(childNodeId, key)` and `inheritedValue(...)` — *"what a revert puts
back, and what the inspector shows beside an overridden one"* — and
`FieldRenderer.tsx` marks an overridden field and offers that revert.
`mount-overrides.md` deferred the same work and has been corrected too.
*Original entry below.* Today
the card appends `· n overridden` and the inspector edits raw JSON. Evidence:
`docs/decisions/mount-overrides.md` "UI contract" — *"Richer per-field
'inherited/overridden' chips ride on the (charted, separate) inspector drill-in
work"*; commit `1adbfa1` — *"Inspector field + inherited-vs-overridden display
follow with the composition-peek frontend work."* **Size M.** **Risk:** you can
see *that* something is overridden, not *what*. **Verdict: fine to carry.**

**UX-06 — ~~Three design-barrel exports have no consumer.~~ Closed
2026-08-11** by ticket 12 of `.scratch/docs-and-gaps/`. `Spinner` and
`Progress` are gone — component, styles and barrel line; `formatShortcut` is
now module-local to `Indicators.tsx`, where `Kbd` and `shortcutText` are its
only two callers, so the promise is kept inside the module instead of
advertised out of it. Original entry: verified by grep
across `src/` excluding `src/design/primitives/`: `Progress` (0), `Spinner`
(0), `formatShortcut` (0). Evidence for the handoff: commit `5238549` —
*"Handoffs recorded in the report for compile/abc/design territory
(precomputed plan.incoming, build() accepting a plan, design barrel dead
exports)."* **Size S.** **Risk:** none — a barrel export is a promise nobody is
holding. **Verdict: fine to carry.**

**UX-07 — No editor affordance for plugin export.** The endpoint exists
(`GET /api/workflows/{slug}/plugin-export`); no button does. Evidence:
`docs/decisions/agent-plugins.md` §6 — *"Deliberately **not** built: an editor
affordance. The Export dialog already exists and this is a report-level
capability; a button is cheap to add later against the endpoint and expensive
to design now."* **Size S.** **Verdict: fine to carry.**

**UX-08 — `Dialog` is not a design primitive.** Evidence:
`docs/decisions/shadcn-consistency.md` "Missing primitives" — *"`Dialog` is
generic chrome living in `src/view/overlays/`, which is where `design/` says it
should not be. Moving it is an import-churn refactor with no consistency payoff
in this pass… Recorded so it is not forgotten."* **Size S.** **Verdict: fine to
carry.**

**UX-09 — Label recolour on error, deferred.** Evidence: same doc, audit row
14 — *"it is a genuine improvement but it introduces the danger hue somewhere
it does not currently appear, which is out of scope for this pass. The
`data-error` hook is now present on the label element, so it is a one-line
change whenever the owner wants it."* **Size S.** **Verdict: fine to carry.**

**UX-10 — A drill-in breadcrumb affordance for mounted workflows.** Evidence:
`src/nodes/compose/TeamNode.ts:38-39` — *"A dedicated breadcrumb affordance is
recorded on ticket 56 as follow-up UX, not blocking the mechanism"*; also
`src/view/nodes/CompositionBody.tsx:39-40` and
`src/view/workflow/loadWorkflowIntoEditor.ts:23`. **Size M.** **Verdict: fine
to carry.**

---

## D. Docs (4)

### Should precede public launch

**DC-01 — ~~The site still says draft→publish "is landing now".~~ CLOSED 2026-08-13.**
`grep -c "landing now" site/index.html` → **0**. The callout is gone; the entry
was not updated when it went. *Original entry below.* It landed:
ticket 04 of the launch-readiness map is closed, and its own resolution says
*"Ticket 05's landing-page callout can now be deleted."* The callout is still
there: `site/index.html:921-925` — *"**Draft → publish is landing now.**"*
**Size S.** **Risk:** the truth rule this project runs on ("a claim must be
verifiable by running something") broken on the landing page. **Verdict: should
precede public launch.** Owned by ticket 01 of the current map, recorded here
so it cannot fall between the two.

**DC-02 — "Upload pending" labelling is not uniform, and must be swept when
PK-01 lands.** Commit `b724496` promised *"every pip line labelled
upload-pending beside the checkout that yields the identical artifact"*;
`docs/adoption.md:16` carries it (*"the PyPI upload is pending"*) but
`docs/what-is-this.md:109` presents `pip install openstategraph` in a table
with no such label. **Size S.** **Verdict: should precede public launch** —
and it inverts the day PK-01 lands, so it needs one owner, not two passes.

### Fine to carry

**DC-03 — Two closed questions still sit in the launch-readiness map's "Not
yet specified".** The Astro doc-site question was answered by ticket 06
(*"no Astro site needed — the 'doc SITE structure' open question in the map can
stay closed"*) and the concierge routing-knowledge gate by ticket 04's decision
line, but the map section was never edited. **Size S.** **Risk:** a closed map
that reads as if it has open questions. **Verdict: fine to carry** — the map is
closed; note it and move on.

**DC-04 — No generated API reference.** Evidence: the current map's own "Not
yet specified" — *"depends on how big the Tier-1 surface gets after 1.0"*.
**Size M.** **Verdict: fine to carry.**

---

## E. Security & ops (4)

### Blocks 1.0

*(none — the security gaps below are all documented boundaries with a stated
mitigation, which is what keeps them off this line.)*

### Should precede public launch

**SEC-02 — No rate limiting, quotas, or audit log.** Evidence:
`docs/decisions/mcp-layer.md` §5 — *"`run_workflow` in particular spends the
deployer's model budget on any connected client's request."* Unchanged by
ticket 06 and now the *largest* remaining security gap, because the token
answers "is this stranger allowed in" and says nothing about how much they may
spend once they are. `docs/deploying.md` names it under "Not solved here" and
points at the proxy as today's place to put a limit. **Size M.** **Verdict:
should precede public launch** — a token holder can still exhaust a budget.

### Fine to carry

**SEC-01 — ~~The MCP layer authenticates nobody.~~ Narrowed
(scale-and-adopt ticket 06): a first-party token layer ships, off by default.**
The old verdict — *"should precede public launch if the launch includes a
hosted MCP endpoint; otherwise the proxy story holds"* — rested on a proxy that
was not in the repository, and on the assumption that the exposed deployment is
a hosted one. Both were wrong in the same direction: the commonest deployment
is an MCP server on a laptop or a team VM with no proxy and no plan for one,
and "configure a reverse proxy" is advice rather than a product.

So both halves shipped. `deploy/Caddyfile` and `deploy/nginx.conf` are
committed and checked against the app's real routes on every CI run
(`backend/tests/test_reverse_proxy.py`) — including the three SSE endpoints,
whose buffering and timeout requirements are the part everyone gets wrong.
And `OPENSTATEGRAPH_API_TOKEN` (`openstategraph/api/auth.py`) puts a shared
bearer token in front of the HTTP API *and* the MCP `streamable-http`
transport, with a session cookie so the editor and `/chat` keep working. stdio
is deliberately not gated: the client is the process that spawned it.

The decision **not** faked here is still not faked: this is a shared secret,
not identity, and `docs/deploying.md` says so in the same paragraph that offers
it. What remains open is per-user identity and authorization, which is a
different entry (see "Identity needs an owner first", §D) and genuinely blocked
on there being an owner concept at all. **Verdict: no longer blocks anything.**

**SEC-03 — Capability discovery imports and executes workflow Python with no
sandboxing.** Evidence:
`backend/openstategraph/api/capability_discovery.py:22` — *"Recorded here as
the ticket asked, not solved — there is no sandboxing."* The boundary is stated
in `api/main.py:46` as the same "local dev tool, not hosted" line.
**Size L** (real sandboxing is a project, not a task). **Risk:** already
accepted — opening a workflow package is opening a Python repository, which is
the same trust model as `pytest`. **Verdict: fine to carry**, provided the
hosted story never quietly starts calling it.

**SEC-04 — No spawn-confirmation gate for runtime children.** Evidence:
`backend/openstategraph/api/streaming.py:408` — `# TODO(future, deliberately
not built): a spawn-confirmation` gate would hook here; commit `0d75068` —
*"No HITL gate by default; the interrupt hook point is marked in
streaming.py."* **Size M.** **Verdict: fine to carry** — the hook point is
marked, which is the whole cost of keeping the option.

---

## F. Performance (5)

### Fine to carry

**PF-01 — ~~`capability_discovery` re-imports every workflow module on every
call, with no cache and no invalidation policy.~~ Closed 2026-08-11** by
ticket 10 of `.scratch/docs-and-gaps/`, and it turned out not to be a
performance gap at all. The policy is now written down in `_import_module`'s
docstring — **no cache, re-execute from the source bytes** — with the measured
cost that justifies it (~1.5 ms/call for `chinook-assistant`, the largest
shipped package). Asking "what invalidates?" found a live bug: the caching had
already happened and nobody had chosen its policy. `spec.loader.exec_module`
is a `SourceFileLoader`, so it wrote a `__pycache__/*.pyc` **into the
developer's own workflow package** and validated it against `(source mtime in
whole seconds, source size)` — so an edit that keeps the byte length and lands
in the same second as the previous one was invisible, serving stale code to
the *runtime*, not merely to the capabilities panel. Fixed by compiling the
source here rather than handing it to the loader. Three tests pin the policy
(`TestTheInvalidationPolicy`), and the recorded rule for a future cache is
that its key must be the file's **content hash** — never mtime, never process
lifetime. Original entry: `_import_module` runs
`spec.loader.exec_module` per call
(`backend/openstategraph/api/capability_discovery.py:66-81`), and every
`/api/workflows/{slug}/capabilities` request and every runtime assembly pays
it. Caching is *not* obviously right: the function's own docstring explains why
reload is refused — *"a previously-discovered class would silently stop
`isinstance`-matching a freshly reloaded base (the exact hazard the ticket
calls out; the fix there is a process restart during development, not
reload)"*. So the gap is **an invalidation decision, not a missing cache**:
cache by (path, mtime)? cache for the process and require a restart? **Size M**
including the decision. **Risk:** repeated arbitrary-code execution per
request, and latency proportional to tool count. **Verdict: fine to carry** —
but it needs the decision written down before someone "optimises" it into the
`isinstance` hazard.

**PF-02 — ~~`save_topic` reads back the file it just wrote.~~ Closed** —
`save_topic` now names the bytes it wrote (`text`) and passes those to
`extract_hint`. Original entry:
`backend/openstategraph/api/knowledge_curation.py:146-147` writes
`f"{cleaned}{trailer}\n"` and then does `text = path.read_text()` to extract
the hint from content it already holds. **Size S.** **Risk:** none measurable
— one extra syscall on an explicit save. **Verdict: fine to carry.** Recorded
because it was on the intake list and it is real, not because it matters.

**PF-03 — `plan.incoming` is recomputed; `build()` does not accept a plan.**
Evidence: commit `5238549` — *"Handoffs recorded in the report for
compile/abc/design territory (precomputed plan.incoming, build() accepting a
plan, design barrel dead exports)."* **Size S.** **Verdict: fine to carry** —
and it should ride along with RC-07, which rewrites those call sites anyway.

**PF-04 — `run_workflow` over MCP is synchronous and unstreamed.** Evidence:
`docs/decisions/mcp-layer.md` §5. Half-unblocked by ticket 05: the durable
checkpointer it waited on exists and is now wired into the MCP run path, so a
`human.approval` document compiles and genuinely pauses instead of failing to
build, and `run_workflow` reports the pause with its durable `thread_id` rather
than a blank answer. What is left is a `resume_workflow` **tool** and token
streaming. **Size S** now, not M. **Verdict: fine to carry.**

---

## Verified closed — checked and not (or no longer) a gap


Items 1-6 were on the intake list and found already fixed. Anything after that
was a live entry in this register that has since been resolved and was
externally visible. Listed so nobody re-adds them from an old session report.

**RC-03 — ~~Single worker, because sqlite is single-process.~~ Closed
(scale-and-adopt ticket 06): multi-worker is now *refused*, not documented.**
The entry survived two narrowings and stayed open both times because the fix on
offer was always "ship Postgres", and Postgres was never the whole fix. Ticket
06 answered the actual question — support it or refuse it — with **refuse**,
and enforced it two ways: `openstategraph serve --workers N`, `WEB_CONCURRENCY`,
`UVICORN_WORKERS` and `GUNICORN_WORKERS` are read and refused before a socket is
bound, and an exclusive OS lock on `<state dir>/serve.lock`
(`openstategraph/deployment.py`) catches `uvicorn --workers 4` and `gunicorn -w
4`, which leave no trace in a child's environment for the first mechanism to
find. The risk this entry recorded — *"the first person to scale horizontally
gets uncoordinated concurrent writes, silently"* — is gone, because that person
now gets a refusal naming both causes.

The Postgres half shipped too, as `[postgres]` +
`OPENSTATEGRAPH_POSTGRES_URL` (`openstategraph/postgres.py`), on its own merits:
checkpoints and long-term memory in a database an operations team backs up. It
is explicitly **not** sold as the lift, and the refusal does not soften when it
is set — because the second cause, the in-process catalogue-events fan-out, has
no cross-process transport. *That* is the remaining work, and it is recorded
as **RC-17** in §A rather than left buried inside a closed entry.


1. **`settings.checkpointer: "sqlite"` silently degrading to in-memory.**
   Fixed: the `[sqlite]` extra is declared (`backend/pyproject.toml:77-79`) and
   `memory.py:196-200,247-249` now names the extra in a warning instead of
   degrading quietly. Framework-packaging §2.5 described the pre-fix state.
2. **The `/chat` client cannot tell a killed stream from a clean finish.**
   Fixed client-side: `chat.html:779-788` keys on the abort signal rather than
   the exception. The *server* still emits no terminating frame — that residue
   is UX-02, and it is a different gap from the one originally reported.
3. **Prompt chaining is undrawable (`PORT.result` terminal).** Fixed by the
   `accepts` widening in launch-readiness ticket 08 (commit `b4dfb63`).
4. **Postgres / MSSQL knowledge adapters "next".** Built:
   `knowledge_engines.py:247` and `:291`. Only MCP and OpenAPI remain (RC-06).
5. **`CodebaseKnowledgeBuilder` unbuilt.** Built:
   `knowledge_explorer.py:441`.
6. **`abc/__init__.py` empty, no `errors` module, no `__version__`, `__all__`
   on Tier 3 modules.** All closed by framework-packaging ticket 03; the
   surface is pinned by `backend/tests/public_api.txt`.
7. **RC-01 — `DEFAULT_PORT_SPECS` hand-mirrored the TypeScript node
   catalogue.** Closed 2026-08-10. `backend/openstategraph/compile/port_specs.json`
   is generated from `src/nodes/portSpecs.ts` by `npm run generate:ports`,
   loaded by `compile/node_catalogue.py`, and gated twice in CI
   (`src/nodes/portSpecs.test.ts` byte-compares; the `generated-port-specs` job
   regenerates and diffs). Externally visible because `docs/mcp.md` listed it
   as a limitation of `get_node_vocabulary`. The mirror had drifted: it held 10
   of the 38 node types the editor registers, and `workflow.subgraph` (plus
   `team.workflow`, which still existed then) were advertised over MCP with
   zero ports.
8. **RC-02 — the API's human-in-the-loop checkpointer was an `InMemorySaver`.**
   Closed 2026-08-10 by ticket 05. The module-level saver in `api/main.py` is
   gone; `WorkflowServices.checkpointer` is the one seam, shared by HTTP, MCP
   and `load_workflow`, and it defaults to
   `<workflows root>/.openstategraph/checkpoints.sqlite` with one startup line
   stating which it got (`memory.build_checkpointer`).
   `backend/tests/test_persisted_checkpointer.py` proves the case that matters
   — pause, destroy the services object, rebuild against the same path, resume
   the same thread — plus a negative control showing the in-memory opt-out
   discards the human's answer and re-asks. `langgraph-checkpoint-sqlite` moved
   onto the `[server]` extra, since the server's default now needs it; a
   missing install still degrades loudly. Externally visible: the limitation
   was stated in `README.md`, `docs/adoption.md`, `Dockerfile` and
   `scripts/dev.sh`, all now corrected.
9. **PK-06 — a published atom was bindable but had no editor card.** Closed
   2026-08-10. `GET /api/workflows/{slug}/capabilities` now also returns
   `plugin_tools` — built by `backend/openstategraph/api/plugin_capabilities.py`
   from `api/registries.process_tool_layer()`, i.e. **the same cached layer
   `build_tool_registry` binds**, so the palette cannot claim a tool the
   runtime lacks — and `src/app/pluginNodes.ts` registers one **app-scoped**
   node type per entry, keyed by the tool's own `node_type` (a plugin's tool is
   process-wide, so unlike a workflow-local capability there is no slug to
   qualify it with). A plugin declares its card's controls on the class
   (`openstategraph.abc.ToolField` / `BaseTool.node_fields`, read at runtime
   through `configure()`), so a third party who cannot add a TypeScript file
   still gets a configurable card. Collisions follow the documented order —
   built-in < plugin < workflow-local: the plugin's card replaces the bundled
   one, is labelled with the distribution, and the bundled definition and
   executor are restored when the plugin stops reporting.

   **The half-authored error is closed with it, and it was the worse half.** A
   Python tool with neither an editor card nor a plugin declaration is bindable
   and invisible, and produced no message anywhere. The response now carries a
   `warnings` list — plugin load failures, built-in replacements, workflow
   `tools/` findings the *listing* path used to discard, and one message naming
   every cardless node type — which the palette shows in a standing block
   rather than a toast. The live checkout produced four true positives on the
   first run (`tool.sql-get-schema`, `tool.sql-list-tables`, `tool.sql-query`,
   `tool.validate-workflow`), which is the point: the register said "genuinely
   unspecified", and what was actually missing was a way to *notice*. Renderable
   types are read from the generated `port_specs.json` (RC-01), so this is not
   a second hand-kept mirror of the TypeScript. Proven by
   `backend/tests/test_plugin_capabilities.py` (12) and
   `src/app/pluginNodes.test.ts` (12); documented in `docs/building-an-atom.md`
   Part 3, "What you must declare to get a card".

   **One residue, named rather than hidden:** the payload is fetched per
   workflow (`/api/workflows/{slug}/capabilities`), so a session that has never
   opened a saved workflow sees no plugin cards until it opens one or presses
   the palette's Refresh. App-scoped capabilities arriving through a
   workflow-scoped URL is the shape ticket 18 left behind; carrying it costs a
   click, and fixing it properly is RC-05's manifest-and-push work.
10. **UX-01 — an approval interrupt left the `/chat` diagram claiming
    "running".** Closed 2026-08-10. `interrupt` and `error` are now handled as
    what they are — endings — on both surfaces. `/chat` calls a new
    `pauseFlow()`: `#flow.running` comes off, the sweeping conic-gradient glow
    is removed, and the paused node is marked distinctly instead — a **static**
    amber ring plus a "Waiting for you" badge over it (`.flow-paused`,
    `.flow-wait`). The editor had the same confusion in a different spelling:
    `AskPanel` deliberately left the paused node on `status: 'running'`, so the
    canvas swept its run glow over the very node waiting for the developer.
    `NodeStatus` gained `'paused'` (and `StatusTone` with it), `CanvasStage`
    marks it `is-paused` — static ring and label from `canvas.css`, no sweep,
    no flowing edges — and the mark is retired when the pause is answered
    (`running`) or walked away from (`idle`). Nothing about `paused` animates,
    which is the whole rule: motion is what claimed the run was working.
11. **UX-02 — a killed stream ended with no terminating frame at all.** Closed
    2026-08-10. `_stream_run` is now a guard around the fold (`_run_frames`)
    and the contract is stated on it: **every stream that can still be written
    to ends with exactly one of `done`, `interrupt` or `error`, and nothing
    follows it.** The gap was wider than "a reload": `error` previously covered
    only exceptions raised *inside* the fold, so a failure in the post-loop
    `graph.get_state` (which decides pause-versus-finish) or in the `done`
    frame's own `draw_mermaid` unwound the generator with the client having
    seen updates and no ending. The one path that genuinely cannot carry a
    frame is the client leaving or the server dying — a generator may not yield
    after `GeneratorExit`, and a killed process runs nothing — so that case is
    **documented and delegated to the client**, which is now authoritative and
    says so in one place per surface: a body that ends with no terminal frame,
    or a `read()` that rejects mid-stream, is reported as "the backend most
    likely restarted or crashed". That second shape also fixed a real hang —
    `RuntimeClient` used to rethrow a mid-stream read failure past `AskPanel`'s
    unguarded `await`, leaving a turn stuck on "Running…" with nothing to end
    it. Pinned by `backend/tests/test_terminal_frame.py` (22) and four new
    cases in `src/core/runtime/RuntimeClient.test.ts`.

---

## Maintaining this file

One rule: **a deferral is not recorded until it is in here.** A session report,
a commit body, or a code comment may *also* say it — this file is what gets
read. When an entry closes, delete it and add a line to "Verified closed" only
if it was ever externally visible; otherwise just delete it.
