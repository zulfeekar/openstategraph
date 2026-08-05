Type: grilling
Status: resolved (authoring half) — files, backend-owned; runtime-state persistence deferred, honestly, as out of scope
Blocked by: 04, 07, 08

## Question

Decide the statefulness model for authoring.

The requirement: an edit is stored to the workflow config, so many workflows can exist and be revisited.

Decisions:
- Where do workflow configs live — files on disk, SQLite, Postgres? Who owns them, editor or backend (depends on 07)?
- Identity and versioning: does saving create a version? Is a running workflow pinned to the version it started with?
- Autosave versus explicit save, and how that interacts with the undo stack (currently in-memory only — a reload loses history).
- What "many workflows" means in the UI: a workspace list, and how a workflow is referenced by another (depends on 05).
- Does runtime state (threads/checkpoints) live alongside authoring state or separately (depends on 04)?

---

## Substrate: files versus Postgres/Supabase

Supabase has been proposed so "everything is synced". It passes the OSS test — core is Apache-2.0, components are MIT/Apache-2/PostgreSQL, and only SSO / HIPAA / SOC 2 are paywalled. The real coupling risk is `supabase-js`, not the licence: treat it as **Postgres + Realtime behind our own repository interface**, never sprinkled through the app, or runtime-agnosticism (ticket 23) dies at the data layer.

But this collides with the file layout in ticket 14. Two stores means two sources of truth unless the split is deliberate. Proposed split, to be ratified here:

| Store | Owns | Why |
| --- | --- | --- |
| **Files (git)** | `workflow.json`, `functions/`, `tools/`, `tests/`, prompts | Diffable, reviewable, agent-editable, versioned. This is source code, and git is already the best sync for source code. |
| **Postgres** | checkpoints/threads, run history, workspace index | `langgraph-checkpoint-postgres` is MIT and needs Postgres anyway; Realtime gives live run streaming to multiple viewers. |

Files own the *definition*; Postgres owns *execution*. Same shape as the structure/capability split — they do not compete.

**Resolved — (a).** Real-time collaborative editing is **out of scope** (see the map's Out of scope section for the full reasoning). "Synced" means git for the definition, Postgres for runtime state. `workflow.json` stays the source of truth.

Consequences this ticket must now carry rather than debate:
- The table split above stands: files own the definition, Postgres owns execution.
- **Canonical serialization (ticket 19) is promoted from hygiene to a hard dependency** — if git is the sync and review mechanism, a non-deterministic `workflow.json` makes both useless.
- **Live multi-viewer run observation is in scope** and is cheap: runtime state is already in Postgres, so several clients can watch one run without any CRDT. Decide the subscription shape here (Realtime channel per thread? or reuse the SSE run-stream from ticket 07 — note ticket 07 found at most one run per thread concurrently).
- **Advisory locking is optional and deferred.** If concurrent edits prove to be a real problem, a "who is editing this" flag is a small addition. Do not build it pre-emptively.
- Still to settle here: where the workspace index lives (does Postgres list the workflows, or is the filesystem the index?), and whether a workflow can be opened without the backend running at all.

## Resolved (2026-08-05) — files, backend-owned, no Postgres yet

Built exactly the split already ratified above, minus the Postgres half —
runtime state (checkpoints/threads) is genuinely out of scope for this pass,
since no run currently persists a thread at all (each `/api/runs` call is a
one-shot `graph.invoke`, not a resumed thread). So this closes the
**authoring** half of the ticket only, honestly:

- **Where**: `workflows/<slug>/workflow.json`, backend-owned
  (`backend/dyflow/api/workflow_store.py`), never written from the browser.
- **Identity/versioning**: no version history — a save overwrites. Versioning
  is what git already gives a file on disk; a second, in-app version log
  would be a second, competing history. Not built, and not proposed.
- **Autosave vs. explicit save**: unchanged and kept **both**, since they
  solve different problems. `WorkbenchContext.tsx`'s existing debounced
  `localStorage` autosave is reload/crash continuity for whatever is open
  right now; explicit Save in the Workflow Manager is the durable, named,
  file-backed save. Neither replaces the other.
- **"Many workflows" in the UI**: the existing Workflow Manager panel — list,
  save, load, delete — now backed by `GET/PUT/DELETE /api/workflows/{slug}`
  instead of a `localStorage` key. A workflow referencing another (ticket 05)
  is still unbuilt and out of scope here.
- **Workspace index**: the filesystem is the index — `GET /api/workflows`
  lists directories under `workflows/`, there is no separate index to keep in
  sync. A workflow **cannot** currently be opened without the backend
  running, by construction: the browser has no filesystem access at all
  (ticket 16's own hard constraint).

**Deferred, stated plainly:** Postgres/runtime-state persistence, workflow
versioning, live multi-viewer run observation, advisory locking. None of
these are needed for what got built (single-user, single-session authoring
against real files), and building them now would be speculative — CLAUDE.md's
own rule against building for a future requirement rather than the current
one.
