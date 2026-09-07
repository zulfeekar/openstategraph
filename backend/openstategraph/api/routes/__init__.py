"""The HTTP surface, grouped by the subject each route already names.

`api/main.py` was 1903 lines with all thirty-two handlers defined inside
`create_app()` as closures over its locals, so none could be imported, tested
or mounted without constructing the entire application
(reviews-2026-08-14 ticket 15).

The grouping here is not invented — it is the one the URLs already declare,
and the one every client already treats as separate surfaces. Nineteen of the
thirty-two are `/api/workflows`, which is why "one module that grew" was never
the right description: it was several modules that had not been separated.

Each router is included by `create_app` and reaches the app's assembly through
`api/deps.Services` rather than through a closure.
"""
