# Open API Explorer (supervisor + per-source worker archetypes)

An OpenStateGraph workflow. `workflow.json` is the source of truth — edit through the editor.

- **Pattern**: supervisor labels each subtask with a worker archetype (hybrid
  routing, ticket 37) — Weather (Open-Meteo, default), Countries (World Bank),
  Knowledge (Wikipedia REST), Quakes (USGS). All keyless public APIs.
- **Run it**: open `open-api-explorer` in the editor and use Chat, or POST the
  document to `/api/runs/stream` with `workflow_slug: open-api-explorer`.
- **Tools** live in `tools/openapis.py`; tests in `tests/` run offline against
  recorded fixtures (`pytest -m live` for one real request per API family).
