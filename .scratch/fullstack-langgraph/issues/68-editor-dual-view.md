Type: grilling
Status: resolved (2026-08-08) — redefined by the user and built

## Question

Developers want to see the MAIN (concierge) workflow together with the
selected child in the builder. Options to grill: (a) breadcrumb drill-in
(ticket 56's deferred Team UX — open child, banner back to parent), (b) a
split canvas rendering parent + selected child side by side (two papers, one
controller each), (c) parent-with-expanded-subgraph rendering via the
compiled Mermaid (ticket 54's Graph tab shows xray=True — cheapest true
view). Recommend (a)+(c) first; (b) is a large canvas feature.

## Resolution

The user's actual meaning (clarified 2026-08-08): not an editor split-canvas — a **live flow view in the customer chat**: while a workflow runs, show its compiled graph with the active node lit. Built: `/chat` gains a collapsible 'Live flow' panel — mermaid served from the repo's own node_modules (CDN-free), the compiled graph fetched per selected workflow, and non-internal stream frames highlight their node (same safe_name rule as the compiler). Live-verified: Chinook run with grader_sql glowing green mid-run, revise/pass edges visible. The editor split-canvas idea is retired — the compiled-graph overlay covers the developer case.
