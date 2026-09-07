# What this changes

<!-- One paragraph. What behaviour is different after this PR? -->

Closes #

## Why

<!-- The problem, not the patch. Link the issue or ticket if there is one. -->

## How to verify by hand

<!-- Steps a reviewer can follow. "Tests pass" is not verification. -->

## Checks

```bash
npm run verify      # tsc + eslint + prettier + vitest
python -m pytest    # backend + workflow tests (live-API tests are opt-in: -m live)
```

- [ ] `npm run verify` passes locally
- [ ] `python -m pytest` passes locally (skip only if the change is TypeScript-only)
- [ ] Tests land with the change — new behaviour has a failing-first test
- [ ] Coverage ratchets are not lowered to make the build green

## Architecture

`CLAUDE.md` is the contract. Tick what applies; delete what does not.

- [ ] No new public members on `WorkflowController` or `WorkflowModel` — extension is a
      new collaborator, a new `GraphQueries` query, or a registry entry
- [ ] New capability arrives by **registering**, not by editing `core/`
- [ ] `core/` still imports neither React nor JointJS
- [ ] No hand-mirrored types across the Python/TypeScript boundary — Pydantic stays the
      single source of truth
- [ ] Node config is declared once as a field schema (card, inspector, defaults and
      validation all derive from it)
- [ ] No execution engine was written — this still compiles to a LangGraph `StateGraph`
- [ ] No LangGraph type names leaked into `workflow.json` or `core/`
- [ ] Any new multi-writer state key uses a named reducer, not a bare scalar
- [ ] No non-finite number (`Infinity`/`NaN`) in a serialisable field
- [ ] No user graph is sent to a third party (`draw_mermaid()`, never `draw_mermaid_png()`)

## Docs

- [ ] README / CHANGELOG updated if user-visible behaviour changed
- [ ] `.env.example` updated if a new environment variable was introduced
- [ ] New dependency recorded in `THIRD_PARTY_NOTICES.md` with its licence

## Notes for the reviewer

<!-- Trade-offs taken, things deliberately left out, follow-ups filed. -->
