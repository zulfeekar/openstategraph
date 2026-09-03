---
name: kanban-patrol
description: Scan this project's recorded runs for findings (redundant tool calls, unstable results, node failures) and file any that are new as kanban board cards, so the patrol board reflects real problems instead of sitting empty. Use when asked to "run a patrol," "scan for issues," or "update the kanban board."
---

# kanban-patrol

OpenStateGraph's own patrol skill: reads what this project's own finding
detectors already know, decides what is worth a card, and files it. It
invents no new detection of its own — it orchestrates what already exists
(`openstategraph`'s `run_findings`, over the checkpointer).

## The loop

1. **Read.** Gather findings across every recorded thread this project holds
   — a repeated tool call, an unstable result, a node that failed — using
   whichever door is available to you (the CLI, the MCP tools, or a direct
   read, if you have one).

2. **Skip what's already filed.** A card's identity is `project_id +
   thread_id`, minted the same way every time — check whether a card with
   that id already exists before filing another. **A card whose stage has
   already left `unattended` is never touched again**, even if the same
   finding reappears on a later pass — the patrol files new work, it never
   re-litigates work already claimed.

3. **Classify.** Every finding needs a `kind` — which decides whether a
   coding agent may attend it or a human must decide — and a `category`.
   A deterministic finding with an obvious remedy (a node failed for a
   named, fixable reason) is usually a `bug`: an agent can go and fix it.
   A finding with no clear remedy, or one that changes user-facing
   behaviour, is a `grilling` — a human must weigh it first.

4. **Author.** Hand the finding to `atom-forge` to produce the ticket text.
   Do not write the ticket yourself here — that is a separate skill on
   purpose, so a ticket authored by a patrol reads identically to one
   authored any other way, by anyone.

5. **File.** Use this project's own filing door (the CLI or MCP tool this
   project exposes for creating a card) with the classified fields and the
   authored ticket as the card's instruction text.

## What this skill refuses to do

- **Never re-run a workflow to manufacture a finding.** Findings come from
  history already recorded; this skill reads history, it does not execute
  anything.
- **Never move a card past `unattended`.** Attending and resolving are a
  human's or a coding agent's job, through the project's own attend/stage
  doors — the patrol only ever files a card into existence, never claims or
  advances one.
- **Never file the same task id twice.** Idempotency is not optional; check
  before you file, every time.
