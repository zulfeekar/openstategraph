# Status: the OpenStateGraph skill

- Gate 1 — Product: APPROVED 2026-09-04
- Gate 2 — Architecture: APPROVED 2026-09-04
- Gate 3 — Program Design: APPROVED 2026-09-04
- Gate 4 — Slice plan: APPROVED 2026-09-04

## Slices
- [x] Slice 1 — tracer: skill folder + directory installer + rules file + get_engineering_rules
- [x] Slice 2 — four agent files from one descriptor, merge semantics, init report
- [x] Slice 3 — idea cards: columns, file_idea_card, MCP + CLI file, board renders the brief
- [x] Slice 4 — triage: pure ordering, MCP + CLI, why_here
- [x] Slice 5 — the whole sheet + references + docs + documented-surface pin
- [x] Slice 6 — tested as a user (fresh install, real agent), three environments, close 25 and 26

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

### Where slice 2 departed from `03-program-design.md`
- `merge_json_servers` is typed `dict[str, object]` rather than bare `dict`;
  mypy's `--disallow-any-generics` refuses the signature as 03 writes it.
- The VS Code entry carries `"type": "stdio"` that the other three do not —
  that is the shape VS Code documents. One extra key in one renderer, not a
  second descriptor: the command line is still stated once.
- The four files are a table (`agent_config.AGENT_FILES`, agent → path → key)
  rather than four hand-written renderer functions, so a reader checks the
  research note's table against one block.
- `init`'s report now ends with two lines starting `next:` — the existing
  `next:` block and `NEXT_SENTENCE`. Left as 03 wrote the sentence; if the
  repetition grates, the fix is the older block's header, not the sentence.

### Where slice 3 departed from `03-program-design.md`
- `file_idea_card` gained an `actor` parameter 03's signature does not have.
  The slice requires the MCP door to resolve the filer through
  `_actor_on_the_card` and the CLI to take `--actor`, and with only the five
  named columns there was nowhere for that name to go. It writes the existing
  `actor` column on a still-`unattended` card, which the first `attend`
  overwrites — the honest reading of that column either way: the person this
  card is currently with.
- `blocked_by` is a `tuple[str, ...]` on `Card` and a `list[str]` on the wire,
  not the JSON text the column holds. The encoding is the store's business,
  the same way `evidence_green` is a `bool` on `Card` and an `INTEGER` in
  sqlite.
- `project_identity.project_id_for_board()` is new and not in 03's file list.
  `cmd_patrol_run` had the read-config / adopt / refuse sequence longhand and
  was the only door that needed it; there are three now, and three spellings
  of it is three chances for one door to file under an id the others do not
  use — which on a board keyed by that id means work filed where nobody looks.
- `anIdeaCardCarriesItsBrief.test.ts` reads `PatrolCard.tsx` and
  `PatrolBoard.css` as text rather than mounting the card. Forced: vitest's
  `include` is `src/**/*.test.ts` (a `.tsx` file is not collected) and this
  repository has no React mount harness. It is also the shape the board's own
  tests already use — `aBoardHeaderOutranksItsCards.test.ts` — and it lets the
  *guard* be asserted, which is the load-bearing half: an unguarded
  `{card.story}` draws an empty element on every patrol card and would pass a
  "the story appears" mount unchanged.
- `kanban_store.py` crossed the 500-line module ceiling (493 -> 544) and now
  carries a recorded row with its argument, beside the raised numbers for
  `cli.py`, `mcp_server.py`, `api/schemas.py` and `RuntimeClient.ts`.

### Where slice 5 departed from `03-program-design.md`
- **There is no CLI verb for the node vocabulary, and none was invented.**
  `openstategraph --help` has no `nodes`; the vocabulary is assembled by the
  MCP server from `compile/port_specs.json`, which the wheel ships. So the
  sheet's door table sends a command-line agent to that file rather than to a
  verb, and the honest gap is stated instead of papered over. Adding a verb
  would have been a second door onto generated data in the same slice that
  writes the sheet, with nothing pinning the two together.
- **`references/engineering-rules.md` is generated, never committed.**
  `bundled_skills.bundled_skill_files()` adds one synthetic entry
  (`RULES_REFERENCE` → `ENGINEERING_RULES`) so the installer writes the rules
  into the skill tree from the same file `get_engineering_rules` serves. A
  committed page would have been a second copy of the rules with nothing
  holding them together — the duplication those rules forbid. The two existing
  tree tests now derive their expectation from `bundled_skill_files()` rather
  than from `rglob`, because a generated file is invisible to a glob.
- **The sheet is 250 lines against a ceiling of 250**, and that is deliberate
  rather than lucky: it was written long and trimmed to fit, twice. The long
  form is in the four written reference pages.
- **The lexicon pin has one narrowed exemption.** `grilling` is a card kind in
  this product (`kanban file --kind grilling`), so the forbidden-name test
  allows the word only on a line that also says `kind`. The hyphenated names
  are forbidden outright.
- **`test_documented_skill_surface.py` also pins `docs/the-openstategraph-skill.md`
  into `docs/README.md`'s index.** Not in 03's plan; a reader's page the index
  does not name is a page nobody reaches from the documentation's front door,
  and that index is the one enumeration `docs/README.md` promises.

### Where slice 6 departed from `04-slices.md`

- **The real coding agent refused, and the fallback was taken.** `claude -p`
  in the scaffolded project answered `Not logged in · Please run /login` — a
  nested CLI carries no credentials of its own. The twelve steps were then
  driven by hand against the *installed* `SKILL.md`, through the doors it
  names and nothing else. That is weaker evidence about whether an agent
  follows the sheet and equally strong evidence about whether the sheet can
  be followed; the transcript in ticket 25 says which it is, at the top,
  rather than burying it.
- **`--version` cannot prove provenance.** The checkout still carries
  `0.3.0rc11`, the string TestPyPI publishes, so the wheel built here and the
  stale published one print the same thing. Provenance was established from
  the payload instead — the installed tree carries `agent_skills/`, and rc11
  has no `bundled_skills.py` at all. Worth knowing before the next slice
  trusts a version string.
- **Case 3b did not behave as the sheet promised, which is why it was run.**
  A bare `pip install` into a venv holding LangGraph 0.6 does not refuse — it
  silently upgrades to 1.x. The refusal is real only when the pin is stated
  to the resolver (`uv add`, `-r`, `-c`). Sheet, reference page and
  `docs/adding-openstategraph-to-your-project.md` §0.1 all corrected;
  transcripts in ticket 26.
- **Two findings were too large for wording and became tickets 29 and 30.**
  29: `get_node_vocabulary`'s `document_shape.settings` names only `model`, so
  `settings.recursionLimit` — the thing that ends a revision loop, which the
  sheet's own Budget dimension asks about — is unreachable through the doors
  the sheet points at, and a plausible guess is silently ignored. 30: a
  `--blocked-by` naming no card is accepted, and strands the card forever
  while telling its blocker `nothing waits on it`.
- **The sheet stayed at 250 lines.** Three corrections landed in it and the
  ceiling did not move: the ceiling's own argument (long form goes to
  `references/`) decided the split, so the sheet carries one true sentence per
  finding and `references/environments.md` carries the measured account.
