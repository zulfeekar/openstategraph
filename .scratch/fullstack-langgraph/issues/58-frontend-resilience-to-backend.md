Type: task
Status: open
Blocked by:

## Question

Observed: the Workflows panel opened while the backend was briefly down
showed "No saved workflows yet" and kept that stale result until manually
closed and reopened; a stale tab reads as "stack is down". Fix: fetch-retry
with backoff + an inline "runtime unreachable — retry" state in the panel,
and a small topbar health dot driven by /api/health polling so the user can
tell a dead backend from an empty list at a glance.
