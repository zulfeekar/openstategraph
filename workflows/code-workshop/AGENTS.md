# Code Workshop (deep coder + grader loop + review subgraph + approval + dry-run PR)

An OpenStateGraph workflow — ticket 43's coder use case, end to end on the canvas.
`workflow.json` in this directory is the source of truth for its nodes and
edges — edit it through the editor, not by hand, unless you know the
canonical serialization rules (ticket 19).

**What it does**: the user describes a bug or task → a deep agent
(`tier: "deep"`: filesystem/planning/subagents built-ins) fixes it inside a
sandboxed copy of `data/fixture-repo` using only the jailed tools below → a
grader checks the answer carries a real diff and a green pytest report
(revise loops back to the coder) → the `code-workshop-review` workflow runs
as a subgraph and produces a hunk-by-hunk review → `human.approval` gates the
finish (reject loops back to the coder with feedback) → a release agent
packages the change via `workshop_create_pr`.

- **Run it**: open `code-workshop` in the editor and use Chat (the
  streaming endpoints carry the checkpointer that `human.approval` needs),
  or `POST /api/runs/stream` with this directory's `workflow.json` and
  `workflow_slug: "code-workshop"` so the tools resolve.
- **Tools** live in `tools/workshop.py`. Safety rails are enforced there, in
  trusted code: every file operation is jailed to `scratch/` (resolved paths
  verified, escapes refused as data), git runs isolated (fresh repo in the
  scratch copy, global/system config disabled), the only runnable process is
  a fixed pytest invocation, and PR creation is **dry-run by default** —
  `output/change.patch` + `output/PR.md`. Invoking `gh pr create` requires
  the PR node's explicit `useGh: true` *and* still sits behind the
  `human.approval` gate.
- **Fixture**: `data/fixture-repo` is a pristine template with one seeded
  failing test (`median()` on even-length lists). `scratch/` and `output/`
  are runtime artifacts, gitignored; the repo's `pytest.ini` excludes `data/`
  from collection so the seeded failure never reddens the main suite.
- **Tests** for the tools are in `tests/`; the saved document itself is
  compiled and exercised by `backend/tests/test_code_workshop_file.py`.
