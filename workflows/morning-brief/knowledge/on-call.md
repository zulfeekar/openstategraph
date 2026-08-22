On-call rota — how the week is handed over, what counts as an escalation, and the response clocks.

# On-call

One person, **Tuesday 10:00 to Tuesday 10:00**, deliberately overlapping the
release tag so the person who inherits a release is on the rota when it lands.

## Clocks

| Severity | Acknowledge within | Update the thread every |
| --- | --- | --- |
| S1 — nobody can run a workflow | 15 minutes | 30 minutes |
| S2 — one provider or one surface is down | 1 hour | 4 hours |
| S3 — a wrong answer with a known workaround | next working day | daily |

An unacknowledged S1 escalates automatically to the previous week's on-call
after 15 minutes, never to a manager. The person who just came off the rota
has the most context and the least surprise.

## What is not an escalation

A third-party rate limit is **S3**, not S2, even when it looks total. The web
search atom is challenged by its upstream several times a month; the correct
response is to record the refusal and wait, and the tools already report it in
words rather than as an empty result.

## Handover

Three sentences in the rota thread, every Tuesday: what is still open, what you
changed while on the rota, and what you would look at first if it woke you up.
Handover is the only meeting the rota has, and it is written, not spoken.

See the release checklist (`release-checklist`) for what lands on the rota, and
the support desks (`support-desks`) for the boundary between a ticket and an
incident.
