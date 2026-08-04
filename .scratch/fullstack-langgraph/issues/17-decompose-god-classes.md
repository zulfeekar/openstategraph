Type: grilling
Status: open
Blocked by: 11

## Question

Decompose the two god classes, with tests in place first.

Measured, not asserted:
- `WorkflowController` — 38 public members, 540 lines, mixing node ops, edge ops, clipboard, grouping, selection, history and document I/O. Seven reasons to change.
- `WorkflowModel` — 41 public members, 451 lines, mixing node CRUD, edge CRUD, adjacency queries, topology, geometry and transactions.

CLAUDE.md now sets a ceiling of ~10 public members and one reason to change.

Decisions:
- The split for `WorkflowController`. Candidate seams: node ops, edge/connection ops, clipboard, grouping, history — with the controller reduced to a thin façade that *delegates* rather than implements. Is a façade even wanted, or should the view depend on the collaborators directly? A façade that only forwards is still a god class by another name.
- The split for `WorkflowModel`. The aggregate root legitimately owns node and edge mutation; the query surface (`topologicalOrder`, `bounds`, `descendantsOf`, `predecessorsOf`) arguably belongs in separate query objects. Decide whether the model keeps queries or exposes a read model.
- Ordering. This is a refactor of load-bearing code with no tests today, so it is blocked by 11 and must be done behind the regression tests named there.
- Whether the entity hierarchy (08) changes these shapes enough that this should wait for it.

Note: `PaperController` (11 members) and `ExecutionEngine` (6) are within budget and are not in scope.
