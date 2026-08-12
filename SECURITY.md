# Security

## Reporting a vulnerability

**Report privately, not in a public issue.** Use GitHub's private
vulnerability reporting (*Security → Report a vulnerability* on the
repository), or contact the maintainer directly using the address on the
latest commits. Include a description, the version or commit, and a
reproduction. You will get an acknowledgement; a fix and a public advisory
follow once there is something to disclose.

Please do not open a GitHub issue for a suspected vulnerability — an issue is
public from the moment it is filed, which is the one thing a disclosure
process exists to avoid. Ordinary bugs are welcome as issues.

## The threat model

OpenStateGraph is a local-first development tool. The backend binds to
`127.0.0.1` and ships with **authentication off**, so by default every caller
that can reach the port has full access — the server says so in its startup
log. Do not expose it to a network in that state.

Authentication exists, it is simply not the default: set
`OPENSTATEGRAPH_API_TOKEN` and every request needs
`Authorization: Bearer <token>`. That is the one-line fix, and
[`docs/deploying.md`](docs/deploying.md) has the whole story — the threat
model for a shared deployment, a committed reverse-proxy config, and why one
worker is a hard ceiling. [`docs/api.md`](docs/api.md) documents the header
from the client's side.

Known, documented trade-offs:

- Canvas-preview provider API keys are kept in browser `localStorage` and sent
  directly to the provider (stated in the credentials dialog). Use scoped,
  revocable keys.
- Capability discovery imports Python from `workflows/<slug>/` — opening a
  workflow executes its code. Only open workflows you trust.
- The prebuilt SQL tools open their database read-only (`mode=ro`), and the
  configured path is jailed to `workflows/` — a canvas field can never reach
  an arbitrary host file.
