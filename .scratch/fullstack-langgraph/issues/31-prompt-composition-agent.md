Type: grilling
Status: open
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
