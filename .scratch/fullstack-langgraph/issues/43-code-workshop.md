Type: task
Status: resolved (2026-08-08) — live-verified incl. HITL
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

## Resolution

Built (session + integration): jailed file/pytest/git tools (`tools/workshop.py`, path-escape refused, fixed pytest runner only), fixture repo with seeded failing median test, deep-tier coder agent, review via `workflow.subgraph` (`code-workshop-review`), grader, `human.approval` before `release1` which writes dry-run `output/PR.md` + `change.patch` (gh strictly opt-in, still behind approval). Live E2E: agent fixed the bug, 5/5 tests passed, interrupt → approve → PR artifacts written fresh.
