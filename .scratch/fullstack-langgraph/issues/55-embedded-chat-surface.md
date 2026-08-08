Type: grilling
Status: resolved (2026-08-07) — decisions recorded, implementation queued
Blocked by:

## Question

A customer-facing app should expose **only a chat / interaction window**;
the workflow, canvas and machinery stay behind the scenes.

What exists: the runtime already runs headless (`POST /api/runs/stream`
takes a document + question; SSE back), so the editor is not required to
execute — the gap is a deliberate product surface.

Decisions to grill:

- What is the artefact — an embeddable widget (script tag / iframe), a
  standalone minimal chat page served per workflow slug, or just a
  documented API contract for the customer's own frontend?
- Auth and exposure: the API is currently localhost/CORS-locked with no
  auth; what is the minimum for exposing one workflow's chat safely
  (per-workflow token? rate limits?) without dragging in the multi-user
  fog the map already records?
- What does the chat surface show of the run — answer only, or the
  activity/progress stream (node names may leak internals)? HITL approvals
  in a customer surface?
- Does this reuse `AskPanel` extracted into a shared component, or a
  separate lightweight build with no JointJS/React-editor payload?

## Resolution (auto-mode decisions, one-liners)

- Artefact: a standalone minimal chat page served per slug (`/chat/{slug}`, no JointJS/editor payload) + the SSE API contract documented — an iframe embed falls out for free; no widget SDK invented yet.
- Auth: per-workflow bearer token in workflow.settings (checked only when set), CORS stays allowlist; multi-user stays out of scope per the map.
- Surface shows the answer + coarse progress (step count, not node ids — internals stay behind the curtain); HITL approvals render as plain approve/reject prompts.
- Reuse: extract AskPanel's stream-fold into a shared headless hook; the editor panel and the chat page both consume it.
- Implementation: new task ticket once the in-flight sessions land (API + frontend files contended).
