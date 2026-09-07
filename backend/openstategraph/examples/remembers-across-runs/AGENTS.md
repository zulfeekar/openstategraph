# Remembers Across Runs

Gallery example 23 — **one ledger, many runs**, and the only example where the
interesting thing happens *between* two runs rather than inside one.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the request enters |
| `mem1` **What you have told me** | `memory.segment` — a tollbooth on the wire |
| `answer1` **Concierge** | answers what was just said, using what was said before |
| `out1` **Answer** | renders the answer |

Four nodes in a straight line. The memory node sits *on* that line, between the
question and the agent, and the position is the whole mechanism: a memory node
wired off to one side records nothing, because nothing crosses it.

## What a crossing does

Three things, in this order, every time flow reaches it:

1. **Furnishes** the entries the segment already holds into what flows onward,
   as a block headed `## Memory`.
2. **Records** what arrived, verbatim.
3. Passes both on.

Furnish *before* record, deliberately. The other order would hand the agent its
own question back inside the block it is reading, which looks like a duplicate
and is really a lie about when the line was written.

Nothing in that path calls a model, so a crossing costs no tokens — and the
node's card says so because it is true by construction, not by discipline.

## The name is the ledger

`data.segment` is `what-you-told-me`. The ledger is keyed by that name and by
this workflow, so two tollbooths carrying the same name are **one** ledger read
and appended at both positions, and it survives a restart because the Store is
durable. This example places one; placing a second before the output, with the
same name, would record the answers alongside the questions with no other
change.

`data.retention` is `20` — a bounded default, on purpose, because this package
gets **copied** into somebody's own workflows root and grows in their Store.
Blank means unbounded and is perfectly legal; a shipped example is the wrong
place to demonstrate it.

## Smoke run — the two runs are the point

```
openstategraph examples copy remembers-across-runs
openstategraph run workflows/remembers-across-runs \
  "My favourite composer is Sibelius, and I always take my coffee black." \
  --thread-id run-one
openstategraph run workflows/remembers-across-runs \
  "Who is my favourite composer, and how do I take my coffee?" \
  --thread-id a-completely-different-thread
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`.

**Run 1**, empty ledger:

> Thanks for sharing!

**Run 2**, a thread that has never seen run 1:

> Your favourite composer is Sibelius, and you always take your coffee black.

The thread ids differ, so the checkpointer — which is the thing that carries a
conversation — holds nothing from run 1. What reached the agent is the block
`mem1` furnished, and a third run shows it verbatim:

```
## Memory · what-you-told-me — 3 entries
1. My favourite composer is Sibelius, and I always take my coffee black.
2. My favourite composer is Sibelius, and I always take my coffee black.
3. Who is my favourite composer, and how do I take my coffee?

And what do I drink?
```

Two things worth reading off that block. The duplicate first entry is a run
whose **agent failed** for want of a credential — the tollbooth had already
been crossed, and recorded, before anything downstream had a chance to fail,
which is what a deterministic node placed on a wire means. And the third entry
is run 2's own question, appended after run 2 was furnished with the first two.

## What it does not claim

- **The card shows no entry count.** The ledger is server-side, so a card
  cannot know its size before a run. It shows the segment name and the
  retention — both true with nothing having happened — and the count is
  furnished by the run itself.
- **It is not summarised.** The record is verbatim. Anything you want condensed
  is an agent node placed upstream, separately drawn and separately paid for.
- **A Guardrail placed after it does not reach what it already recorded.** An
  outbound policy scrubs what flows onward; the Store keeps what crossed.

## Pairs with the memory tools

Every agent gets `save_memory` when a store is present — the half of memory the
*model* decides to use. This is the other half: a write that happens because
the flow reached a position. Both are real, and the reason they are two
mechanisms rather than one is that a drawn node whose position implied a
guarantee the model was free to ignore would be a node that lies.

## Tests

`tests/` asserts the wire, the segment name, and that the shipped retention is
bounded — all without a model or a Store. Whether the model *uses* what it was
handed is what the two-run smoke above is for.
