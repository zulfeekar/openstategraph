Storage tiers — the three vaults a seed lot can live in, and the conditions each one holds.

**Business meaning**
A tier is a promise about *how long a lot stays alive without intervention*.
Moving a lot between tiers is a decision about cost, not about the seed: every
tier is safe, and only the cheapest one is short-lived.

**The tiers**

| Tier | Name | Temperature | Relative humidity | Expected shelf life |
|------|------|-------------|-------------------|---------------------|
| 1 | Working Store | +4 °C | 35 % | 3 years |
| 2 | Base Vault | −18 °C | 20 % | 40 years |
| 3 | Deep Vault | −40 °C | 12 % | 180 years |

**Rules**

- Every accession enters at Tier 1 and stays there until its first viability
  test clears (`viability-testing`). Nothing is admitted directly to Tier 3.
- A lot may be promoted one tier at a time. Skipping a tier is refused by the
  registry, because the drying step between Tier 1 and Tier 2 has no equivalent
  between Tier 1 and Tier 3.
- Demotion is allowed in one case only: a lot scheduled for withdrawal within
  the next 90 days (`withdrawals`) may be dropped to Tier 1 so the thaw is not
  paid for twice.
- A tier's conditions are logged every 15 minutes. Two consecutive readings
  outside the band open an incident and freeze all withdrawals from that vault
  until a Curator clears it.
- Tier 3 holds no lot that lacks a safety duplicate (`duplication`). The
  registry refuses the promotion rather than warning about it.
