Type: task
Status: open
Blocked by:

## Question

"Stack is down" keeps happening because both processes are started ad hoc in
throwaway terminals and die with them; nothing supervises or restarts them,
and the README's two-terminal incantation (PYTHONPATH=backend:workflows/...)
is hand-typed state. Fix: one `scripts/dev.sh` (or Procfile/launch config)
that starts uvicorn (with the right PYTHONPATH and SSL_CERT_FILE) + vite,
restarts on crash, and one `scripts/status.sh` that says what is up. The
PYTHONPATH chinook shim should die entirely — the capability loader already
imports workflows by file location.
