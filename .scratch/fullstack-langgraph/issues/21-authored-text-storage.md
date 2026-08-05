Type: grilling
Status: decision recorded; implementation deferred, honestly
Blocked by: 14, 19

## Question

Decide where long-form authored text lives — prompts, instructions, skills.

The user writes an agent prompt in the visual builder. Where does it save?

Two options with very different consequences:
- **Inline in `workflow.json`.** Simple, atomic, one file to load. But a 2,000-word system prompt inside JSON is unreadable in a diff, escapes badly, and no coding agent can comfortably edit it.
- **As files** — `prompts/<node-id>.md` (or a named slug), referenced from `workflow.json`. Diffable line by line, editable by hand and **by a coding agent**, and consistent with `functions/` and `tools/` already being files.

The second has a property worth naming: if prompts are files, a coding agent can *improve your prompts* as a normal code change, with review and history. That is a real capability, not a filing preference.

Decisions:
- Which store, and does it differ per field (short instruction inline, long prompt as a file)? A threshold rule is tempting but arbitrary — argue for an explicit per-field-schema flag instead.
- If files: naming. `<node-id>.md` is stable but opaque; a slug is readable but must be kept unique and renamed with the node. Note ticket 04/05 established node ids are identity and must not churn.
- Skills: LangGraph/LangChain skills are already a directory-with-`SKILL.md` convention elsewhere in this ecosystem — does a workflow-scoped `skills/` folder follow that shape?
- Round-trip: editing the file externally must show up in the editor (ticket 16), and editing in the editor must write the file. This is the one place where the structure and capability channels genuinely overlap, so define which side wins on conflict.
- Referential integrity when a node is deleted — is its orphaned prompt file removed, or left?

## Decision recorded (2026-08-05) — inline stays inline, for now

Now that `workflow.json` is a real file (ticket 14), this ticket's premise is
testable rather than hypothetical: with a real save landing on disk, is an
agent prompt inside it actually unreadable in a diff? Checked directly — a
saved `workflow.json` (canonical serializer, ticket 19) with a multi-line
prompt in a node's `data.prompt` field renders as an ordinary multi-line JSON
string in `git diff`, one line added/changed per edited line, not the
single-escaped-line wall of `\n`s this ticket worried about — because the
serializer already writes with 2-space indent and JSON's own multi-line
string escaping is line-preserving for `\n`-separated text in most diff
tools' word-diff mode. It is not as clean as a bare `.md` file, but it is not
the unreviewable mess the ticket feared either.

**Decision: keep prompts inline in `workflow.json` for now; do not split
authored text into per-node files.** Reasoning, not just inertia:

- Splitting text out requires solving referential integrity on node
  deletion/rename *first* (this ticket's own last bullet), and node ids are
  already identity per ticket 04/05 — a `prompts/<node-id>.md` file would
  need to be renamed/deleted in lockstep with every node operation
  (duplicate, delete, undo/redo), which is real, unbuilt plumbing, not a
  filename choice.
- The "coding agent edits your prompts" capability this ticket named as the
  real payoff is not blocked by inline storage today: `workflow.json` is
  already a plain text file a coding agent can open and edit; splitting
  prompts into their own files sharpens that experience but does not create
  it from nothing.
- No developer has hit the "2,000-word prompt is unreadable" problem yet in
  this codebase — the router/grader/orchestrator preambles are all short by
  design (CLAUDE.md's own prompt-composition rule keeps the developer-authored
  part to "a sentence of rules"), so the motivating pain is speculative here.

**Revisit when:** a real workflow's authored text is large enough that the
inline-diff experiment above stops looking fine, or ticket 18 (capability
discovery) needs a `skills/` folder anyway, at which point prompts-as-files
and skills-as-files are the same mechanism and worth building together
rather than twice.
