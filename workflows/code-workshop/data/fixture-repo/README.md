# stats-toolkit (fixture)

A deliberately tiny Python project used as the Code Workshop workflow's
sandbox. It ships with **one seeded failing test**: `median()` mishandles
even-length lists (it returns the upper-middle element instead of the mean
of the two middle elements). The workflow's coder agent is expected to find
and fix exactly that.

Run the tests from this directory:

    python -m pytest

This copy under `data/` is the pristine template — the workshop-reset tool
copies it into the workflow's `scratch/` jail and initialises an isolated
git repository there. Nothing in here is ever edited in place.
