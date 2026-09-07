Support tiers — the four contract tiers Northwind Robotics sells, and the first-response time each one buys.

**Business meaning**
A tier is a contractual promise about *first response*, never about resolution.
Every customer account carries exactly one tier, set at contract signature and
changeable only at renewal.

**The tiers**

| Tier | Name | First response | Hours covered |
|------|------|----------------|---------------|
| T0 | Foundry | 4 hours | Mon–Fri, 09:00–17:00 CET |
| T1 | Forge | 60 minutes | Mon–Fri, 07:00–19:00 CET |
| T2 | Furnace | 20 minutes | 7 days, 06:00–22:00 CET |
| T3 | Crucible | 5 minutes | 24/7 |

**Caveats**

- A ticket that arrives outside the tier's covered hours starts its clock at
  the next covered minute. Only Crucible has no such gap.
- The clock measures *first human response*, not the automated acknowledgement,
  which every tier receives within 30 seconds.
- A tier does not decide who works the ticket. That is `escalation-paths`.
- A ticket that becomes an incident stops being governed by this table and
  starts being governed by `incident-response`.
