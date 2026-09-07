# Third-party notices

OpenStateGraph is distributed under the MIT License (see [`LICENSE`](LICENSE)).
It depends on, and in one case redistributes, third-party work under other
licences. This file lists the ones that carry an obligation or that are
load-bearing enough to name. It is not a machine-generated SBOM: transitive
dependencies are covered by their own packages' notices, which npm and pip
install alongside the code.

Licence fields below were read from the installed packages
(`node_modules/<pkg>/package.json`, `importlib.metadata`) at the versions
noted, not from memory.

---

## Copyleft / attribution-carrying — read these

### JointJS core — MPL-2.0

| Package | Version | Licence |
| --- | --- | --- |
| `@joint/core` | 4.3.1 | MPL-2.0 |
| `@joint/layout-directed-graph` | 4.3.0 | MPL-2.0 |

Copyright (c) client IO. Source: <https://github.com/clientIO/joint>

The Mozilla Public License 2.0 is a **file-level** copyleft. It requires that
the source of the MPL-licensed files themselves stays available under the MPL
if you modify and distribute them, and that this notice is preserved. It does
**not** extend to this repository's own MIT-licensed code, which merely uses
JointJS as a library. Full text: <https://www.mozilla.org/MPL/2.0/>

This repository does not modify JointJS. It uses the **open-source core only** —
no `@joint/plus` commercial package is used, which is why the editor scaffolding
(stencil, inspector, selection, snaplines, navigator, command manager) is
reimplemented here. See README's "What had to be rebuilt".

`@joint/layout-directed-graph` wraps **dagre** (`dagre` 0.8.5, MIT, copyright
(c) 2012–2014 Chris Pettitt), which is also a direct dependency here, together
with its own `graphlib` (2.1.8, MIT).

### Inter — SIL Open Font License 1.1

| Package | Version | Licence |
| --- | --- | --- |
| `@fontsource-variable/inter` | 5.3.0 | OFL-1.1 |

The Inter typeface is copyright (c) 2016 The Inter Project Authors
(<https://github.com/rsms/inter>), licensed under the SIL Open Font License,
Version 1.1: <https://openfontlicense.org>

The OFL permits bundling and redistribution with software. Its two live
conditions are that the font is not sold on its own, and that any *modified*
version is not distributed under the reserved name "Inter". This project ships
the font unmodified.

### Chinook sample database — MIT

The file `workflows/chinook-assistant/data/Chinook_Sqlite.sqlite` is
**redistributed in this repository**, not merely referenced. It is the Chinook
sample database, v1.4.5:

> Copyright (c) 2008-2017 Luis Rocha — <https://github.com/lerocha/chinook-database>
> Licensed under the MIT License.

It is sample data used by the `chinook-assistant` workflow and its tests. The
fetch script that refreshes it is [`scripts/fetch_chinook.sh`](scripts/fetch_chinook.sh).
This entry exists because a committed binary artefact carries its licence with
it — a comment inside a fetch script is not adequate attribution for a file
that ships in the tree.

---

## Permissive dependencies

Listed for completeness. All are MIT, BSD-3-Clause or Apache-2.0, and all
require only that their own copyright notice and licence text (shipped inside
each installed package) be preserved.

### Editor (npm)

| Package | Version | Licence |
| --- | --- | --- |
| `react`, `react-dom` | 19.2.8 | MIT |
| `react-markdown` | 10.1.0 | MIT |
| `remark-gfm` | 4.0.1 | MIT |
| `mermaid` | 11.16.1 | MIT |
| `dagre` | 0.8.5 | MIT |
| `graphlib` | 2.1.8 | MIT |
| `clsx` | 2.1.1 | MIT |
| `lucide-react` | 1.28.0 | ISC |
| `vite` | 8.x | MIT |
| `vitest`, `@vitest/coverage-v8` | 4.x | MIT |
| `eslint`, `typescript-eslint`, `prettier` | — | MIT |
| `@playwright/test` | 1.x | Apache-2.0 |
| `typescript` | 5.9.x | Apache-2.0 |

Vendor SDKs are dynamic imports loaded as separate chunks, so they cost nothing
for users who stay on Mock or Ollama: `@anthropic-ai/sdk` 0.115.0 (MIT) and
`openai` 7.3.0 (Apache-2.0).

### Runtime (PyPI)

| Package | Version | Licence |
| --- | --- | --- |
| `langgraph` | 1.2.10 | MIT |
| `langchain` | 1.3.14 | MIT |
| `langchain-core` | 1.5.3 | MIT |
| `langchain-ollama` / `-anthropic` / `-openai` | 1.x | MIT |
| `deepagents` | 0.7.5 | MIT |
| `fastapi` | 0.121.1 | MIT |
| `pydantic` | 2.13.4 | MIT |
| `uvicorn` | 0.38.0 | BSD-3-Clause |
| `duckdb` | 1.4.1 | MIT |
| `pandas` | 2.3.3 | BSD-3-Clause |

---

## Not a dependency: JointJS+

The JointJS+ *AI Workflow Builder* demo was the design reference for this
editor. No JointJS+ code, asset or licence key is present in this repository,
and none is required to build or run it.

## Reporting an omission

If something here is wrong, stale, or missing, open an issue. Notices are
checked when a dependency is added — see the Docs checklist in the pull
request template.
