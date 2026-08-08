Type: task
Status: resolved (2026-08-07)

## Question

`data/vgsales.csv` is 50 fabricated rows presented as the Kaggle VGChartz
dataset (row 1: NA_Sales == Global_Sales == 82.74; the real row is 41.49 /
82.74). The deep grader demands "specific numbers from the dataset", so the
demo would grade confidently against invented data.

Decide: fetch script mirroring `scripts/fetch_chinook.sh` (license: VGChartz
scrape, redistribution unclear — check before committing the real file) vs a
clearly-labelled synthetic dataset of realistic size (~1–5k rows, plausible
distributions, README note). Either way the file's provenance is stated in
the workflow's AGENTS.md and the grader criteria match reality.

## Resolution

Synthetic over unlicensed mirror: `scripts/generate_vgsales.py` (seed 41) writes 300 internally-consistent rows (Global = sum of regions), data dir labelled SYNTHETIC, tools smoke-tested against it.
