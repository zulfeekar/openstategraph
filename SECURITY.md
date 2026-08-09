# Security

OpenStateGraph is a local-first development tool; the backend binds to localhost and
has no authentication. Do not expose it to a network as-is.

Known, documented trade-offs:
- Canvas-preview provider API keys are kept in browser `localStorage` and sent
  directly to the provider (stated in the credentials dialog). Use scoped,
  revocable keys.
- Capability discovery imports Python from `workflows/<slug>/` — opening a
  workflow executes its code. Only open workflows you trust.
- The prebuilt SQL tools open their database read-only (`mode=ro`), and the
  configured path is jailed to `workflows/` — a canvas field can never reach
  an arbitrary host file.

Report vulnerabilities via GitHub issues (or privately to the maintainer if
disclosure-sensitive).
