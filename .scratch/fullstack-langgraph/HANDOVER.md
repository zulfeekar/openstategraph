# Handover — resume state

**Purpose.** Any agent, model or person can pick this effort up from cold. Deliberately tool-agnostic: plain markdown in the repo, so it works whether the next session is Claude Code, another assistant, a local model via Ollama, or a human.

**Keep it current.** Update the *Status* block at the end of every session, before the session ends. It is the only part that goes stale.

---

## Resume in five steps

1. **Read `CLAUDE.md`** (repo root) — the binding architecture principles. Non-negotiables live there.
2. **Read `.scratch/fullstack-langgraph/map.md`** — destination, decisions already made, fog not yet specified, out of scope.
3. **Rebuild the code graph** so you can navigate without burning context:
   ```bash
   graphify update .
   ```
   Then query it instead of reading files: `graphify explain "WorkflowController"`, `graphify path "AgentNode" "ExecutionEngine"`.
4. **Find the frontier** — open, unblocked, unclaimed tickets:
   ```bash
   cd .scratch/fullstack-langgraph/issues
   for f in *.md; do
     st=$(grep -m1 '^Status:' "$f" | sed 's/Status: //')
     [ "$st" = "open" ] || continue
     blk=$(grep -m1 '^Blocked by:' "$f" | sed 's/Blocked by: //')
     echo "$f  [blocked by: $blk]"
   done
   ```
   A ticket is takeable when every id in `Blocked by:` is `Status: resolved`.
5. **Claim one ticket** — set `Status: claimed` and save *before* doing any work. Resolve **one ticket per session** (research tickets excepted).

## Resolving a ticket

1. Read its `## Question`.
2. Do the work. For `grilling` tickets, interview the human one question at a time — never answer on their behalf.
3. Append the answer under `## Answer`, set `Status: resolved`.
4. Add a one-line gist plus link to `map.md` → *Decisions so far*.
5. Graduate any fog the answer made specifiable into new tickets; clear it from *Not yet specified*.
6. Update the *Status* block below.

## Ticket types

| Type | Driven by | Meaning |
| --- | --- | --- |
| `research` | agent alone | establish a fact a decision waits on |
| `grilling` | **with the human** | a decision reached by conversation |
| `prototype` | **with the human** | build something cheap and concrete to react to |
| `task` | agent, or a checklist for the human | manual work unblocking a decision |

## Hard rules that are easy to violate

- **LangGraph/LangChain facts come only from the `docs-langchain` MCP server.** Never from memory. If unavailable, say so rather than guessing.
- **Never write an execution engine.** We compile to LangGraph. See CLAUDE.md.
- **Tests before implementation.** Never refactor load-bearing code without tests first.
- **Pydantic is the single source of truth**; TypeScript types are generated, never hand-mirrored.
- **One ticket per session.** The pull to do more is the signal to hand over instead.

## Environment

| Thing | State |
| --- | --- |
| Dev server | `npm run dev` → http://localhost:5273 |
| Typecheck | `npm run typecheck` — currently clean |
| Build | `npm run build` — currently clean |
| Tests | **none yet** — the largest gap; ticket 11 designs them |
| Code graph | `graphify update .` (output is gitignored; rebuild is cheap) |
| Backend | **does not exist yet** — phase 1 is the editor only |
| Providers | Mock (default, offline) · Ollama (local, auto-discovers models) · Anthropic · OpenAI |

---

## Status

**Last updated:** 2026-08-04

**Phase:** planning complete for the research half; first build step starting.

**Done:**
- Phase 1 editor built and verified end to end — canvas, design system, MVC engine, 4 LLM providers, runs the seeded demo against Mock (424 tokens, renders a Markdown table).
- **9 of 25 tickets resolved** — all research, plus the git baseline. See `map.md` → *Decisions so far*.
- `CLAUDE.md` written: architecture non-negotiables.
- **Git initialised.** Baseline commit `b86018a`, 149 files. `git log` is now a valid way to see state.

**Frontier (takeable now):**
- `11-tdd-strategy` — `grilling`; **newly unblocked by the git baseline**
- `08-entity-hierarchy` — `grilling`, **the crux**; 5 tickets unblock behind it
- `12-repo-topology` — `grilling`
- `15-codegen-strategy` — `research`

**Immediate next:** `11-tdd-strategy`. Reason: there are zero tests, CLAUDE.md forbids refactoring load-bearing code without them, and **a test suite is itself the best handover artifact** — a cold session runs `npm test` and learns the state in seconds rather than reading 17k lines. It also unblocks `17` (god-class decomposition) and `19` (canonical serialization), both of which are prerequisites for the file layout.

**Open question waiting on the human:** the performance budget in ticket 11 is *proposed, not agreed* — 500 nodes / 800 edges / 60fps pan / <16ms keystroke-to-paint / zero heap growth over 100 add-delete-undo cycles. Confirm or veto before writing the perf tests.

**Nothing is claimed.** No work in progress.
