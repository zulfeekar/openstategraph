Type: task
Status: resolved (2026-08-08)
Blocked by:

## Question

Observed: on a python.org macOS install, every live API tool fails with
CERTIFICATE_VERIFY_FAILED unless SSL_CERT_FILE is exported by hand (the
uvicorn launch now does this, fragile). Fix in code: the HTTP helper in
`workflows/open-api-explorer/tools/openapis.py` (and any future fetcher)
builds its ssl context from `certifi.where()` when available; certifi is
declared as a backend dependency. One test: the context resolves without
env vars.

## Resolution

default_fetch builds its ssl context from certifi.where() (import-safe fallback); certifi declared; live API suite passes with no env var.
