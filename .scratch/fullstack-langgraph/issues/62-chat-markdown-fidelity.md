Type: task
Status: open — claimed 2026-08-08

## Question

User report: the chat window is not properly markdown-formatted. RichText
(GFM) landed for answers + HITL candidates (ticket 46), so audit what still
renders raw: streamed `thinking` tokens (deliberately preformatted — is that
the complaint?), activity lines, error blocks, tables mid-stream. Fix so
every model-authored surface renders markdown, with code blocks and tables
styled, while the raw-token stream stays legible during streaming.
