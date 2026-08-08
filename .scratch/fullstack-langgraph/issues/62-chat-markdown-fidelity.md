Type: task
Status: resolved (2026-08-08)

## Question

User report: the chat window is not properly markdown-formatted. RichText
(GFM) landed for answers + HITL candidates (ticket 46), so audit what still
renders raw: streamed `thinking` tokens (deliberately preformatted — is that
the complaint?), activity lines, error blocks, tables mid-stream. Fix so
every model-authored surface renders markdown, with code blocks and tables
styled, while the raw-token stream stays legible during streaming.

## Resolution

Streaming keeps the raw `<pre>` token feed (legible mid-arrival); a settled turn re-renders thinking through RichText — every model-authored surface is now GFM.
