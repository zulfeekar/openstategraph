---
name: openstategraph
description: Build a workflow with OpenStateGraph — interview the developer, file the work as cards on their board, then build it test-first using only the node types, tools and rules the installed package actually has. Use when someone says "use OpenStateGraph" or asks for a workflow, agent graph, router, grader or pipeline in a project that has OpenStateGraph installed.
---

# OpenStateGraph

## First, whose project is this?

Ask one question of yourself before anything else: is the developer asking
for a **workflow in their project**, or for a change to **OpenStateGraph
itself**? Only the second needs this repository's own checkout. If the ask is
about the platform and the current directory is not an OpenStateGraph
checkout, say so plainly and stop — do not edit an installed package.

## Two doors, and you already have one of them

- **MCP.** If the `openstategraph` MCP server is selected, use its tools.
  `openstategraph init` wrote the config file your agent reads.
- **The command line.** Otherwise everything here has a CLI verb:
  `openstategraph validate`, `compile`, `kanban ...`. Same steps, same order.

Check which door you have before promising the developer anything.

## Read the ground rules before you compose

Two calls, every time, before the first node exists:

- `get_node_vocabulary` — every node type, every port id and type, what may
  legally connect to what. Your model cannot invent these.
- `get_engineering_rules` — what may be *built* out of them: the
  interface → abstract → base → concrete ladder, extension by registration,
  port cardinality, one field schema, tests first, and the rule that decides
  most arguments — **never invent a node type**. When nothing registered
  fits, that is not a dead end: implement the family's base, register it,
  then use it. The rules text names the pipeline.

Without the vocabulary you compose documents that fail validation for reasons
the verdict can only explain afterwards. Without the rules you build something
that works once and cannot be extended.

## Then say this to the developer

> Tell me what the workflow should do, and I will ask you the questions a
> senior engineer would ask before building it.

One question per turn, their answers recorded as cards on the project's board,
ranked, and built one at a time — a failing test first, then the code that
passes it. Never write a test after its code. Never validate by running a
model when `validate` and `compile` answer deterministically.

## References

`references/` beside this file carries the long form — the interview, the
build loop, the subagent gates, the environments and a copy of the
engineering rules for the command-line door. Read the one the step needs.
