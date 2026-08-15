Viability testing — how often a lot is germination-tested, and the rate at which it must be regenerated.

**Business meaning**
A seed lot is not an object in a box; it is a population that dies slowly. The
test interval is how often we ask whether it is still alive, and the
regeneration threshold is the point at which storing it further is storing a
corpse.

**Test intervals, by tier**

| Tier | Name | Test interval | Sample size |
|------|------|---------------|-------------|
| 1 | Working Store | every 12 months | 100 seeds |
| 2 | Base Vault | every 5 years | 200 seeds |
| 3 | Deep Vault | every 20 years | 400 seeds |

**Thresholds**

| Germination rate | Verdict | What happens |
|------------------|---------|--------------|
| 85 % or above | healthy | nothing; the clock restarts |
| 70 % to 84 % | watch | interval halves until the next clear result |
| below 70 % | **regenerate** | the lot is grown out and re-accessioned |
| below 40 % | critical | regeneration is scheduled within 60 days |

**Rules**

- The first test happens 6 months after accession, whatever the tier. It is
  the only test that is not on the interval, and it is what gates promotion
  out of Tier 1 (`storage-tiers`).
- A regenerated lot is a **new accession** with a new lot id; the parent lot is
  retained at Tier 1 for one further year and then discarded.
- Sample seeds are drawn from the working sub-sample, never from the base
  collection. A test that consumed base-collection seed is a reportable error.
- A lot under a `watch` verdict may not be withdrawn (`withdrawals`) except by
  a Curator, and never for a distribution request.
