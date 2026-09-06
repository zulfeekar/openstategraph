---
name: kanban-patrol
description: Scan this project's recorded runs for findings (redundant tool calls, unstable results, node failures, a run whose every tool call was refused the same way) and file any that are new as kanban board cards, so the patrol board reflects real problems instead of sitting empty. Use when asked to "run a patrol," "scan for issues," or "update the kanban board."
---

# kanban-patrol

OpenStateGraph's own patrol skill: reads what this project's own finding
detectors already know, decides what is worth a card, and files it. It
invents no new detection of its own — it orchestrates what already exists
(`openstategraph`'s `run_findings`, over the checkpointer).

## The loop

1. **Read.** Gather findings across every recorded thread this project holds
   — a repeated tool call, an unstable result, a node that failed, or a run
   in which nothing came back at all — using whichever door is available to
   you (the CLI, the MCP tools, or a direct read, if you have one).

   The kinds, by their own names:

   | name | what it says |
   | --- | --- |
   | `redundant-tool-call` | the same call, answered the same way. Waste. |
   | `unstable-tool-result` | the same call, answered differently. Information. |
   | `node-failure` | a node failed, and the compiler's marker says why. |
   | `every-tool-call-failed` | **every** call this run made was refused, and refused the same way — a warehouse that will not log in, a key that expired. Nothing the run said rests on a result. |

2. **Skip what's already filed.** A card's identity is `project_id +
   thread_id`, minted the same way every time — check whether a card with
   that id already exists before filing another. **A card whose stage has
   already left `unattended` is never touched again**, even if the same
   finding reappears on a later pass — the patrol files new work, it never
   re-litigates work already claimed.

   **`every-tool-call-failed` is the one exception to the identity, and it
   is deliberate.** Its card is keyed by the **refusal**, not by the thread:
   one client secret that has stopped working refuses every call for a day
   across every thread anybody opens, and a per-thread key files a card per
   thread for one problem. So that card's id is
   `project_id + ":refusal:" + a digest of the refusal's first line`, it
   carries a count across runs, and the second patrol over the same evidence
   files nothing.

3. **Classify.** Every finding needs a `kind` — which decides whether a
   coding agent may attend it or a human must decide — and a `category`.
   A deterministic finding with an obvious remedy (a node failed for a
   named, fixable reason) is usually a `bug`: an agent can go and fix it.
   A finding with no clear remedy, or one that changes user-facing
   behaviour, is a `grilling` — a human must weigh it first.

   An `every-tool-call-failed` card is a `bug` at `high`, and its story
   quotes the refusal, names the tool type and the **names** of the
   environment variables that type's connection reads — never a value, ever —
   and the provider's own error code when the refusal carried one.

4. **Author.** Hand the finding to `ticket-forge` to produce the ticket text.
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

## The trap: a patrol eventually reads its own reflection

Every run this project records becomes something a later patrol reads. That
includes the runs **you** make — the question you ask a workflow to reproduce
a card's defect is a run, in a new thread, with findings of its own. The
idempotency rule above does not save you from it: that thread is genuinely
new, so the next patrol files a card about the work you did on the last card,
and the board slowly fills with its own shadow.

**So mark every run you make while working the board**, and the marker is the
sitting the run belongs to:

- working card `<task_id>` — pass the session `card:<task_id>`
- driving a patrol yourself — pass a session beginning `patrol:`

Each door takes it under its own name:

    openstategraph run <package> "<question>" --session-id card:<task_id>

and over MCP, `run_workflow` takes a `session_id` argument that means the
same thing. A run marked either way is skipped by the next patrol; an
unmarked run is ordinary traffic and is still read, so the marker is the only
thing standing between the board and its own reflection. Set it every time.
