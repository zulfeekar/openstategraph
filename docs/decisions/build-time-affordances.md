# Where a build-time action lives on a canvas of run-time nodes

**Status: accepted (ticket 16, 2026-08-11). Generalises the second-brain
builder's answer into the pattern the map asked for.**

## The tension

Everything draggable on this canvas is a node, and every node compiles to a
LangGraph construct. But some actions act *on* a workflow without being a
step *in* it — building a second brain, running an evaluation, publishing.
They happen at build time, on a button, and the compiler must never be able
to reach them. The knowledge record states this as invariant 3: *"the
knowledge an answer relies on predates the question."*

Naively, "drag and drop a builder" wants a node that compiles to nothing.
Reject that. A node that compiles to nothing is a node whose ports, edges and
position mean nothing — validation, layout, undo and the compiler would each
need a branch for it, and the canvas would stop being a picture of a graph.

## The rule

> **A build-time action is an affordance on the run-time declaration it acts
> upon. Where there is no such declaration, it is a panel action scoped to
> the open workflow. It is never a node of its own.**

One question decides which: **does this action have a run-time counterpart
already on the canvas?**

| Build-time action | Run-time counterpart | Therefore it lives on… |
| --- | --- | --- |
| Build second brain | the `knowledge_lookup` tool an agent calls | the **Knowledge atom's card** |
| Regenerate root routing docs | the same tool, on the root's own store | the same card |
| Publish | none — publishing is about the package, not a step | a **panel action** |
| Run an eval suite | none — an eval is a harness *around* the graph | a **panel action** |

The Knowledge atom is the worked example, and it is not a special case: the
atom is a **run-time node that hosts a build-time affordance**. It compiles
to a real tool (`prebuilt_knowledge.KnowledgeLookupTool`) that a real agent
calls at run time. The button beside it is not part of the compile at all —
it `POST`s to `/api/workflows/<slug>/knowledge/build`, which writes files.

That is why invariant 3 is **structural rather than conventional**: there is
no compile path from the button. A trainer cannot run during a customer run
because nothing in the emitted graph can reach one. Nobody has to remember
the rule.

## Cardinality: what `maxInstances` counts

The Knowledge atom declares `maxInstances: 1`
(`src/nodes/tools/PlatformToolsNode.ts`). The mechanism was already there and
already counts the right thing — `model.countOfType` is over the **open
document**:

```
one document  =  one package  =  one knowledge/ directory
```

So "one second brain per workflow" needs no new scope concept. A second atom
would be a second card claiming the same single store, and two "Build second
brain" buttons racing over the same files.

And the owner's collision question answers itself mechanically: a **mounted
child is a different document with a different model**, so a root workflow
and a `data-analytics` team may each hold one. Two stores, two directories,
zero collision. Verified end to end — see below.

## When the affordance is a panel action instead

Same invariant, different home. A panel action must still:

- be scoped to the **open workflow**, named in its own label, so it is never
  ambiguous which package it writes;
- state that it is build-time in the surface itself, not only in a decision
  record;
- write through the same seam the node-hosted version would — for knowledge,
  `BaseKnowledgeBuilder.write`; never a second write path.

## Why not the alternatives

**A distinct build-time atom that compiles to nothing.** Costs a branch in
every consumer of the node contract, and buys a picture that lies: a card
with ports nothing may connect to, sitting in a graph where a card means a
step. Rejected.

**A panel action for knowledge specifically.** Loses the visible
declaration. The atom on the canvas is what tells a reader "this workflow has
a second brain" while they are looking at the workflow, and it is where the
topic index and the curation editor already live. Ambient seeking means the
atom is not *required* for lookup — that is exactly what frees it to be the
declaration and the affordance's home rather than a wiring obligation.

## Verification (ticket 16, run rather than reasoned)

Reproduced against a scratch workflows root — `OPENSTATEGRAPH_WORKFLOWS_ROOT`
pointed at a temp directory, no shipped workflow touched:

- A gateway mounting one child, compiled through the real
  `WorkflowServices.runtime_for`, produced **two** ambient knowledge
  bindings: the gateway's agent resolved to the gateway's `knowledge/` and
  found only its routing pointer; the mounted child's agent resolved to the
  child's `knowledge/` and found only its table detail. Each store is
  reachable by routing there, and by nothing else.
- The root builder's own discovery rule was **wrong in both directions** and
  is corrected — see `knowledge-architecture.md`.
