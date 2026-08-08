# Page Analytics

The full-capability reference workflow: page **views, revenue, falloff and
trends** over a six-table analytics database, with the finished report
emailed to a fixed recipient after human approval.

Built as the platform's own comprehensive test — it deliberately uses every
generic node type at once:

| Piece | Node types |
| --- | --- |
| Two entries | `input.text` (the question) + `input.markdown` (house style, fanned out to two agents) |
| Intent routing | `route.classifier` — full_report / quick_metric / database_deep_dive / industry_context |
| The report crew | `orchestrate.supervisor` + three `orchestrate.worker` archetypes (Traffic, Revenue, Trends) sharing the SQL Explorer bus; Trends also holds Web Search |
| Join + quality | `function.format_report` → `route.grader` (revise loop) → `human.approval` |
| Delivery | Report Dispatcher `agent.llm` bound to `tool.email-send` — recipient is **node config**, the model writes only subject and body; dry-run `.eml` to `workflows/_outbox/` unless SMTP is configured |
| One-shot branch | `agent.llm` metric answerer with summarization on, its own grader |
| Composition | `team.workflow` → `page-metrics-team`; `workflow.subgraph` → `research-team` |

## Data

`data/analytics.sqlite` — synthetic, deterministic (`scripts/generate_page_analytics.py`):
`pages`, `referrers`, `experiments`, `sessions`, `pageviews`, `revenue`,
with foreign keys as the JOIN rules. Falloff = exit rate by `pages.funnel_step`.

## Email

Without `OPENSTATEGRAPH_SMTP_HOST` the send is a **dry run**: the complete
RFC-5322 message lands in `workflows/_outbox/` and the dispatcher says so.
Set the `OPENSTATEGRAPH_SMTP_*` variables to deliver for real.
