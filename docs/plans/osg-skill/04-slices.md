# Slices: the OpenStateGraph skill

Trailer on every commit: `Ticket: osg-agent-experience/25` (the ticket stays
`partially` until slice 6 closes it). Each slice ends running and shown.

1. **Tracer.** Package-data folder `backend/openstategraph/skills/` holding
   the two existing sheets (moved) and a minimal `openstategraph/SKILL.md`
   (frontmatter, the routing check, the two doors, and *"read
   get_engineering_rules first"*); `bundled_skills` installs directory
   trees; `engineering_rules.md` exists with its `CLAUDE.md`-heading pin;
   `get_engineering_rules` on the MCP server returns it. Proof: `init` in a
   temp dir lists three skills in both roots; a stdio MCP client call
   returns the rules with the package version.
2. **Four agent files.** `agent_config.py`: `ServerDescriptor`, four
   renderers, merge semantics, `KEPT` on conflict; `init` writes and
   reports them and ends with the next-sentence line; `docs/mcp.md` §1
   stops hand-pasting. Proof: `init` on a dir holding a `.vscode/mcp.json`
   with a foreign server merges; the four files parse; a second `init` says
   `current` four times.
3. **Idea cards.** Five columns via `ensure_schema`; `file_idea_card`;
   `kanban_file_card` tool (actor through the principal) and `kanban file`
   CLI; the board renders story and done-when and the pasted instruction
   carries them. Proof: file a card over stdio MCP into the 8124 server's
   store, see it in Detected with its story; `Copy instruction` shows
   done-when.
4. **Triage.** Pure `triage()` + `kanban_triage` tool + `kanban triage`
   CLI with `why_here`. Proof: three cards with a blocked-by chain come
   back in the argued order from both doors.
5. **The whole sheet.** `SKILL.md` at full length with its five reference
   sheets (interview one-question-per-turn with the dimensions; sizing: map
   vs gates and say which; filing and triage; the build loop through the
   board; the four subagent gates and the card's model/effort; show-me
   rule; environments and the LangGraph-pin refusal wording; credits by
   shape); `test_documented_skill_surface.py`;
   `docs/the-openstategraph-skill.md`; README paragraph; `docs/cli.md` and
   `docs/mcp.md` sections. Proof: the sheet parses; every verb it names
   exists; the docs pin is green.
6. **Tested as a user, and close.** Build the wheel from the checkout,
   install it with `uv tool` into a fresh tool dir, `init` an empty folder,
   open a real coding agent there, say the sentence with a small concept,
   and take it to a compiled package with its cards `finished`; paste the
   transcript into ticket 25; the three-environment proofs of ticket 26;
   CHANGELOG; ceilings; close 25 and 26.

Each slice: prove it, tick it in `00-status.md`, continue (the owner
delegated slice-boundary approvals on 2026-09-04).
