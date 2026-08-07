Type: task
Status: resolved (2026-08-07) — ccd1959

## Question

Chat renders answers, thinking and HITL candidates in `<pre>` although
react-markdown + remark-gfm are installed and used in one node body. Every
workflow produces markdown tables; users see raw pipes.

One `<RichText>` component (fixed component map, no raw HTML, styled code
blocks/tables, theme-aware) used by: chat answers, thinking stream, approval
candidate, node runtime output bodies, tool descriptions in the palette.
Streaming-safe (partial markdown mustn't flicker badly). Keep `<pre>` for
genuinely preformatted content (logs).

## Resolution

RichText (GFM, no raw HTML, noopener links) renders chat answers + HITL candidates; thinking stays preformatted deliberately.
