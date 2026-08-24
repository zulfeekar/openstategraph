# {{name}}

An OpenStateGraph workflow package, scaffolded from the **minimal** template.

## What is in here

`workflow.json` is the source of truth — a document, not code. This one is
three nodes wide:

```
input.text → agent.llm → output.formatted
```

One model call per run. Nothing can reject the answer, so it works before you
have configured anything.

Everything else is discovered by convention, so an empty directory is not a
mistake — it is the place the next thing goes:

| Directory | What lands here |
| --- | --- |
| `tools/` | a `BaseTool` subclass per file; it becomes a node you can bind, placeable under `<this-package>/tools.<ClassName>` — `node_type` is an *optional* alias, not required |
| `functions/` | plain Python a `function.*` node calls |
| `middlewares/` | one slot per file, exposing `MIDDLEWARE` |
| `skills/` | `*.md` prompt context every agent in this package sees |
| `tests/` | `pytest` over the above — this is real code, so test it |
| `data/` | fixtures, databases, anything the tools read |

## Run it

```bash
openstategraph run . "your question here"
openstategraph validate .          # compile-check without spending a token
openstategraph graph .             # the compiled topology, as Mermaid text
```

## The obvious next step

1. **Give the agent a job.** Open the editor (`openstategraph serve`), select
   `agent1`, and write its system prompt.
2. **Wire a tool.** Drop a `BaseTool` subclass into `tools/`, reload the
   palette, and connect its `tool` port to the agent's `tools` bus. That is the
   whole extension mechanism — no engine code is edited.
3. **Publish it.** This package is a **draft** (`"published": false`). Publish
   from the editor's Workflows panel, or
   `POST /api/workflows/{{slug}}/publish`, to put it on the customer `/chat`
   surface.

When one agent stops being enough, `openstategraph new <slug> --template
routed-qa` shows the next shape: a router, and a grader that sends weak answers
back.
