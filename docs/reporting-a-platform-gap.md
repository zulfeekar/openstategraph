# Reporting a platform gap

You hit something this install could not do — a card the backend has no
implementation for, a provider it cannot build a client for, a door that said
no — and you are willing to tell the maintainers. This page is what such a
report contains, what it structurally cannot contain, and how you say yes to
sending one. It assumes you have run a workflow and seen a refusal.

This is the **automated** report: a fixed set of fields, assembled for you.
The hand-written kind — a reproduction, two values, a *done when* — is a
different artifact and lives in
[OpenStateGraph in a LangGraph codebase §6](openstategraph-in-a-langgraph-codebase.md#6-reporting-a-defect-or-a-gap).
Use that one when you can describe what should have happened. Use this one when
the platform simply refused and the refusal is the whole story.

## What is sent

The fields below, plus a hash derived from them. This is the complete list, and it is the
model's own field list rather than a copy of it — the schema is published at
[`gap-report.schema.json`](gap-report.schema.json), generated from
`openstategraph.gap_report.GapReport` and committed beside it.

| Field | What it is |
| --- | --- |
| `version` | the OpenStateGraph version this install runs |
| `kind` | which kind of gap — e.g. `no-backend`, `provider-not-configured` |
| `type_ids` | the node/tool **type ids** involved, e.g. `tool.reddit-search` |
| `door` | where you were standing: `api`, `mcp`, `cli`, `library`, `editor` |
| `refusal` | the refusal sentence — one this codebase wrote, never model output |
| `check` | the id of the check that noticed, when a check did |
| `traceback_line` | one line naming what was raised, with no frames under it |
| `os` | the system and its release, e.g. `Darwin 25.6.0` |
| `python` | the Python version |
| `project_hash` | a SHA-256 of this project's id — never the id itself |
| `aad_code` | Azure AD's own error code, when the refusal carried one |
| `finding_hash` | derived from the fields above, so one gap reported forty times is one card with a count |

## What is never sent

The document, prompts, the values you typed into fields, table names, your
question, file paths, environment values.

Not *"we don't send those"* — **they cannot be put in**. The report is a closed
Pydantic model: a field that is not on the list above is rejected rather than
ignored, the type-id fields take type ids and refuse anything shaped like a
path, a table name or a sentence, the check field takes only check ids this
codebase publishes, and paths are redacted out of the traceback line whichever
route it arrives by. A door that tries to attach your workflow gets an error,
not a send.

Two details worth knowing because they are the ones people ask about:

- **Type ids, never values.** `tool.mssql-query` says which card refused.
  `SELECT …`, the table it names and the answer it did not give are not in the
  report and have no field to be in.
- **The refusal is ours.** It is one of the sentences this codebase writes —
  the compiler's *no implementation for tool "…"*, a provider's *has no
  credential — set …*, or one line from an exception this package defines.
  There is no constructor that takes free text, so a model's answer cannot
  become a refusal.

## Seeing it before it goes

Every report renders as plain text, exactly as it will be sent, and the
rendering is derived from the model's own fields — so a field added later
cannot be sent unseen:

```text
This is the whole report. Nothing else is sent.

  version         0.3.0rc1
  kind            no-backend
  type_ids        tool.reddit-search
  door            editor
  refusal         source: runtime · text: No implementation for tool "tool.reddit-search" — the agent ran without it, so its answer may not be grounded in that data source.
  check           no-backend
  traceback_line  —
  os              Darwin 25.6.0
  python          3.13.9
  project_hash    2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881
  aad_code        —
  finding_hash    fa721b6a4c38
```

## Opt-in, per send

There is no setting to turn on, no *don't ask again*, and no stored consent.
You read the block above and you send that one report, or you do not. Nothing
about this is telemetry: there is no timer and no background sender, and the
module that builds a report has no network client in it at all — so no code
path can assemble one and dispatch it in the same breath.

## Where it goes — the two doors, neither walked yet

The schema exists so that both doors send the same thing. **Today nothing in
this package sends anything** — no code path assembles a report and dispatches
it. The first door's *landing place* now exists (the issue form below); what
does not exist is anything that walks through it on your behalf.

1. **An issue under your own GitHub login.** The primary door: your `gh`
   credentials, your account, the rendered text shown to you first, filed as an
   issue on the project's tracker. **The form it files into exists** —
   `.github/ISSUE_TEMPLATE/platform-gap.yml`, whose boxes are exactly this
   schema's fields, asserted against it rather than transcribed from it
   (`team-board-and-gap-reports/05`) — so you can file the report by hand
   today, box by box, and an issue filed that way is copied onto the
   maintainers' board and told what shipped when it closes. What is not built
   is the *automatic* door: nothing in this package fills that form in for you
   or opens a browser.
2. **A keyless door for an install with no `gh`.** A hosted function that
   accepts exactly this schema, drops unknown fields, and rate-limits by the
   hashed project id.

Until they land, the report object is still useful for the thing it was built
for: it is the definition of what *would* be sent, checkable now, so that
neither door can invent a payload of its own later.
