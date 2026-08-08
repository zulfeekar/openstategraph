Type: task
Status: open
Blocked by:

## Question

Observed: on a python.org macOS install, every live API tool fails with
CERTIFICATE_VERIFY_FAILED unless SSL_CERT_FILE is exported by hand (the
uvicorn launch now does this, fragile). Fix in code: the HTTP helper in
`workflows/open-api-explorer/tools/openapis.py` (and any future fetcher)
builds its ssl context from `certifi.where()` when available; certifi is
declared as a backend dependency. One test: the context resolves without
env vars.
