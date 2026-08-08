Type: task
Status: resolved (2026-08-08) — generalised and live-verified

## Question

User request: when a generic-chat user asks to create a workflow, run a
grill-me-style interview — ONE question per turn (goal → inputs → steps/
nodes → tools → outcome criteria), then compose.

The blocker is architectural, found honestly: `_agent` sends only the
current question (`payload = [HumanMessage(...)]`) — `RunState.messages`
accumulates in the checkpointer across a thread's sends but is never fed
back to the agent, so every turn is amnesiac. The interview needs:
`payload = state.messages + [new]` for agents on a continuing thread
(bounded by the summarize toggle for long threads). Small change, wide
blast radius — needs its own test pass (all four E2E suites re-run) before
the skill below can actually hold a conversation.

v1 shipped meanwhile: `workflows/workflow-architect/skills/interview.md`
instructs the Architect to detect underspecified requests and answer with
exactly one clarifying question instead of composing blind — single-turn
honest behavior; full multi-turn lands with the state change.

## Resolution

Generalised far beyond the interview after the user caught the real gap live
("what is the weather?" → "oslo" → a Wikipedia article): conversation memory
is now **structural, for every workflow** — the input node records each user
turn and the output node each answer (history exists on supervisor paths, no
agent required); `_thread_question` renders the exchange for every
intent-interpreting node; agents speak into the shared record with feedback
as its own turn. Live-verified on the exact reported scenario: turn 2 "oslo"
returned real Oslo weather (18.6°C + forecast), no drift. The Architect's
interview skill rides on the same mechanism (turn 1 clarifying-question
behaviour verified; its turn-2 composition remained provider-gated by
Ollama 500s all evening — mechanics pinned by 9 unit tests instead).

Plus the user's memory-scope model: save_memory(scope=user|workflow|app),
search across all three with provenance labels — user follows the person,
workflow holds slug-scoped findings, app is the root's shared pool.
