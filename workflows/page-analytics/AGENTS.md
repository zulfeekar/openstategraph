# Store Analytics

The full-capability reference workflow: **revenue by genre, revenue by
country, top customers and invoice trends** over the shared Chinook
music-store database, with the finished report emailed to a fixed recipient
after human approval.

Built as the platform's own comprehensive test — it deliberately uses every
generic node type at once:

| Piece | Node types |
| --- | --- |
| Two entries | `input.text` (the question) + `input.markdown` (house style, fanned out to two agents) |
| Intent routing | `route.classifier` — five branches, `conversation` being the fallback. Each one owns a different downstream shape (see below) |
| The report crew | `orchestrate.supervisor` + three `orchestrate.worker` archetypes (Sales, Customer, Trends) sharing the SQL Explorer bus; Trends also holds Web Search |
| Join + quality | `function.format_report` → `route.grader` (revise loop) → `human.approval` |
| Delivery | Report Dispatcher `agent.llm` bound to `tool.email-send` — recipient is **node config**, the model writes only subject and body; dry-run `.eml` to `workflows/_outbox/` unless SMTP is configured |
| One-shot branch | `agent.llm` metric answerer with summarization on (`summarize: true`), its own grader |
| Conversation branch | Analytics Concierge `agent.llm` + its own grader — follow-ups ("how did you get that") and meta questions, answered from history rather than a new query |
| Composition | `team.workflow` → `chinook-metrics-team`; `workflow.subgraph` → `chinook-nl-to-sql` — real reuse, not a demo prop |

Where each branch goes:

| Branch | Downstream |
| --- | --- |
| `full_report` | supervisor → three workers → format → grader → approval → email dispatcher |
| `quick_metric` | Metric Answerer + grader |
| `database_deep_dive` | the mounted `chinook-metrics-team` Team |
| `sql_specialist` | the mounted `chinook-nl-to-sql` subgraph |
| `conversation` (fallback) | Analytics Concierge + grader |

## Data — one database, one source of truth

There is **one** sample database in this repository:
`chinook-nl-to-sql/data/Chinook_Sqlite.sqlite` (the standard Chinook
music store: Artist, Album, Track, Genre, MediaType, Customer, Invoice,
InvoiceLine, Playlist, Employee, with foreign keys as the JOIN rules).
Both examples — this comprehensive one and the focused `chinook-nl-to-sql`
— evaluate against it. The generic `tool.sql-*` nodes here point at it by
path; the focused workflow binds its own Chinook-specific tools.

## Email

Without `OPENSTATEGRAPH_SMTP_HOST` the send is a **dry run**: the complete
RFC-5322 message lands in `workflows/_outbox/` and the dispatcher says so.
Set the `OPENSTATEGRAPH_SMTP_*` variables to deliver for real.
