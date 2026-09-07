Chinook Assistant (slug `chinook-assistant`) — the one visible example on this platform: a five-intent router in front of three destinations, answering questions about the Chinook music store, plus greetings, general knowledge and live web lookups. One document; nothing is mounted.

**What questions it answers**
- "Which genre earns the most revenue?" — routed to the SQL analyst, verified before it is returned.
- "How many albums did Iron Maiden release?" — same branch.
- "Hello / what can you do?" — answered directly, in one sentence.
- "Can you book me a flight?" — declined honestly, with what it *can* do.
- "Who wrote Bohemian Rhapsody?" — answered from the model's own knowledge.
- "What is the latest release from …?" — routed to a web search and fetch.

**Branches & capabilities (topology)**
- **`route.classifier`** with five intents: `data_query`, `greeting`, `off_topic`, `general_knowledge`, `web_lookup` (fallback `off_topic`).
- **`data_query`** → an `agent.llm` bound to `tool.chinook-get-all-tables`, `tool.chinook-get-schema` and `tool.chinook-execute-sql`, taking its rules from a wired `input.markdown` skill file (`sql-analyst.md`). Its answer goes to a `route.grader`, which passes it on or sends it back over `feedback` for another attempt — three at most.
- **`greeting` / `off_topic` / `general_knowledge`** → one tool-less agent. One model call, no database, no web.
- **`web_lookup`** → an agent bound to `tool.web-search` and `tool.web-fetch`, which searches, fetches and cites.
- **`output.formatted`** renders whichever branch ran as Markdown.

**When NOT to use**
- A question about another database — this one is wired to the Chinook sample file only.
- Anything that writes: this workflow has no write tool anywhere in it.

This workflow has its own second brain — route there for depth.
