Type: task
Status: open — claimed 2026-08-08

## Question

LangSmith-style trace: the flat activity feed should be a **tree** — run →
node → (namespace) child graph → model/tool steps — so a user sees what hit
what and why. The SSE stream already carries `namespace` per frame (and
ticket 60 filters internal frames from the flat feed; the tree is where they
belong, nested under their owning node). Include per-step duration + output
preview, collapse/expand, and **Export as tree JSON** (download of the
structured run). Feeds the customer client (ticket 64).
