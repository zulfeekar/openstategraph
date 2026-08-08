Type: task
Status: resolved (2026-08-08)
Blocked by:

## Question

Observed: the Workflows panel opened while the backend was briefly down
showed "No saved workflows yet" and kept that stale result until manually
closed and reopened; a stale tab reads as "stack is down". Fix: fetch-retry
with backoff + an inline "runtime unreachable — retry" state in the panel,
and a small topbar health dot driven by /api/health polling so the user can
tell a dead backend from an empty list at a glance.

## Resolution

Panel keeps listError state with an inline Retry (stale 'no workflows' impossible); RuntimeHealthDot polls /api/health every 10s in the topbar (verified green live), tooltip names scripts/dev.sh.
