Type: grilling
Status: open
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
