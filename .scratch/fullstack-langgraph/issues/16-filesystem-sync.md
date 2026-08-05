Type: grilling
Status: partly resolved — the editor-writes-file direction is built; watching for external changes is not
Blocked by: 07, 14

## Question

Decide how the editor and the filesystem stay in agreement.

The user's requirement: when files are created, modified or deleted, that should take effect. This implies the filesystem is a real participant, not a passive export target.

Hard constraint to resolve first: **the editor is a browser application and cannot write to disk.** The File System Access API is Chromium-only and permission-gated, so it is not a production answer. Therefore all file I/O belongs to the backend (see 07) — confirm this and record it, because it makes the Python runtime a hard dependency of *saving*, not just of *running*.

Decisions:
- Who watches for change — backend watcher pushing to the editor, or editor polling? What is the transport (reuse the run-stream from 07)?
- What happens when `workflow.json` changes underneath an open editor with unsaved changes. Reload, prompt, or merge? Undo history across an external change?
- Deletion of an open workflow, and deletion of a workflow referenced by another.
- Is generated code regenerated on save, on run, or on demand? The user said "when I run" — confirm whether that is the right trigger, given a stale generated file is a debugging trap.
- Does the editor ever *read* generated code back (see 15), or is it write-only output?

## Partly resolved (2026-08-05)

**Confirmed and built exactly as the hard constraint states**: all file I/O
is backend-only (`backend/dyflow/api/workflow_store.py`); the browser never
touches disk, it posts a document and the backend writes it. Saving is now a
hard dependency on the backend being reachable — verified live (the editor
surfaces "Could not save: ..." rather than silently falling back, when the
backend is down).

**Not built, and stated honestly rather than glossed over**: the *other*
direction — the backend or another process changing `workflow.json` on disk
and the open editor finding out. There is no watcher, no polling, no
"reload/prompt/merge" behavior for an external change, and no story yet for
deleting a workflow that's currently open in another tab. This is a real,
open gap, not a solved one — the ticket's own question about *watching* was
not this pass's scope, only the *writing* half was. Regenerating code
on-save/on-run/on-demand is moot for now since no code generation exists yet
(ticket 15's interpreter path is what runs today).
