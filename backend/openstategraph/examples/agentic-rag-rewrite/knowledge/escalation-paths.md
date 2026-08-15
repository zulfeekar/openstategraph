Escalation paths — the three rungs a stuck piece of work climbs, and how long each rung may hold it.

**Business meaning**
Escalation moves *ownership*, never blame. Each rung has a hold time; when the
hold time expires the work climbs whether or not anyone asks it to.

**The rungs**

| Rung | Owner | Hold time | Reached by |
|------|-------|-----------|------------|
| 1 | Support Engineer | 90 minutes | every ticket, on arrival |
| 2 | Field Reliability | 4 hours | rung 1 expiring, or any hardware symptom |
| 3 | Duty Commander | no limit | rung 2 expiring, or any SEV-1 or SEV-2 |

**Rules**

- A rung may be skipped upward, never downward. Anyone may skip; nobody may
  return work to a lower rung once it has climbed.
- Hold times pause outside the customer's covered hours, except at rung 3.
- The Duty Commander is the only role that can stand down an incident, and the
  only rung with no time limit.
- Escalating a *ticket* does not raise its severity. Severity is
  `incident-response`; response time is `support-tiers`.

**Caveats**

- A customer cannot request a rung. They can request a callback, which is
  logged against the ticket and does not move ownership.
- Rung 2 is a team, not a person: the Field Reliability queue is worked by
  whoever holds the secondary pager (see `oncall-rotation`).
