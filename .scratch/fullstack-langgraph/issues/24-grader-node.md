Type: grilling
Status: resolved
Blocked by: 08, 09

## Question

Design the grader / evaluator concept. The use case requires it: agent produces a result, grader checks it, then pipe onward or send it back for another attempt.

This is LangGraph's documented **evaluator-optimizer** pattern — a generator node, an evaluator node using `with_structured_output` to return a verdict plus feedback, and `add_conditional_edges` mapping `{"Accepted": END, "Rejected + Feedback": generator}`. Nothing to invent.

But there are **two legitimate places** a grader can live, and this ticket must choose (or support both):

- **As a canvas node** — an explicit Grader node the user drops in and wires. Visible, composable, arbitrary loop-back target. Matches "everything is composable".
- **Inside an agent** — `RubricMiddleware` from `deepagents` runs an LLM-as-a-judge sub-agent against a rubric, with documented verdicts `satisfied` / `needs_revision` / `max_iterations_reached` / `failed` / `grader_error` and its own `max_iterations`. Invisible on the canvas; configured as an agent field.

Decisions:
- Which one, or both? If both, when does a user reach for each, and does the UI make that legible?
- The verdict contract for a canvas Grader node: reuse the `RubricMiddleware` verdict enum for consistency, or a simpler pass/fail plus feedback string? The verdict is what outgoing conditional edges branch on, so it defines the node's output ports (ticket 03 fixed what each branch carries).
- **Iteration cap.** A loop-back needs a bound. `RubricMiddleware` has `max_iterations`; a hand-wired loop needs either a counter in state or the graph `recursion_limit`. Decide which and how it surfaces — an unbounded grader loop is the most likely way a user burns their token budget.
- Feedback plumbing: the rejected path must carry the grader's feedback back to the generator, which means a state key and a reducer (ticket 23 fixed reducers as a named enum).
- Does a Grader node carry its own model, or inherit the workflow default?

---

## Answer — built in both languages

`backend/dyflow/abc/grader.py` (`IGrader -> BaseGrader -> Grader`, 25 tests) and
`src/nodes/routing/GraderNode.ts` (13 tests).

### Prebuilt **and** overridable, which is the user's requirement

Criteria ship with the node, so a grader works before anyone configures it. A
developer then **extends** them (default) or **replaces** them (explicit mode).
Both directions matter: extending is safe, and prebuilt behaviour that *cannot*
be overridden is a straitjacket.

Two guards on the override:

- **Replacing with an empty string keeps the defaults.** Clearing a field is far
  more often a slip than a deliberate request for no criteria.
- **The override cannot reach the output contract.** Criteria are rules;
  preamble and contract are machinery. So `replace` can never produce a grader
  whose verdict is unparseable — and the contract still renders *last*, so even
  "ignore formatting, write an essay" loses the tie.

This is generalised, not grader-specific: `SystemPrompt` now carries
`default_rules` + `replace_defaults`, so every node that composes one inherits
extend/replace for free. A latent bug surfaced while doing it — `with_context`
did not carry the new fields forward, and because the type is frozen and rebuilt,
that silently turned a `replace` back into an `extend`. Now tested.

### Cheap checks before the model

`deterministic_checks` runs first: empty answer, transported error. These were
the failure modes actually observed in the Chinook run, and a rule detects them
more cheaply and more reliably than a second model call. Tests assert the model
is **not called** in those cases. A subclass adds domain checks and calls
`super()` to keep the universal ones.

### Feedback is the point, not the verdict

`Verdict.reject()` defaults `feedback` to `reason`, because a rejection with
nothing actionable makes the revise loop pure cost — the agent just retries the
same thing. And an *unreadable* verdict **passes**: a grader that cannot decide
must not silently discard a candidate the agent worked for.

### The cycle is now drawable — and a prediction turned out wrong

Adding `PORT.feedback`, the grader's `revise` output and the agent's `feedback`
input makes the evaluator-optimizer loop wireable in the editor. `acyclicRule`
was scoped to permit a cycle **only** when it closes on a feedback port.

**But the expectation that this would wake up `acyclicRule`'s rejection branch
was wrong.** Trying the obvious accidental loop — grader `pass` back to agent
`prompt` — is rejected by `typeCompatibilityRule` first (`result` cannot feed
`text`), so the cycle check never runs. Ticket 11's finding therefore still
holds: the rejection branch remains unreachable through the real catalogue, and
**the type graph is doing the work, not the rule**. Pinned by a test that asserts
the message is a type error and *not* a loop error, so the next person does not
re-derive it.

A test also asserts the grader is the **only** node type with a `feedback`
output. If anything else could emit one, accidental cycles would become drawable
and the type gate would stop being a gate.

### Not done here

The Python compile target — grader to conditional edge in a generated
`StateGraph` — is ticket 15, along with the router's.
