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
  credential — set …*, one line from an exception this package defines, or
  this codebase's own sentence about a run failure the patrol recorded.
  There is no constructor that takes free text, so a model's answer cannot
  become a refusal.

## Which refusals you can report, and which are your install's own

The question `team-board-and-gap-reports/15` settled, because both answers were
defensible and only one of them is true:

| What refused | Reportable | Why |
| --- | --- | --- |
| A node type this runtime has no implementation for | yes | the archetypal platform gap: a type the editor offers and the backend cannot run |
| A provider this install cannot build a client for | yes | the spec's own sentence names a variable, never a value |
| A run whose every tool call was refused, or a node that failed after retries | **yes, as structure** | the tool **type** that could not be reached is ours to fix or to document; the driver's sentence is not ours to publish |
| A repeated call, or a tool that answered two ways | no | real cost and worth fixing, but it is this install's own waste, not a gap in the platform |
| Anything you typed onto a card yourself | no | a card somebody wrote is a person's account, and the hand-written form is the right artifact for it |

The third row is the one worth reading twice. A warehouse refusing your login
**is** worth telling us about — which tool type, which check noticed, and Azure
AD's own error code when it supplied one — and the sentence the driver wrote is
**not** sent. `ToolResult.failure` carries whatever the tool was handed: an ODBC
message, a vendor's prose, and, when arguments would not parse, the model's own
arguments echoed back. So the words in the report are ours, with one exception
that is still ours — an exception line naming a class `openstategraph.errors`
defines, which is what a tool of ours raising put there.

That is why `openstategraph report <card-id>` works for a card the patrol filed
and refuses a card you typed by name. The card records the finding, not the
prose; the door rebuilds the report from the finding and validates every field
of it again, so a row edited by hand is refused rather than sent.

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

## Where it goes — the two doors

The schema exists so that both doors send the same thing. **Nothing in this
package sends anything on its own** — there is no timer and no background
sender, and every send below is a thing you asked for in the same breath.

1. **An issue under your own GitHub login** — `openstategraph report`, the
   primary door (`team-board-and-gap-reports/08`):

   ```bash
   openstategraph report tool.reddit-search        # prints the whole report, sends nothing
   openstategraph report tool.reddit-search --yes  # files it, as you
   ```

   The subject is the **type id the refusal named**. The first form prints the
   complete payload — the block above, plus the issue exactly as it would be
   filed — and stops; the second hands it to the GitHub CLI, which files it on
   `.github/ISSUE_TEMPLATE/platform-gap.yml`, whose boxes are exactly this
   schema's fields, asserted against it rather than transcribed from it
   (`team-board-and-gap-reports/05`). The issue is **yours**: your account,
   your issue, yours to edit, close and follow, and it is copied onto the
   maintainers' board and told what shipped when it closes.

   No credential of ours is anywhere in it. `gh` carries yours, we carry none,
   and the subprocess is handed nothing but the issue you just read. An install
   with no `gh`, or a `gh` nobody has logged in, prints the report and the
   form's URL and says `gh auth login` — a refusal with a next step, never a
   traceback. Filling the form in by hand, box by box, lands the same way.

   The command line is the whole of this door, deliberately: filing a public
   issue under your login is the kind of write `docs/decisions/mcp-layer.md`
   keeps behind a person, so there is no MCP tool for it.
2. **A keyless door, for an install with no `gh`.** Described in full below.

## The keyless door

A container, a CI job, a company that does not use GitHub: no `gh`, no GitHub
account, and the first door is unreachable. The second one needs neither — it
is a plain HTTPS POST of the JSON above to a URL, with no credential of any
kind, because there is nothing here for you to hold.

**It does not exist on your install until you name it.** One environment
variable:

```
OPENSTATEGRAPH_REPORT_ENDPOINT=https://<the maintainers' function>
```

Unset — which is how every install starts, and how most will stay — means the
door is not there. There is no default URL in this package, in any build, in
any release; grep the wheel and you will not find one, and a test
(`team-board-and-gap-reports/09`) fails the day somebody adds one. That is the
same rule this project applies to every vendor it reaches: never reach one
without naming a variable you can set, see and revoke. It is also the whole
opt-out. There is no setting to turn off, because with the variable unset there
is nothing on.

Sending is still per report and still after you have read it:

```python
from openstategraph.gap_report_client import endpoint, send

shown = report.render()   # the block above — read it
print(shown)
answer = send(report, endpoint(), shown=shown)   # only if you say so
```

`send` refuses to post unless the text you pass is exactly what this report
renders, so nothing can show you one report and send another. The answer is
either `Accepted(outcome, count)` — `count` being how many times this same gap
has now been reported from this install, because repeats are one card with a
count rather than a hundred cards — or `Refused(status, reason)`, where the
reason is one of the door's own fixed words (`rate-limited`, `too-large`,
`not-json`, …) and never anything derived from what you sent.

### What the far side does with it

Worth knowing, because a door you cannot see is a door you have to trust:

- It is **public by declaration** — no authentication, because a reporting
  install holds no credential of ours and issuing one to every install would be
  a worse problem than the one it solves.
- It **refuses by length before it parses**, so an oversized body costs a
  length check.
- It is **tolerant in reading and strict in trusting**: a field it does not
  know is dropped rather than refused, so an older or newer client still gets
  through, and nothing outside the allowlist ever reaches the database.
- It **rate-limits by your hashed project id**, and **deduplicates by the
  finding hash** — one card, a count.
- It **logs nothing from the body**. Counts, outcomes and reject reasons only,
  not even on an error path.
- It has a **kill switch** its maintainers can throw without a deploy, which is
  the honest answer to "what if this ever misbehaves".

Until something calls it for you, the report object is still useful for the
thing it was built for: it is the definition of what *would* be sent, checkable
now, so that neither door can invent a payload of its own later.
