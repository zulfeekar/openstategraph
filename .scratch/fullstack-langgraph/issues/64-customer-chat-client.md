Type: task
Status: open — claimed 2026-08-08
Blocked by: 55 (decisions)

## Question

The real deal: a customer-facing LLM client hooked to the workflow app —
pick one of the existing workflows, chat, watch it think (streamed
findings), get the result with real error handling. Identity model:
`thread_id` (one conversation with one workflow's checkpointer),
`session_id` (a browser session), `user_email` (the person — future memory
namespace key). Implementation per 55's decisions: standalone `/chat` page
served by the backend (no editor payload), workflow selector from
`GET /api/workflows`, SSE consumption, HITL approve/reject inline.
`RunRequest` grows optional `session_id` + `user_email` (forwarded into run
config/metadata; memory tickets consume them later).
