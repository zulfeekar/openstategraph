# The OpenStateGraph skill

**Say "use OpenStateGraph" to your coding agent, describe the workflow you
want, and answer its questions.** That is the whole interface. This page is
what happens after you say it, so you can tell whether your agent is doing the
right thing.

`openstategraph init` installs the skill into your project. Nothing else is
needed and there is nothing to configure.

## What you say

Anything that names the product and describes a want:

> use OpenStateGraph — I want a workflow that reads a support ticket, decides
> which team it belongs to, and drafts a reply the team can send

Or, if your agent already has the `openstategraph` MCP server selected, just
describe the workflow. The server's presence is enough.

## What happens

1. **It works out whose project this is.** A workflow for *your* project is
   built here. A change to OpenStateGraph itself — a new node family, the
   compiler — belongs in an OpenStateGraph checkout, and the agent says so
   rather than editing files inside your installed package.
2. **It reads the ground rules before composing anything.** Two reads: the
   node vocabulary (every node type, every port, what may connect to what) and
   the engineering rules (what may be built out of them). Your agent's model
   cannot invent node types, and this is what stops it trying.
3. **It interviews you, one question per turn.** The questions come from your
   concept, not from a script, and each one carries a recommended answer so
   you can agree in a word. It keeps going until nine dimensions are settled:
   input, output, which node types carry which step, where judgement belongs,
   what the tools fetch, what may not be invented, what unit every pinned
   numeric column carries, the budgets, and what "done" looks like. **"We do
   not know yet" is a legal answer** — an explicitly accepted gap is settled;
   a silent one is not. (This line said eight until `osg-agent-experience/81`
   noticed it; `75` added the units question and this page did not follow.)
4. **It recommends a shape, and says what it rejected.** Before a single card
   exists it asks the one question the interview does not: *what in this
   concept is going to multiply?* — specialists, sources, tenants, teams,
   checks, decisions. It reads your counts against a catalogue of the
   platform's own idioms (one agent; a router in front of N mounted packages;
   a revision loop; a supervisor fan-out; a guard gate; ask-back; a primary
   with a facet; one tool family behind an allowlist), then names the shape it
   recommends, the two it rejected with a reason each, and what the
   recommended one costs in calls, folders and test suites — and asks you to
   confirm. This step exists because a concept with fifteen specialists was
   once built, correctly, as sixty-six nodes on one canvas: every node right,
   the shape wrong, and nobody able to say so until it ran.
5. **It sizes the work and tells you which way it went.** A one-field change
   goes straight to building. A multi-session concept gets a decision map
   first, resolved one decision at a time.
6. **It files the work as cards on your board** — every task and every
   decision, each with a story, a done-when you can run, a priority carrying
   its own reason, and what it is blocked by.
7. **It triages and takes the top card.** Cards that unblock other cards come
   first, then priority; blocked cards last. Every card comes back with the
   rule that put it where it is.
8. **It builds one card at a time, test first.** Claim the card, write the
   failing test, watch it fail, make it pass, **break the fix and watch it
   fail again**, commit, mark it finished with the commit. The board refuses a
   finished card that carries no commit.
9. **It proves the work before it tells you it is done.** The closing step is
   a gate, not a summary: `validate` must print no problems **and** no notes —
   the same checks the editor draws in red on the canvas, so nobody has to
   open a browser to find out — and one smoke run must end at exactly one
   exit. Only then does the brief get written, and it opens with **Not clean
   yet** and every remaining warning quoted, or the words *no warnings*. This
   step exists because a router was once reported finished with green tests, a
   VALID verdict, and four red diagnostics on the canvas nobody had looked at
   (`osg-agent-experience/81`).

## The four files `init` writes for your agent

The skill is one directory installed into both `.claude/skills/` and
`.agents/skills/`, so whichever convention your agent follows, it finds it.

| File | What reads it |
| --- | --- |
| `SKILL.md` | the entry sheet — the twelve steps above, in order |
| `references/interview.md` | the long form of the interview |
| `references/build-loop.md` | the long form of the build loop |
| `references/subagents.md` | when a card may be handed to a helper |
| `references/environments.md` | fresh folder, existing project, existing LangGraph |
| `references/engineering-rules.md` | the rules themselves, for the command-line door |

The last one is **generated at install time** from the file the package ships,
which is the same text the `get_engineering_rules` MCP tool serves. There is
one copy of the rules; the two doors cannot disagree about them.

Two more skills are installed beside it — one for writing a well-formed ticket,
one for the patrol that reads your runs and files what it finds.

## The board

Everything the agent does is on the patrol board. Open it from the radar in
the editor's top bar, or read it from a terminal with
`openstategraph kanban triage`. Four columns:

- **Detected** — filed, unclaimed, ready for an agent.
- **Needs You** — a judgement somebody has to make. The agent put it here
  because it refused to make the call for you.
- **In progress** — claimed by somebody, moving through red and green.
- **Resolved** — finished, with the commit on it.

You can edit any card: change a priority, rewrite a done-when, change the
model and effort the agent should use for it. Those two fields are **advice** —
an agent that cannot choose its own model says so and carries on.

See [the patrol board](the-patrol-board.md) for the columns in full.

## What it will not do

- **It will not run your workflows without permission.** Runs are off by
  default (`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`) because a run costs money. You
  turn them on, and the agent still asks.
- **It will not invent a node type.** If nothing that exists fits your step,
  it tells you and files a card for building the type properly — through the
  family's base, registered, then used.
- **It will not draw you a picture of something that already compiles.** A
  diagram of a real workflow comes from the compiler (`openstategraph graph`),
  not from the agent's imagination. Hand-drawn sketches are for proposals
  only, before anything exists.
- **It will not force an install past your pins.** If your project pins
  LangGraph 0.x, the library install is refused and the agent explains that
  the developer tool still works from its own environment.

## Both doors

Everything above works two ways, and your agent picks whichever it has:

- **MCP** — the `openstategraph` server, registered by `init` in the config
  files for the four common agent setups. See [the MCP layer](mcp.md).
- **The command line** — every step has a verb. See
  [the `openstategraph` command](cli.md).

Same steps, same order, same board.
