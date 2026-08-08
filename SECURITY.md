# Security

Dyflow is a local-first development tool; the backend binds to localhost and
has no authentication. Do not expose it to a network as-is.

Known, documented trade-offs:
- Canvas-preview provider API keys are kept in browser `localStorage` and sent
  directly to the provider (stated in the credentials dialog). Use scoped,
  revocable keys.
- Capability discovery imports Python from `workflows/<slug>/` — opening a
  workflow executes its code. Only open workflows you trust.
- The code-workshop tools are jailed to their workflow's scratch directory and
  never invoke `gh` without explicit opt-in plus human approval.

Report vulnerabilities via GitHub issues (or privately to the maintainer if
disclosure-sensitive).
