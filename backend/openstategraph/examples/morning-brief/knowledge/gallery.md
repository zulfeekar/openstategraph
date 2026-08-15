Gallery — the twenty example workflows, how they are batched, and the rules every one of them obeys.

# The gallery

**Twenty** example packages, built in four batches of five: foundations, loops,
composition, real world. They are permanent — an example is never deleted, only
corrected — because each one is the recorded answer to "can the canvas express
this", and deleting it deletes the answer.

Every example obeys four rules:

1. It validates with zero tokens spent.
2. It has been **run**, and the run is recorded in its `AGENTS.md` with the date
   and the model.
3. Its expectation is written down before the run, and a run that misses it is
   recorded as a miss rather than quietly re-specified.
4. Every gap found on the way becomes a ticket, never an inline fix.

Nineteen of the twenty record their expectation as prose a reader judges. Only
one — the SQL example — can be graded by a machine, because the only fixture
format that exists compares SQL result sets.

The smoke budget for all twenty is roughly **65 000** tokens on the cloud model,
plus about 3 000 paid tokens for the single Anthropic synthesis step in the
YouTube example. That one step is the only place in the gallery where money is
spent per run.

See the release checklist (`release-checklist`), whose line 6 is what keeps
these twenty honest between releases.
