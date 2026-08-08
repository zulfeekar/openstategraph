Type: task
Status: resolved (2026-08-08) — generated, wired, scheduled

## Question

Integrate **OpenWiki** (langchain-ai/openwiki — docs-verified, not assumed):
a CLI that writes and maintains a Markdown wiki (`openwiki/`, Google OKF
v0.1 format) for a codebase or personal knowledge, with **agents as the
primary audience** — discovered through AGENTS.md, refreshable from CI with
an auto-PR when content changes.

Why it snaps into Dyflow with almost no new code:
1. **The concierge already reads it.** `platform_ls/read/grep` are jailed to
   the repo — a generated `openwiki/` directory is instantly inside the
   root assistant's readable area. "How does X work?" answers move from raw
   grep over source to a *curated, maintained* wiki. One prompt line points
   the agent at `openwiki/index.md` first.
2. **It IS the SSOT the 6-tables scenario wanted.** The user's original "it
   can be a table or it can be openwiki" resolves: business definitions and
   JOIN conventions maintained as OKF concept pages (front matter, linked
   concepts), refreshed by CI — the glossary question answered by the
   product built for it.
3. **Per-workflow knowledge**: an `openwiki/` bundle inside a workflow
   package slots beside `skills/` — skills = short standing instructions,
   wiki = deep reference the agent reads on demand (progressive disclosure,
   same philosophy as deepagents skills).

Build steps:
- `npm install -g openwiki` (or repo-local devDependency), provider via
  `openai-compatible` pointed at Ollama's OpenAI endpoint (no new keys), run
  `--init`, review the generated `openwiki/`, commit.
- Wire AGENTS.md/CLAUDE.md pointers per the code-mode docs; add one line to
  the concierge's system prompt ("consult openwiki/index.md first for
  how-does-this-work questions").
- Optional: the docs' CI example for scheduled refresh + PR.
- Later: `wiki_lookup` prebuilt tool (concept search over openwiki/ with
  front-matter citations) if raw read/grep proves too blunt.

## Resolution

Generated (user-approved Copilot provider): 13 OKF concept pages / 677 lines — compile seam, entity ladders, memory, package contract, ten-workflow catalogue, extending how-to, testing, quickstart. Wired: concierge prompt reads openwiki/index.md first for how-does-it-work questions (platform_read already reaches it); CLAUDE.md points coding agents at it; `.github/workflows/openwiki-update.yml` refreshes weekly and opens a PR only on change (openwiki installed globally in CI — local install collides with our React 19). Finding recorded: the Ollama openai-compat endpoint completes silently with an empty wiki — a hosted provider is required.
