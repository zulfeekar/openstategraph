Store Analytics (slug `page-analytics`) — the comprehensive reference workflow: configurable music-store analytics reports (full report, quick metric, team deep dive, or a precise SQL answer) over the shared Chinook database, with human approval and email delivery.

**What questions it answers**
- "Send me the full store-analytics report."
- "Which genre earns the most revenue?"
- "Who are our top customers, and which countries buy most?"
- "How are monthly invoice totals trending?"
- "Dig through the store database and find anything unusual." (team deep dive)

**Branches & capabilities**
- **Intent routing (`route.classifier`)** selects one of: `full_report`, `quick_metric`, `database_deep_dive`, `sql_specialist`, or the fallback `conversation`.
- **Full report** orchestrates a supervisor and three workers (Sales, Customer, Trends) sharing the generic SQL Explorer bus over `chinook-nl-to-sql/data/Chinook_Sqlite.sqlite`; the Trends worker can also invoke web search.
- **Quick metric** is a single LLM agent with summarization on, behind its own grader.
- **Database deep dive** mounts the `chinook-metrics-team` Team package.
- **SQL specialist** mounts the focused `chinook-nl-to-sql` workflow as a subgraph — deep single SQL questions are real reuse of the other example.
- **Report assembly**: `function.format_report` → `route.grader` → `human.approval`; delivery via an agent bound to `tool.email-send` (dry-run `.eml` to `workflows/_outbox/` without SMTP config).

**When NOT to use**
- Questions outside the Chinook music-store data (weather, news, other databases).
- A single precise SQL question with no report framing — route straight to `chinook-nl-to-sql`.
- Real-time or streaming data; the workflow reads a static SQLite snapshot.
