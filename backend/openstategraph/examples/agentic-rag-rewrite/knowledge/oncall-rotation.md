On-call rotation — who holds which pager, for how long, and what the compensation is.

**Business meaning**
Three pagers exist and are always held by someone. A shift is a week, handed
over at 10:00 CET on Wednesday — deliberately mid-week, so a bad handover is
discovered while everyone is at their desk.

**The pagers**

| Pager | Held by | Shift length | Ack deadline |
|-------|---------|--------------|--------------|
| Primary | one engineer | 7 days | 5 minutes |
| Secondary | one engineer, different team | 7 days | 15 minutes |
| Duty Commander | one of six named leads | 14 days | 10 minutes |

**Rules**

- An unacknowledged page escalates to the next pager after the ack deadline,
  and to the Duty Commander after two hops.
- Nobody may hold Primary two shifts running.
- A handover is a written note in `#inc-live` listing every open incident and
  every ticket above rung 1.
- Compensation is a flat 1.5 days off per Primary or Secondary week, and 2 days
  per Duty Commander fortnight. It is not paid in cash.

**Caveats**

- Holding a pager does not make you the Incident Lead; see `incident-response`.
- The Secondary pager also works the Field Reliability queue, which is rung 2
  of `escalation-paths`.
