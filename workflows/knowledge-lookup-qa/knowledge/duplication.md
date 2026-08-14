Duplication — the off-site safety copy every long-term lot must have before it is trusted to one building.

**Business meaning**
A duplicate is not a backup of a file; it is a second population in a second
place. The vault's own promise is that no single fire, flood or border closure
can end a taxon we hold.

**The three duplication states**

| State | Meaning | Where the copy sits |
|-------|---------|---------------------|
| `none` | one population, one building | — |
| `partner` | a copy at a named partner vault | inside the region |
| `black-box` | a sealed copy we cannot open ourselves | outside the region |

**Rules**

- Tier 3 promotion is refused for any lot in state `none` (`storage-tiers`).
- A `black-box` copy is sealed: the receiving vault may not test, distribute or
  even count it, and it is returned unopened on request. It therefore does not
  count as a viability record, and the parent lot is still tested on its own
  interval (`viability-testing`).
- The duplication ratio is 25 % of accessioned mass, with a floor of 200 seeds.
  A lot that cannot meet the floor is regenerated before it is duplicated, not
  after.
- Partner duplicates are reconciled annually. A partner that misses two
  consecutive reconciliations is downgraded to `none` in our registry, which
  demotes every Tier 3 lot relying on it.
- A repatriation withdrawal (`withdrawals`) may never be served from the
  duplicate; it is served from the parent lot or refused.
