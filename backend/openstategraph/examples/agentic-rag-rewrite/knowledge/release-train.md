Release train — the fortnightly train that carries firmware to the fleet, and the two ways to catch it late.

**Business meaning**
Firmware ships on a fixed cadence, not when a change is ready. The train
departs every second Tuesday at 14:00 CET. A change that misses it waits for
the next one.

**The gates**

| Gate | Closes | Who signs |
|------|--------|-----------|
| Code freeze | Friday 17:00 CET, 4 days before departure | the change author |
| Fleet soak | Monday 09:00 CET, on 20 robots for 24 hours | Field Reliability |
| Departure | Tuesday 14:00 CET | Duty Commander |

**Catching a departed train**

1. **Hotfix train** — one extra departure, Thursday 14:00 CET, for a change
   that closes a SEV-1 or SEV-2 only. Needs the Duty Commander's signature and
   a soak of 4 hours rather than 24.
2. **Pinned rollout** — the change ships to named sites only, capped at 5% of
   the fleet, and rejoins the next scheduled train. Any Field Reliability
   engineer may sign this; it never needs the Duty Commander.

**Caveats**

- A rollback is not a train. It is an incident action and needs no gate; see
  `incident-response`.
- Missing code freeze by minutes is still missing it. There is no discretion at
  this gate, which is why it is four days ahead of departure and not one.
