Type: grilling
Status: open
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
