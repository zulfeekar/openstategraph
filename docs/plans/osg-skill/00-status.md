# Status: the OpenStateGraph skill

- Gate 1 — Product: APPROVED 2026-09-04
- Gate 2 — Architecture: APPROVED 2026-09-04
- Gate 3 — Program Design: APPROVED 2026-09-04
- Gate 4 — Slice plan: APPROVED 2026-09-04

## Slices
- [x] Slice 1 — tracer: skill folder + directory installer + rules file + get_engineering_rules
- [ ] Slice 2 — four agent files from one descriptor, merge semantics, init report
- [ ] Slice 3 — idea cards: columns, file_idea_card, MCP + CLI file, board renders the brief
- [ ] Slice 4 — triage: pure ordering, MCP + CLI, why_here
- [ ] Slice 5 — the whole sheet + references + docs + documented-surface pin
- [ ] Slice 6 — tested as a user (fresh install, real agent), three environments, close 25 and 26

## Notes for a fresh session
- Map: `.scratch/osg-agent-experience/` — `REQUIREMENTS.md` (owner's text
  verbatim), `OWNER-DECISIONS.md` (twelve decisions + the standing one: the
  MCP server is local stdio, never cloud), `current-state.md` (what a fresh
  TestPyPI install actually does today), `skills-survey.md`, tickets 19–25.
- The owner delegated slice-boundary approvals on 2026-09-04 ("as you
  recommend"); gates are still presented, one summary each.
- Every skill lifted from is credited by shape, never copied
  (kanban-patrol/24's rule).

### Where slice 1 departed from `03-program-design.md`
- The package-data folder is `openstategraph/agent_skills/`, **not**
  `openstategraph/skills/`. Forced, not chosen: `openstategraph/skills.py` —
  the parser for the SKILL.md format itself — already exists, and a package
  cannot hold a module and a directory of the same name. Slice 5's
  `references/` pages go under `agent_skills/openstategraph/references/`.
- `install_bundled_skills` keys its report `(root, relative_path)` rather than
  `(root, skill_name)`, because 03 asks for a report *per file* and a skill is
  now a tree. `scaffold.py`, `cli.py` and the two existing tests moved with it.
- "Never invent a node type" is a `###` inside `## Interface → Abstract →
  Base → Concrete` rather than its own `##` section. The heading pin requires
  every `##` to name a section of `CLAUDE.md`, and the long form has no
  heading by that name — the rule lives inside the ladder there too, which is
  where it belongs. The pin now measures section length at any heading level,
  so the subsection is still held to a dozen lines.
