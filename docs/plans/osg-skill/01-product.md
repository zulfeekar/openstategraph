# Product: the OpenStateGraph skill

## Problem
"I installed OpenStateGraph, I'm in my project with my coding agent, and I
have an idea for a workflow. I want to say *use OpenStateGraph* and describe
it, and get interviewed like a colleague would, get tickets I can see on the
board, and get it built the right way — tests first, real node types, no
invented tools — without me having to know the platform's rules by heart."
Today the agent has two thin sheets (write a ticket, run a patrol), no way
to find the MCP server, no interview, and no place for a new idea's tickets.

## Success metric
From a fresh folder to a compiled package with its cards on the board and
every one at *finished*, driven only by the sentence "use OpenStateGraph"
plus a concept, in one sitting, with no invented node type and no test
written after its code. Measured as the transcript of that run pasted into
ticket 25, and a test suite the skill ships with, green, each test red first.

## Announcement — the blog post before the feature
Say "use OpenStateGraph" to your coding agent and describe what you want
the workflow to do. The agent now knows the platform: it asks you the
questions a senior engineer would ask before building, writes the answers
down as tickets on your project's board, ranks them, and builds them one at a
time, test first, using only the node types, tools and rules the installed
package actually has. It draws a sketch of a proposed flow when that helps
and never sketches what exists; the compiler draws that. When a step is safe
to hand to a helper agent it says so and does, with the model you chose, and
tells you what the helper did. Everything lands in your project. If you have
the OpenStateGraph MCP server selected, the agent uses it; if not, the same
skill drives the command line. Install it with `openstategraph init`, which
also writes the one file your agent needs to find the local server.

## Three starting points, all of them supported
1. **A fresh folder.** `init` writes everything; the skill and the local
   MCP server come from the `uv tool` install, isolated from any project
   environment.
2. **An existing project without LangGraph.** Same as 1; `init` reviews an
   existing `workflows/` before touching it and `--adopt` takes it over.
3. **An existing LangGraph codebase.** The CLI, MCP server and skill are
   unaffected by the project's own LangGraph pin (isolated tool env). Using
   OpenStateGraph *as a library* inside that project needs LangGraph 1.x;
   on another major the installer refuses and the skill says so plainly
   rather than working around it (`docs/openstategraph-in-a-langgraph-codebase.md`).

## Screens
No UI. The surfaces are: the skill sheet a coding agent reads
(`.claude/skills/openstategraph/SKILL.md` and `.agents/skills/…`), the
`.mcp.json` `init` writes, the board (existing) where the tickets appear,
and the `init` report line that tells the developer what to type next.
