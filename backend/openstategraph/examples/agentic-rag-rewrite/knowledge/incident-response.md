Incident response — the five severities, who is paged for each, and the fixed cadence of updates.

**Business meaning**
An incident is a live loss of service. It is not a support ticket, and it is
not a bug report: those are governed by `support-tiers` and `release-train`
respectively. Any engineer may declare one; nobody needs permission.

**Severities**

| Severity | Meaning | Who is paged | Update cadence |
|----------|---------|--------------|----------------|
| SEV-1 | Fleet-wide loss of motion control | Primary on-call **and** the Duty Commander | every 15 minutes |
| SEV-2 | One customer site down | Primary on-call | every 30 minutes |
| SEV-3 | Degraded telemetry, robots still moving | Primary on-call, next business hour | every 2 hours |
| SEV-4 | Cosmetic or reporting-only | Nobody is paged; a ticket is filed | none |
| SEV-5 | Suspected, unconfirmed | Nobody is paged; the reporter watches for 1 hour | none |

**The fixed steps**

1. Declare in `#inc-live`. The declaration itself starts the clock.
2. The Duty Commander names an Incident Lead within 10 minutes for SEV-1 and
   SEV-2. The Incident Lead is never the person fixing it.
3. Mitigate before diagnosing. A rollback is always an acceptable first move.
4. Stand the incident down only when the Incident Lead says so.
5. A written review is due within 5 working days for SEV-1 and SEV-2.

**Caveats**

- Severity is set by observed impact, never by the customer's tier. A Foundry
  customer whose whole site is down is a SEV-2.
- Escalating a stalled incident is `escalation-paths`.
- Who is on the pager this week is `oncall-rotation`.
