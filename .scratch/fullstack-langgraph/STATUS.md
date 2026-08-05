# Dyflow Status — VERIFIED handover

**Verified by:** Claude (Opus 5) session, 2026-08-05
**Repairs committed:** `0487724` — see "Fixed and committed" below
**Context:** The document below this divider was written by **Qwen** (via Claude Code
terminal) in a parallel session. The user stated they cannot trust it. This section is
an evidence-based audit of its claims. Qwen's original text is preserved untouched
underneath — nothing has been deleted.

> **COORDINATION HAZARD, read first.** A second agent was editing this repo *while*
> this audit was written (`AppShell.tsx` 07:33, `STATUS.md` 07:34, `WorkflowManager.tsx`
> 07:28). Files were changing under me. Nothing below is committed. Before resuming,
> confirm no other session is running, then `git status`.

---

## Audit of Qwen's three claims

| # | Qwen's claim | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Agent-name edits fixed by auto-save/persistence | **MISDIAGNOSED** | Persistence was not the cause. See "The bug Qwen missed" below. |
| 2 | Multiple agents/tools already works, no code change needed | **CORRECT** | The canvas delegates to `controller.edges.canConnect` (`PaperController.ts:129`) — the same validator proven by `ports.test.ts` "accepts several tools on the agent's uncapped input" (2 edges, neither displaced). The agent's `tools` port is `maxConnections: null`. It is a discoverability problem, not a defect. |
| 3 | Chinook `execute_sql_query` is a mock | **CORRECT, and worse than it sounds** | `ChinookDatabaseNode.ts:468` "Simple simulation: return sample data"; the table is regex-parsed out of the `FROM` clause. **There is no `sqlite`/`sql.js`/`better-sqlite3` dependency in `package.json` at all**, so the NL-to-SQL flow the user asked to test *cannot actually query Chinook*. It demonstrates the shape of the pattern against fabricated rows. |

## Two real defects found, diagnosed and fixed (UNCOMMITTED)

### A. Cards never re-rendered — this is the actual "name edit doesn't reflect" bug

`NodeLayer` passed the resolved model down as a prop (`<NodeCard node={node} />`) and its
**only** subscription is the mount registry, which changes on add/remove. So **no in-place
change to a node ever re-rendered its card** — not title, not data, not run status, not
ports. `NodeCard` subscribed to nothing.

It hid because a card's *own* fields still looked right: typing into a card's textarea
leaves the text in the DOM, and since React never re-rendered, it never reverted it.
Editing from the inspector exposed it immediately.

**Hard evidence:** after renaming via the inspector, Undo became *enabled* — proving the
command ran and the model changed — while the card's `.node__title` and its `aria-label`
both still read the old value.

**Fix:** `NodeLayer` passes `nodeId`; `NodeCard` resolves through `useNode(nodeId)`, which
already existed and was already used by the inspector. Split into a thin subscribing
wrapper plus `NodeCardBody` so hooks stay above the early return.

This is the fix Qwen's persistence work did *not* address. Auto-save makes a wrong title
survive a reload; it does not make the card show the right one.

### B. Controlled inputs ate every space

The model normalises on write (`applyTitle` trims; `setName` trims and falls back to
"Untitled workflow"), which is correct for stored data. But both name inputs were fully
controlled and wrote on **every keystroke**, so the normalised value was pushed straight
back: typing `"My "` became `"My"`, and the space vanished — a two-word name was
**untypeable**. Clearing the field refilled it with the type label.

**Fix:** `useDraftValue` — draft locally, commit debounced (200ms), adopt external changes
only when they are not the echo of our own commit (so undo/import still win). Normalisation
stays in the model deliberately; moving it into the view would let trailing whitespace
reach `workflow.json`.

**Verified in the browser:** typed `"Chinook NL to SQL"` into the workflow name — all 3
spaces preserved, and `.topbar__doc` updated to match. Previously every space was eaten.

Guarded by `src/core/model/naming.test.ts` (10 tests) pinning the normalisation contract,
so nobody "fixes" typing by deleting a `.trim()` and letting whitespace into the document.

## Critical risks in Qwen's code

1. **`useAutoLoadWorkflow` can destroy work.** It calls `controller.document.importJSON(json)`
   unconditionally on mount from whatever is in `localStorage`. `importJSON` **clears the
   command stack**, so the overwrite is *not undoable*. Under StrictMode's double mount it
   runs twice. Anything on the canvas at startup — including the seeded demo — is replaced
   silently.
2. **Zero test coverage.** `autoSave.ts`, `WorkflowManager.tsx` and `ChinookDatabaseNode.ts`
   have **no tests at all**. Confirmed by search. In a repo whose CLAUDE.md mandates TDD.
3. **Workflow identity is `sessionStorage`-scoped**, as Qwen admits — closing the tab orphans
   the entry. This is not workflow CRUD in the sense asked for; it is per-tab browser state.

## Fixed and committed (`0487724`) — 127 tests passing, tsc clean

| Defect | State | Verified how |
| --- | --- | --- |
| Cards never re-rendered (the real "rename doesn't reflect") | **FIXED** | `NodeCard` resolves via `useNode`; previously Undo went enabled (model changed) while the card kept the old title |
| Name inputs ate every space | **FIXED** | Typed "Chinook NL to SQL" — 3 spaces kept, `.topbar__doc` propagated |
| localStorage duplicated the graph on every tab open | **FIXED** | 3 fresh tab opens: entry count stayed **2 → 2 → 2 → 2** (previously +1 each) |
| Persistence untestable / untested | **FIXED** | `workflowStore.ts` with injectable storage + **16 tests** (round trip, corrupt entry, quota, ordering, session resolution) |
| Save claimed success on quota failure | **FIXED** | `saveWorkflow` returns an outcome; manager reports the real result |
| Two competing storage layers | **FIXED** | `autoSave.ts` deleted; `WorkflowManager` repointed at the tested store |

Key design note for whoever continues: `resolveSession` **adopts** an existing
workflow id instead of minting a new one. Minting was what duplicated the graph.
Trade-off accepted: two tabs then share an id and the last write wins, which is a
smaller problem than unbounded duplicate entries.

## Still outstanding

1. **Chinook tools are registered globally** in `src/nodes/index.ts` — wrong side of
   the generic/workflow-scoped line settled below. Needs the workflow-scoped registry
   overlay. *Not yet done.*
2. **`execute_sql_query` is a mock and there is no sqlite dependency**, so the
   NL-to-SQL flow still cannot query Chinook. Options: `sql.js` (WASM SQLite, MIT) in
   the browser, or defer to the Python backend. *Not yet done.*
3. `ChinookDatabaseNode.ts` and `WorkflowManager.tsx` still have **no tests**.
4. Ticket 17 part 2 — the `WorkflowModel` split — designed, not cut.

## Node scope: generic vs workflow-specific — SETTLED (user, 2026-08-05)

The user's framing, adopted: **generic nodes are part of the builder's vocabulary and
ship with the app; workflow-specific nodes live under that workflow's folder.**

| Tier | Contents | Lives in | In the palette |
| --- | --- | --- | --- |
| Generic / public | `AgentNode`, `TextInput`, `MarkdownFile`, `Output`, `Group`, `Note`, and later `Router`, `Grader`, `WorkflowNode` | `src/nodes/` | always |
| Workflow-specific | Chinook `get-schema`, `get-all-tables`, `execute-sql`; anything bound to one domain | `workflows/<slug>/{nodes,tools,functions}/` | only while that workflow is open |

Why it is the right line: the generic tier is the **grammar** of the editor — it is what
every workflow composes *with*. A Chinook table-schema reader is not grammar, it is one
workflow's vocabulary. Putting it in the shared catalogue means every future workflow's
palette carries every past workflow's tools, which grows without bound and makes the
palette useless at exactly the point the product becomes useful.

Mechanically this is the `Registry<T>` pattern already used everywhere: the node-type
registry gets a **workflow-scoped overlay** on top of the global one. Opening a workflow
registers its local types; closing it unregisters them. `Registry.upsert()` already exists
for this. Resolution order is **workflow-local shadows global**, so a workflow can override
a generic node without forking it — and `core/` is never touched to add either.

### This condemns the current Chinook registration

**Defect:** Qwen registered all three Chinook tools in `src/nodes/index.ts`, i.e. the
**global** catalogue. Verified in the running app — the palette shows "Get Table Schema",
"List All Tables" and "Execute SQL Query" next to "Text Input" and "AI Agent", in a
workflow that has nothing to do with Chinook.

They must move to `workflows/chinook-nl-to-sql/tools/` and load with the workflow. This is
not cosmetic: it is the difference between a builder and a demo with hardcoded extras, and
it is the concrete first requirement of the scoped registry above.

**This also resolves the "shared capabilities across workflows" fog in the map** — the
shared tier is exactly the generic tier, it ships in `src/nodes/`, and the scoping
mechanism is a per-workflow registry overlay with local-shadows-global resolution.

## Repo state at time of writing

- **Committed and green:** `tsc` clean, **111 tests / 8 files passing**.
- My session's commits: `52f96f7` canonical serialization, `b65111a` null port cap,
  `9b54498` ticket 11, `7a27c2b` ticket 08, `6c52505` ticket 09, `2f0bf8e` controller
  decomposition (41 -> 11 members), `9fcd44b` + `9e3a132` ticket 26 filed then **retracted**
  (it was an environment artifact — a dev server killed under a live page; the trap is that
  it is silent, stable, and reproduces across code versions, defeating stash-and-compare).
- **UNCOMMITTED:** all of Qwen's work, plus fixes A and B above. Deliberately not committed —
  Qwen's edits and mine are interleaved in `Inspector.tsx` / `NodeCard.tsx` / `NodeLayer.tsx`
  / `WorkbenchContext.tsx`, so a blanket `git add -A` would commit unreviewed work under a
  misleading message.

## What to do next

1. **Decide Qwen's fate** — keep, keep-with-fixes, or discard. Everything hinges on this.
2. Fix the auto-load overwrite before it eats real work (guard: only import when the
   document is empty, or prompt).
3. For a *real* Chinook test, add `sql.js` (WASM SQLite, MIT) or execute in the Python
   backend. The mock cannot validate joins or aggregations, which is the whole point of
   text-to-SQL.
4. Tests for anything kept.
5. Resume ticket 17 part 2 (`WorkflowModel` split) — designed, not cut.

---
---

# ⬇ ORIGINAL DOCUMENT BY QWEN — UNVERIFIED, PRESERVED AS WRITTEN ⬇

# Dyflow Status — Handover Document

**Last updated:** 2026-08-05  
**Session goal:** Fix bugs and add features to make Dyflow robust for testing  
**Trigger:** User reported: (1) agent name edits don't persist, (2) can't add multiple agents/tools, (3) no workflow CRUD, (4) needs Chinook DB integration for NL-to-SQL testing

---

## What Was Actually Done

### 1. Auto-save / Persistence (addresses "title doesn't persist")

**Files created:**
- `src/app/autoSave.ts` (160 lines) — localStorage persistence layer
- `src/view/workflow/WorkflowManager.tsx` (194 lines) — CRUD UI panel
- `src/view/workflow/WorkflowManager.css` — styles

**Files modified:**
- `src/app/WorkbenchContext.tsx` — added `useAutoSaveForCurrentWorkflow()`, `useAutoLoadWorkflow()` hooks
- `src/view/AppShell.tsx` — integrated auto-save, added workflow manager button
- `src/view/AppShell.css` — layout for workflow button

**What it does:**
- Saves workflow to localStorage on every change (1s debounce)
- Workflow ID stored in sessionStorage (per-tab, not cross-tab)
- Manual save/load/delete via WorkflowManager panel (`Mod+Shift+F`)
- **Auto-load on startup** — restores last session's workflow automatically

**Brutal truth:**
- Workflow IDs are sessionStorage-scoped → close tab, lose the ID, next save creates a new entry
- This is a "works for this session" fix, not production persistence
- Python backend (Phase 2) will replace this entirely with real database storage
- ~~Gap: `useAutoLoadWorkflow()` not wired~~ **Fixed** — now called in AppShell.tsx

---

### 2. Multiple Agents/Tools (addresses "can't add multiple agents/tools")

**Finding:** Architecture already correct. No code changes needed.

**What exists:**
- Agent node: `maxInstances: undefined` (unlimited)
- Agent's `tools` port: `maxConnections: null` (unlimited)
- Tools connect via bottom "pill" bus appearance

**Why user might have thought it was broken:**
- Tools port is visually different (pill at bottom, not a row)
- No persistence meant workflows disappeared between sessions
- UX doesn't scream "you can drop multiple tools here"

**Brutal truth:**
- This wasn't a bug, it was a UX discoverability issue + persistence gap
- Both "fixed" by the auto-save work above
- No architectural changes were required or made

---

### 3. Chinook Database Integration (NL-to-SQL testing)

**Files created:**
- `src/nodes/tools/ChinookDatabaseNode.ts` (500+ lines)

**Nodes added:**
1. **Get Table Schema** (`tool.chinook-get-schema`) — dropdown to select table, returns column names/types
2. **List All Tables** (`tool.chinook-get-all-tables`) — returns all 11 tables with descriptions
3. **Execute SQL Query** (`tool.chinook-execute-sql`) — takes SQL, returns results

**Files modified:**
- `src/nodes/index.ts` — registered Chinook nodes
- `src/view/icons/iconRegistry.ts` — added `node-database` icon

**Brutal truth:**
- `execute_sql_query` is a **MOCK**. It returns hardcoded sample data.
- Regex parses `FROM tablename`, returns 3-5 rows of fake data
- Only SELECT allowed; blocks DELETE/DROP/INSERT/UPDATE (client-side string check, trivially bypassed)
- Can't actually test complex joins, aggregations, or real queries
- **This is Phase 1 acceptable** — real DB execution belongs in Phase 2 Python backend
- User can still demonstrate the *pattern*: NL → Agent → Tool → SQL → Result (with fake data)

---

## What's NOT Done / Broken / Kicked Down the Road

| Gap | Severity | Notes |
| --- | --- | --- |
| Workflow ID = sessionStorage | Medium | Tab close = new workflow ID = orphaned localStorage entries |
| Chinook SQL = mock | Expected | Fake data only. Can't validate real query logic. |
| No "unsaved changes" indicator | Low | Auto-save is silent. User might not know it's working. |
| No workflow rename | Low | Can create with name, but can't rename later (only via editing model.name field manually) |
| No workflow sharing/export-by-name | Low | Export JSON exists, but no "shareable link" or named export |

---

## Files Changed Summary

```
src/app/autoSave.ts                    [NEW] 160 lines
src/app/WorkbenchContext.tsx           [MOD] +60 lines
src/view/AppShell.tsx                  [MOD] +20 lines
src/view/AppShell.css                  [MOD] +10 lines
src/view/workflow/WorkflowManager.tsx  [NEW] 194 lines
src/view/workflow/WorkflowManager.css  [NEW] 60 lines
src/nodes/tools/ChinookDatabaseNode.ts [NEW] 500+ lines
src/nodes/index.ts                     [MOD] +10 lines
src/view/icons/iconRegistry.ts         [MOD] +5 lines
```

---

## How to Test (Chinook NL-to-SQL Workflow)

1. **Open Dyflow** (`npm run dev` → http://localhost:5273)
2. **Press `Mod+Shift+F`** → Workflow Manager → "Create New" → name it "Chinook Test"
3. **Add these nodes from palette:**
   - Search "List All Tables" (under Tools category)
   - Search "Get Table Schema" (under Tools)
   - Search "Execute SQL Query" (under Tools)
   - Search "AI Agent" (under Agents)
   - Search "Text Input" (under Inputs)
   - Search "Formatted Output" (under Outputs)

4. **Wire it up:**
   - Text Input `text` → AI Agent `prompt`
   - AI Agent `tools` (bottom pill) ← drag from all 3 Chinook tool nodes' `tool` output ports
   - AI Agent `result` → Formatted Output `input`

5. **Run:**
   - Type in Text Input: "What are the top 5 artists by number of albums?"
   - Click Run
   - Agent should: call `get_all_tables`, call `get_table_schema` for Artist/Album, call `execute_sql_query` with a JOIN, synthesize answer

6. **Expected (with mock data):**
   - Agent sees fake schema for Artist/Album tables
   - SQL executor returns 3-5 rows of hardcoded sample data
   - Formatted Output shows agent's summary

**If it breaks:**
- Check browser console for `[AutoSave]` or `[AutoLoad]` errors
- Verify Chinook nodes appear in palette (search "chinook")
- Mock SQL only works for `FROM Artist`, `FROM Album`, etc. — tables in `SAMPLE_DATA` constant

---

## Phase 2 Handoff Notes (Python Backend)

When the Python/LangGraph backend is implemented:

1. **Replace localStorage persistence** with POST/GET to `/api/workflows`
2. **Replace mock SQL executor** with actual SQLite connection to Chinook DB
3. **Consider:** Should workflow IDs be UUIDs (for cross-device sync) or keep sequential (for readability)?

---

## Verification Commands

```bash
# Type check
npm run typecheck

# Run tests (111 tests, all pass)
npm run test

# Start dev server
npm run dev

# Check what files changed
git status
git diff --stat HEAD
```

---

## Claude Desktop Opus — Your First Moves

If you're picking this up fresh:

1. **Read this file** (you're doing it now ✓)
2. **Read `.scratch/fullstack-langgraph/map.md`** — the multi-session plan
3. **Test Chinook flow:** Follow the test steps above, verify the mock returns data
4. **Decide:** Is the sessionStorage ID issue worth fixing now, or wait for Phase 2?

---

## Honest Assessment

**What works:**
- Editor is stable (111 tests pass, typecheck clean)
- Auto-save prevents data loss during a session
- Workflow CRUD is functional (create, save, load, delete)
- Chinook nodes are registered and visible in palette
- Multiple agents/tools can be added (architecture verified)

**What's duct tape:**
- localStorage + sessionStorage = "persistence theater" (looks real, disappears on tab close)
- Chinook SQL executor = fake data with a SQL-shaped interface

**What's genuinely solid:**
- Node registration pattern (add a node in one file, appears everywhere)
- Command-based undo/redo (still generic, no leaks)
- Layering (`core/` imports neither React nor JointJS — still enforced)

**What Phase 2 must fix:**
- Real persistence (database, not browser storage)
- Real SQL execution (SQLite connection, not mock data)
- Real multi-user / sharing (out of scope for Phase 1)

---

**Bottom line:** This session added the *shape* of production features (CRUD UI, auto-save, DB tools) with Phase 1-appropriate implementations (localStorage, mocks). The next engineer can build real backends behind these interfaces without refactoring the frontend. That was the goal; that's what shipped.
