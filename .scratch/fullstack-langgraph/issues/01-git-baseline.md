Type: task
Status: resolved
Blocked by: —

## Question

The project is not a git repository. Establish the baseline that every later ticket depends on: `git init`, a `.gitignore` covering `node_modules/`, `dist/`, `graphify-out/`, `.scratch/` (decide: tracked or not), and an initial commit of the phase-1 editor.

Without this, `/code-review`, `/tdd` red-green loops, CI, and the git-guardrails hooks have nothing to work against, and there is no way to review a change in isolation.

Record: what is ignored, whether `.scratch/` is tracked (the map is a shared artifact — argues for tracking), and the branch strategy for a multi-session effort.

## Answer

Resolved. Repository initialised with a single baseline commit `b86018a` covering the whole phase-1 editor (149 tracked files).

**`.gitignore` decisions:**
- **Ignored:** `node_modules/`, `dist/`, `*.tsbuildinfo`, editor/OS cruft, `.env*` (except `.env.example`), `*.local`, Python artefacts (`__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` — pre-added for the backend), `coverage/`.
- **`graphify-out/` ignored.** It is derived — 1120 nodes of generated JSON plus an HTML viewer. Committing it would add noise to every diff for no benefit, and `graphify update .` rebuilds it in seconds. The rebuild command is documented in `CLAUDE.md` and `HANDOVER.md`.
- **`.scratch/` IS tracked** (28 files). This was the one real judgement call: the wayfinder map, its tickets and the decision records are the *shared artifact* of a multi-session effort. Ignoring them would mean the plan lives only in one machine's working directory and cannot be reviewed, diffed or handed over — which defeats the purpose. They are documentation, and documentation belongs in the repo.
- **`.claude/launch.json` tracked** — it is how anyone starts the dev server.

**Branch strategy:** committed on the default branch. Deliberately *not* imposing a branch-per-ticket convention yet — with one contributor and no CI it would be ceremony. Revisit when ticket 12 (repo topology) settles CI, since that is when branch protection starts to earn its keep.

**Commit-message convention:** body explains *why*, not *what* — the diff already shows what. No trailer conventions imposed yet.

**Unblocks:** ticket 11 (TDD strategy) — a test runner and `/code-review` both need a baseline to diff against.
