Type: grilling
Status: resolved (2026-08-08)
Blocked by: 30

## Question

Three `agent.llm` nodes in the video-game workflow carry `data.systemPrompt`
— a key nothing reads. `_agent` passes no `system_prompt=` to `create_agent`
(`_worker` got that fix; `_agent` did not), and the TS node declares no such
field, so authored prompts silently do nothing.

Extend `SystemPrompt` composition (preamble → context → rules → output
contract, already proven on Router/Grader) to the agent family:

- `resolve_prompt()` on `AbstractAgentNode` is the single place config
  becomes a prompt; the `skill` port's text and the `systemPrompt` field
  compose rather than compete — decide precedence.
- The TS node gains a `systemPrompt` (rules) field; the locked sections
  render **read-only** in the Inspector beside it (the RouterNode lesson:
  never ship the contract as a pre-filled editable field).
- What is the agent's output contract? Unlike a router, a free-text answer
  is legitimate — is the contract empty by default, or tier-dependent?

Also restore/record: the reverted WIP router rewrite bypassed
`resolve_system_prompt()` entirely and interpolated the question into the
system message — the anti-pattern this ticket exists to prevent.

## Resolution

`resolve_prompt()` on the family composes SystemPrompt (context above rules); `systemPrompt` field on agent.llm reaches `create_agent(system_prompt=)`. The reverted router rewrite is gone — `BaseRouter` classifies through `resolve_system_prompt()` again. Still open: rendering the *locked* sections read-only in the Inspector.

## Locked sections shipped (2026-08-08)

`GET /api/node-contracts` serves each ladder's PREAMBLE/OUTPUT_CONTRACT from the Python classes (single source of truth); `LockedPromptSections` renders them read-only in the Inspector under Identity ('locked · runs first' / 'locked · always last'), absent honestly when the runtime is down. Endpoint + fetch live-verified; the click-to-select visual check is deferred to ticket 51's Playwright suite (synthetic DOM clicks don't traverse JointJS's pointer pipeline).
