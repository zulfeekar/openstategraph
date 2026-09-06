# Product: token status bar

## Problem
"I ran this workflow a few times while fixing the prompt. How much did that
cost me? And how much did the whole project cost so far?" Today the only
number is one run's tokens, inside the run dock, gone when the next run
starts. There is no total for what I did in this tab, no total for the
project, no split by model, and I cannot tell how much was served from cache
versus paid in full.

## Success metric
Time to answer "what did this session cost, by model" drops from *not
possible* to *one glance*: the number is on screen at all times without
opening anything, and the per-model split is one click away. Measured by
the bar existing on every editor screen and the modal opening in one click
(a UI test), and by the numbers matching the run store to the token (a
backend test summing the same rows).

## Announcement — the blog post before the feature
The editor now shows what your work costs. A small bar along the bottom of
the screen keeps a running count of tokens: everything this project has ever
spent, how much of that was served from cache, and what this tab has spent
since you opened it. Click it and you get the breakdown — grand total by
model, this session by model, every past session in a list. Nothing to
configure and nothing new to run: the numbers come from the runs you already
made. Where a provider does not report a figure, the bar says so instead of
showing a zero.

## Screens
- `mockups/status-bar.html` — the bottom bar at rest, and the modal open.
