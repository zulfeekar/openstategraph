# Chinook NL-to-SQL

The focused example: natural language in, one SQL-backed answer out.

An `agent.llm` bound to three Chinook-specific tools (`tools/chinook.py`:
list tables → table schema → read-only query) behind a grader, over the
repository's **single sample database** —
`data/Chinook_Sqlite.sqlite`, the standard Chinook music store (Artist,
Album, Track, Genre, MediaType, Customer, Invoice, InvoiceLine, Playlist,
Employee).

That database is the single source of truth for every example: the
comprehensive `page-analytics` (Store Analytics) workflow and the
`chinook-metrics-team` Team package point their generic `tool.sql-*` nodes
at this same file, and Store Analytics mounts this workflow as a subgraph
for deep SQL questions.

- `tools/` — the Chinook tool family (`tool.chinook-get-all-tables`,
  `tool.chinook-get-schema`, `tool.chinook-execute-sql`), read-only by
  construction.
- `tests/` — the workflow's own pytest suite; `graph.py`/`agents.py` show
  the compiled output is plain Python that runs without the editor.
