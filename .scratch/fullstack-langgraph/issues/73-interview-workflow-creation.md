Type: task
Status: open — v1 skill shipped; conversation-state change pending

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
