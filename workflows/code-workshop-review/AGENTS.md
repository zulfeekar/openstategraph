# Code Workshop Review (reviewer + review-quality grader)

An OpenStateGraph workflow. `workflow.json` in this directory is the source of truth —
edit it through the editor, not by hand, unless you know the canonical
serialization rules (ticket 19).

The review stage of the `code-workshop` workflow, kept as its own workflow so
it runs as a **`workflow.subgraph` node** there (ticket 34: workflow
composition = subgraphs). Its input is the coder's answer — summary + unified
diff + pytest report — and its output is a hunk-by-hunk review ending in a
`Verdict: APPROVE` / `Verdict: REQUEST_CHANGES` line. A grader loops the
reviewer until the review actually cites the diff and states a verdict.

- **Run it**: standalone via Chat (paste a diff), or — its real purpose —
  referenced by slug from `code-workshop`'s review node.
- It defines no tools or functions of its own; it is a pure text workflow,
  which is exactly what lets the subgraph isolation rule hold (a subgraph
  receives a task and reports a result; it never sees the parent's state).
