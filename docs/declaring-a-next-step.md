# Declaring a next step: what a refusal should say to do instead

Written 2026-08-29 for whoever owns an MCP server an OpenStateGraph workflow
calls. It is one field long. Companion to `declaring-a-table.md`, and it
exists because of one measured behaviour:

> **A model told to change its approach, with no destination in the message,
> has the same wrong moves available to it — so it makes them again.**

---

## The failure this closes, measured

A question asked about the catalogue **and** the playlists. Each is its own
lens and the SQL tool locks to one of them. The run received, alternately:

```
lock guard refused: SQL references tables outside the resolver lock set:
  ['playlists'] not in ['main.Invoice', 'main.InvoiceLine', ...]
Unknown lens 'main.Album'. Valid lenses: ['sales', 'catalog', ...]
```

The model then alternated between passing a *table* name as `lens` and passing
a table outside the lock set, three to five times per run, and stopped only
when the loop ended.

**The platform side of this is already done.** Both refusals travel as
`{"ok": false, "retryable": false, ...}`, and OpenStateGraph reads that pair:
it appends *"The service reported this call as not retryable: making the same
call again will fail the same way. Change the approach…"* to the tool result
the model sees. That is necessary and it is not sufficient. It says **do not
repeat this**; it cannot say **do this instead**, because only the service
knows.

And the service does know. Its own instructions already name the destination:
`mcp_skill_read("_cross_cutting/JOINS.md")`. Nothing routes the model there.

---

## The field

Put a `notes` list in the envelope you already return, top level, beside `ok`.
One entry, one kind:

```json
{
  "ok": false,
  "retryable": false,
  "error_code": "lock_violation",
  "message": "lock guard refused: SQL references tables outside the resolver lock set…",
  "notes": [
    {
      "kind": "next_step",
      "text": "This question spans two lenses. Read _cross_cutting/JOINS.md with mcp_skill_read, then run one statement per lens."
    }
  ]
}
```

That is the whole contract. It works today, in either carrier — the JSON text
of the result, or `structured_content` — with **no change on the
OpenStateGraph side**. The note reaches the model as `Next step: <text>`,
ahead of the platform's own sentence, and it never reaches a reader: a
`next_step` is addressed to the model, not published in an answer.

Three kinds are accepted (`next_step`, `substitution`, `source_choice`);
`next_step` is the one this document is about. `kind` is required even though
it looks defaultable — without it, any object carrying a `text` field would
become an instruction addressed to the model, and a stranger's payload is not
something to guess at. Anything else in the list is ignored rather than
rejected, so a `notes` field you already use for something else is safe: an
entry is believed only if it is an object naming one of the three kinds and
validating in full.

---

## What to write in it

**A destination, not an apology.** The `message` already says what went wrong.
This field says where to go, and it is worth exactly as much as it is
specific:

| Instead of | Write |
| --- | --- |
| "Try a different lens." | "`playlists` is not in this lock set. Call `mcp_resolve_lens` for it and run a second statement." |
| "Invalid lens." | "`main.Album` is a table, not a lens. Lens ids are `sales`, `catalog`, … — pass one of those." |
| "Read the docs." | "Read `_cross_cutting/JOINS.md` with `mcp_skill_read`." |

Name the tool the model should call next, and the argument. A model that can
see the tool and the argument takes the step; a model that is told to "change
approach" re-rolls the dice.

**One note, not a list of options.** The point is to end an alternation, and
three destinations restart it.
