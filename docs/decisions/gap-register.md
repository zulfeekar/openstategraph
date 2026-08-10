# The gap register — every known deferral, in one place

**Status: in force from 2026-08-10.** Resolves wayfinder ticket 02 of
`.scratch/docs-and-gaps/`. This file replaces "it's recorded somewhere in a
session report" as the answer to *what is not done?*

## How to read this

Every entry names its evidence — a `file:line`, a doc section, or a commit —
because **a gap without evidence is not a gap, it is a worry**. Where a reason
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

**48 gaps · 6 blocks-1.0 · 14 should-precede-launch · 28 fine-to-carry.**

| Theme | Total | blocks 1.0 | precede launch | carry |
| --- | --- | --- | --- | --- |
| A. Runtime correctness & capability | 16 | 2 | 4 | 10 |
| B. Packaging & release | 10 | 4 | 2 | 4 |
| C. UX | 10 | 0 | 4 | 6 |
| D. Docs | 4 | 0 | 2 | 2 |
| E. Security & ops | 4 | 0 | 2 | 2 |
| F. Performance | 4 | 0 | 0 | 4 |

Six items on the intake list for this register were checked and found
**already done** — they are listed at the bottom under "Verified closed", not
silently dropped.

---

## A. Runtime correctness & capability (16)

### Blocks 1.0

**RC-01 — `DEFAULT_PORT_SPECS` hand-mirrors the TypeScript node catalogue.**
The Python compiler carries its own copy of every node type's port table.
Evidence: `backend/openstategraph/compile/workflow_compiler.py:169-174`, whose
own comment says *"**Known duplication, deliberately visible.** The
authoritative definitions live in the TypeScript node catalogue, and CLAUDE.md
forbids hand-mirroring a type across the boundary."* Also
`backend/tests/test_workflow_compiler.py:283` (*"temporary (ticket 02)"*).
Deferred because the table is **injectable** via `port_resolver`, so the
compiler works today and can consume generated output without a compiler
change. **Size L** (a generator plus a build step across two languages).
**Risk:** a node type added in TypeScript and not added here compiles as an
opaque node with control-flow edges — silently wrong wiring, not a crash. The
MCP layer raised the stakes: `mcp_server.py:126-147` serves this table as
`get_node_vocabulary`, so the drift is now *"invisible to every connected
client, not merely to the compiler"* (`docs/decisions/mcp-layer.md` §5).
**Verdict: blocks 1.0** — CLAUDE.md names hand-mirroring across the Pydantic/TS
boundary as a hard rule, and we are now publishing the mirror over a wire.

**RC-02 — The API server's human-in-the-loop checkpointer is `InMemorySaver`.**
An approval pause does not survive a restart and is invisible to a second
worker. Evidence: `backend/openstategraph/api/main.py:40-52` — *"needs a real
persisted checkpointer (Postgres), which is ticket 10's own already-named,
still-open gap"*; `backend/tests/test_human_approval.py:11` — *"`InMemorySaver`
is a real, honest limitation — fine for a single dev process, not for
multi-worker production — recorded rather than papered"*. **Size M** (the seam
exists; `memory.py` already swaps a sqlite saver per workflow). **Risk:** a
customer answering an approval after a deploy gets a 4xx and loses the thread.
**Verdict: blocks 1.0** — HITL is a shipped, documented feature; a feature that
loses state on restart is not 1.0-shaped.

### Should precede public launch

**RC-03 — Single worker, in-process state.** The memory `Store` and the HITL
saver are per-process, so `uvicorn --workers 2` gives two disagreeing servers.
Evidence: `docs/decisions/memory-architecture.md` "Durability" — *"Both share
the **single-worker constraint**: one uvicorn worker, one shared connection.
Multi-process hosting means PostgresStore/PostgresSaver dropped into the same
seams — nothing else changes"*; `docs/decisions/mcp-layer.md` §5; commit
`61a8551` (*"Single worker documented as a correctness constraint"*). **Size
M**, and the same work as RC-02. **Risk:** the first person to scale
horizontally gets nondeterministic memory. **Verdict: should precede public
launch** — documented honestly today, which is why it is not a 1.0 blocker.

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
**Risk:** authoring a tool is a two-place job with no error message when you do
half of it. **Verdict: should precede public launch.**

**RC-06 — No MCP or OpenAPI knowledge adapters.** The trainer recognises SQL
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
`workflows/chinook-nl-to-sql/tools`, wrapped in `try/except` with a debug log.
Evidence: `docs/decisions/framework-packaging.md` §2.5 — *"the default tool
registry outside the repo is therefore quietly different from the one inside
it. Any adopter whose document binds a `chinook.*` node type inherits a warning
instead of a tool."* **Size S** (the honest fix is to stop shipping a
repo-relative default). **Risk:** small and warned. **Verdict: fine to carry.**

**RC-15 — Chinook's `graph.py` sets `retry_policy` per node instead of once.**
Evidence: `workflows/chinook-nl-to-sql/graph.py:300` — *"Collapse this into one
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
literal appears ~12 times in `site/index.html` (e.g. `:802`, `:873`, `:1049`,
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

**PK-06 — A published atom is bindable but has no editor card.** The Python
half of the plugin story shipped; the TypeScript half did not. Evidence:
`.scratch/framework-packaging/tickets/05-extension-entry-points.md` — *"the
honest gap: a published atom is bindable and runs, but its editor *card* still
needs registering — the TypeScript counterpart remains fog, as the ticket
said."* Same root cause as RC-05. **Size L, and genuinely unspecified.**
**Risk:** "extend without forking" is half-true in a documented, advertised
seam. **Verdict: should precede public launch.** Deliberately **not** charted
as a ticket — see the map's "Not yet specified".

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

**PK-09 — `openstategraph/middleware/` is an empty leftover directory.**
Verified: contains only `__pycache__`, tracked by nothing, correctly absent
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

## C. UX (10)

### Should precede public launch

**UX-01 — An approval interrupt leaves the `/chat` diagram claiming
"running".** The server yields `interrupt` and returns without a `done` frame;
the client renders the approval card and never calls `finishFlow()`, so
`#flow.running` stays on — every node dimmed, a live ring over the paused node.
Verified in this sweep: `backend/openstategraph/api/static/chat.html:750-751`
(the `interrupt` branch calls only `renderInterrupt`) against `:560-566`
(`finishFlow` is what removes `.running`). Recorded at the time in
`.scratch/launch-readiness/tickets/11-persona-sweep-both-flows.md` — *"**The
`interrupt` frame ends the stream with no `done` and no answer**, so every
surface must special-case it to stop showing 'running' — `chat.html` renders
the approval card but never calls `finishFlow()`, leaving the diagram live
under it. Real, and it is inside the composer/stream JS another agent holds
this session. Left for a follow-up ticket rather than edited under someone
else's hands."* **Size S.** **Risk:** the customer-facing surface tells a
demonstrable lie about run state at the exact moment it is asking for a
decision. **Verdict: should precede public launch.**

**UX-02 — A reload-killed stream ends with no terminating frame at all.**
Same source: *"A reload-killed stream ends with no terminating frame at all —
a client cannot tell it from a clean finish. Now rare rather than routine, but
the honest fix is a frame, not a smaller window."* Note the client-side half
*is* handled — `chat.html:779-788` distinguishes a user stop by the abort
signal, with the note *"Found live — the button went back to Send and the turn
showed nothing at all."* The **server-side** gap (no terminating frame) is what
remains. **Size S.** **Verdict: should precede public launch** — it is the
protocol half of UX-01 and they are one ticket.

**UX-03 — Tabular / CodeWorkshop node stubs are orphaned.**
`src/nodes/tools/TabularDataNode.ts` and `CodeWorkshopNode.ts` (plus their
tests) define palette entries with no backend tools and no workflow that uses
them — `workflows/` holds only chinook×2, concierge, page-analytics and
workflow-architect. Evidence: commit `0d1b2d7` — *"Follow-up recorded:
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

### Fine to carry

**UX-05 — No per-field inherited-vs-overridden chips on a mount card.** Today
the card appends `· n overridden` and the inspector edits raw JSON. Evidence:
`docs/decisions/mount-overrides.md` "UI contract" — *"Richer per-field
'inherited/overridden' chips ride on the (charted, separate) inspector drill-in
work"*; commit `1adbfa1` — *"Inspector field + inherited-vs-overridden display
follow with the composition-peek frontend work."* **Size M.** **Risk:** you can
see *that* something is overridden, not *what*. **Verdict: fine to carry.**

**UX-06 — Three design-barrel exports have no consumer.** Verified by grep
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

**DC-01 — The site still says draft→publish "is landing now".** It landed:
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

**SEC-01 — The MCP layer authenticates nobody.** Evidence:
`docs/decisions/mcp-layer.md` §5 — *"**No authentication layer. This is the
known gap.** The MCP server authenticates nobody and authorizes nothing; every
connected client has the same capabilities. For v1 that is the **deployer's
reverse proxy**… Do not expose `streamable-http` to the public internet as-is.
The MCP specification has an authorization story; adopting it is the first
thing to do when this leaves a trusted network, and it is deliberately not
faked here with a shared secret."* Restated at
`backend/openstategraph/mcp_server.py:802-803`. **Size L.** **Risk:** bounded
by the trust boundary the design already enforces — no publish, no delete, no
credentials, writes jailed and validated — but unbounded on model spend.
**Verdict: should precede public launch** *if* the launch includes a hosted
MCP endpoint; otherwise the proxy story holds.

**SEC-02 — No rate limiting, quotas, or audit log on MCP.** Evidence: same
section — *"`run_workflow` in particular spends the deployer's model budget on
any connected client's request."* **Size M.** **Verdict: should precede public
launch** — cheaper than SEC-01 and mitigates the same worst case.

### Fine to carry

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

## F. Performance (4)

### Fine to carry

**PF-01 — `capability_discovery` re-imports every workflow module on every
call, with no cache and no invalidation policy.** `_import_module` runs
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

**PF-02 — `save_topic` reads back the file it just wrote.**
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
`docs/decisions/mcp-layer.md` §5 — *"No token streaming, no `interrupt()`/resume
over MCP. A workflow with a `human.approval` node will block rather than
pause-and-resume… Making interrupts work over MCP needs a resume tool and a
durable checkpointer — both real work, neither speculatively built."* Blocked
by RC-02. **Size M.** **Verdict: fine to carry.**

---

## Verified closed — named on the intake list, checked, and not a gap

These were investigated for this register and found already fixed. They are
listed so nobody re-adds them from an old session report.

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

---

## Maintaining this file

One rule: **a deferral is not recorded until it is in here.** A session report,
a commit body, or a code comment may *also* say it — this file is what gets
read. When an entry closes, delete it and add a line to "Verified closed" only
if it was ever externally visible; otherwise just delete it.
