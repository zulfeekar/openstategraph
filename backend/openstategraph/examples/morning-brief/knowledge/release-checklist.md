Release checklist — everything that must be true before a version tag is pushed, and who signs each line off.

# Release checklist

A tag is cut on **Tuesdays only**, and never in the 48 hours before a public
holiday in the release engineer's own timezone.

Seven lines, in order. Each is signed off by the named role, and a line signed
by the person who wrote the change does not count.

| # | Line | Signed by |
| --- | --- | --- |
| 1 | The suite is green on a clean checkout — not on a warm cache | release engineer |
| 2 | The changelog section for this version names every user-visible change | author |
| 3 | No open ticket carries the `blocks-release` label | release engineer |
| 4 | The wheel installs into an empty virtualenv and its console entry runs | release engineer |
| 5 | The published contract file matches the generated one, byte for byte | reviewer |
| 6 | Every example package in the gallery still validates | reviewer |
| 7 | The previous release has been live for at least **six days** | release engineer |

Line 7 is the one people try to waive. It exists because the two worst
regressions this project has shipped were both found on day five by someone
who was not looking for them, and a release cadence faster than that discovers
nothing before it compounds.

A failed line is not a veto. The release engineer may proceed on lines 2, 3 and
6 with a written note in the release thread naming what was skipped and when it
will be finished; lines 1, 4, 5 and 7 have no waiver.

See also the on-call handover (`on-call`), because a tag on Tuesday hands the
first week of its life to whoever is on the rota.
