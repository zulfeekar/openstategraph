Type: task
Status: open

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
