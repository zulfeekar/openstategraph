Type: task
Status: resolved (2026-08-08) — all four violations addressed

## Question

Brutal-honest verdict on "OOP is robust throughout": **true for the entity
ladders, false at the edges.** The ladders hold (I*→Abstract→Base→concrete
on router/grader/orchestrator/agent/tool, both languages; registries
everywhere; core/ clean). The violations, named:

1. **`api/main.py` — 971 lines, 42 defs, one `create_app` closure**: a god
   module. Endpoints, request models, model resolution, tool registry
   assembly and SSE framing share one file. Split: routers per concern
   (workflows, runs, chat, assets), a wiring module.
2. **`api/chat_page.py` — a 365-line HTML/JS string**: untestable,
   unlintable, no structure — the single biggest style violation in the
   repo. Make it a real static asset (templates/ dir served by FastAPI),
   testable with Playwright.
3. **`NodeRuntime.__init__` — 8 keyword params** and growing: parameter-
   object smell; the runtime's construction wants a `RuntimeContext`
   dataclass.
4. **`AskPanel.tsx` — 610 lines**: chat thread + streaming fold + canvas
   highlighting + approvals + trace tree in one component; extract the
   stream-fold hook (already the plan from ticket 55) and the trace tree.

## Resolution

1. `main.py` 973 → ~575: schemas / model_resolution / registries / streaming split out, test-facing names re-exported (ruff's unused-import fix ate one re-export — pinned with noqa). 2. `chat_page` is a real `static/chat.html` asset. 3. `RuntimeServices` frozen dataclass — new capabilities land once; kwargs remain the test-facing surface; both production sites + the child clone use services. 4. `AskPanel` 610 → 524 with `traceTree.tsx` (101) owning the trace record/model/export; the stream-fold hook extraction remains the recorded follow-up for the /chat-shared client (ticket 55's note).
