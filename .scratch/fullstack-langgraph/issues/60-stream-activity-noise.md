Type: task
Status: open
Blocked by:

## Question

Observed in live runs: the SSE `updates` stream (and thus the chat activity
feed) interleaves internal frames — `model`, `tools`,
`SummarizationMiddleware.before_model` — with real canvas node ids, and the
Team run reported `attempts: 0` because a child subgraph's attempts never
propagate to the parent. Fix: filter/namespace non-canvas frames server-side
(map them to their owning node id so the node still lights up, without fake
node names in the feed), and surface a child workflow's attempt count in the
parent's outputs. Also fold in the recorded warning-collapse item (7
"can loop back" diagnostics for one loop -> one per-loop notice).
