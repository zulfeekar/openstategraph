Type: task
Status: open
Blocked by: 30, 34, 33

## Question

The coder use case, end to end on the canvas: user submits a bug/task → a
deep agent (filesystem + planning + subagents) edits code in a sandboxed
scratch repo → a tool runs pytest and returns the report as data → a grader
judges the diff+tests (revise loop back to the coder) → a **review subgraph**
(ticket 34) produces a review → `human.approval` gates the finish → a PR
tool emits the patch + PR body.

Safety rails, non-negotiable: all file operations jailed to a scratch
directory; `git` state isolated (worktree or temp clone); PR creation is
**dry-run by default** (writes .patch + PR body to the workflow's output);
invoking `gh pr create` is an explicit opt-in field AND still passes through
human.approval. Tests use a fixture repo with a seeded failing test.
