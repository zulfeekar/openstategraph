Type: grilling
Status: open
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
