chinook-metrics-team — a mountable Team package (supervisor + generalist worker + grader) that explores the shared Chinook music-store database with the generic SQL Explorer tools and loops until its grader passes.

**What it is for**
- Open-ended, multi-step exploration of the Chinook database, split into subtasks by its supervisor.
- Mounted by Store Analytics' `database_deep_dive` branch; mountable from any workflow via a Team node with slug `chinook-metrics-team`.

**Outcome contract (its grader)**
- Every figure comes from a SQL tool result against the Chinook database, table named.
- JOINs follow the schema's declared foreign keys.
- Answers involving dates state the invoice date range covered.

**When NOT to use**
- A single precise SQL question — use `chinook-nl-to-sql` directly.
- Anything outside the Chinook data.
