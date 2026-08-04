Type: task
Status: open
Blocked by: —

## Question

The project is not a git repository. Establish the baseline that every later ticket depends on: `git init`, a `.gitignore` covering `node_modules/`, `dist/`, `graphify-out/`, `.scratch/` (decide: tracked or not), and an initial commit of the phase-1 editor.

Without this, `/code-review`, `/tdd` red-green loops, CI, and the git-guardrails hooks have nothing to work against, and there is no way to review a change in isolation.

Record: what is ignored, whether `.scratch/` is tracked (the map is a shared artifact — argues for tracking), and the branch strategy for a multi-session effort.
