Type: grilling
Status: open
Blocked by: 30, 31, 32

## Question

`agent.llm` has two fields. The vision needs: tier (react/deep/custom),
systemPrompt rules + read-only locked sections, middleware slots, subagents,
structured-output opt-in, per-node model override — and ticket 22 already
counted 60+ plausible fields. The card cannot hold this and the Inspector
has no grouping.

- `FieldSchema` gains `group` and `advanced`; Inspector renders groups
  collapsed by default; card shows only `onCard` fields (model, tier, tool
  count).
- The `harness`/tier preset is the master dial: it sets group defaults,
  everything else is an override on top (ticket 22's conclusion).
- Which field kinds are still missing? Ticket 20 built repeatable-group for
  branches; subagents need the same; middleware slots likely a dedicated
  editor.
- Read-only prompt sections: rendering (ticket 31) belongs to the same
  Inspector pass.
