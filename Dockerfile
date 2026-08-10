# OpenStateGraph — one image, two build stages, a thin runtime.
#
# The image mirrors the *repo layout* under /app rather than pip-installing the
# backend package. That is deliberate, not laziness: two runtime lookups are
# relative to the repo root and would break inside site-packages —
#   * workflow_store.py:  _REPO_ROOT = Path(__file__).resolve().parents[3]
#                         -> DEFAULT_WORKFLOWS_ROOT = <root>/workflows
#   * main.py /chat/mermaid.js: <root>/node_modules/mermaid/dist/mermaid.min.js
# so the container sets PYTHONPATH=/app/backend exactly as scripts/dev.sh does
# on the host, and /app is the "repo root" the code expects.
#
# Everything here is host-path free (no absolute host paths, no bind-mount
# assumptions) so the build behaves identically on macOS, Windows and Linux.

# ---------------------------------------------------------------------------
# Stage 1 — frontend build. Produces /app/dist (the editor SPA).
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app

# package*.json first so the dependency layer caches across source edits.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts index.html ./
COPY src ./src
# Not decoration: `npm run build` runs `tsc -b`, which typechecks the test files
# too, and src/nodes/tools/PlatformToolsNode.test.ts imports
# ../../../workflows/concierge/workflow.json. Without this the build fails with
# TS2307. Small (~2.4MB) and this stage is discarded anyway.
COPY workflows ./workflows

# `npm run build` is `tsc -b && vite build` — a type error fails the image
# build, which is the behaviour we want.
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — python dependency build. Produces a self-contained /install prefix.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS pydeps
WORKDIR /build

# Compilers live only in this stage and are thrown away with it. Present so a
# dependency without a prebuilt wheel for the target arch still installs
# instead of failing the build on arm64 Macs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./pyproject.toml

# Install the backend's *dependencies* but not the backend package itself.
# pyproject.toml stays the single source of truth — the list is read out of it
# with tomllib rather than duplicated into a requirements.txt that would drift.
#
# The core is lean by design, so the image must also take the extras: this
# container serves the HTTP API and the MCP transport and runs deep agents, i.e.
# everything `[all]` names. `all` itself is skipped because it is a
# self-reference (`openstategraph[...]`) and the package is not installed here;
# the concrete requirements are read from the other extras directly.
RUN python -c "import tomllib,pathlib; \
d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); \
p=d['project']; \
extras=[r for name,rs in p.get('optional-dependencies',{}).items() \
        if name not in ('all','dev') for r in rs]; \
pathlib.Path('requirements.txt').write_text('\n'.join(p['dependencies']+extras)+'\n')" \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 3 — the runtime image. Python slim + runtime deps + dist + backend +
# workflows. No node, no npm, no node_modules (bar one file), no compilers.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # The same two roots scripts/dev.sh exports on the host. The chinook entry
    # is the path shim pytest.ini documents for that workflow's tools package.
    PYTHONPATH=/app/backend:/app/workflows/chinook-nl-to-sql \
    # Read by the guarded block at the end of api/main.py: mounts the built
    # SPA at / so the editor is served by the backend itself. Off by default,
    # so a host-run backend is completely unaffected by its presence.
    OPENSTATEGRAPH_SERVE_STATIC=1 \
    OPENSTATEGRAPH_STATIC_DIR=/app/dist

WORKDIR /app

COPY --from=pydeps /install /usr/local

COPY backend ./backend
COPY workflows ./workflows
COPY --from=frontend /app/dist ./dist
# The /chat page serves mermaid from the repo's own node_modules so it stays
# CDN-free (main.py: chat_mermaid_asset). One file, ~3MB — not the 183MB tree.
COPY --from=frontend /app/node_modules/mermaid/dist/mermaid.min.js \
     ./node_modules/mermaid/dist/mermaid.min.js

# Non-root. `workflows/` must be writable at runtime (the editor creates and
# saves workflows through WorkflowStore), so it is chowned explicitly. When
# docker-compose bind-mounts ./workflows over this, Docker Desktop on macOS and
# Windows presents the mount world-writable, so the uid does not matter there;
# on native Linux the host directory must be writable by uid 10001 (or run the
# container with `user: root` if that is inconvenient).
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4).status==200 else 1)"

# ONE worker, on purpose — not a placeholder to be tuned up later.
#
# Ticket 05 fixed the durability half: the human-in-the-loop checkpointer is no
# longer a module-level InMemorySaver. It is a SqliteSaver on
# <workflows root>/.openstategraph/checkpoints.sqlite (WorkflowServices owns
# it; OPENSTATEGRAPH_CHECKPOINT_PATH moves it), so a paused approval survives a
# container restart PROVIDED the workflows directory is a volume — the same
# bind mount docker-compose already needs for the editor to save workflows.
# The container logs which one it got at startup: "approvals persist at X", or
# "approvals are in-memory and will NOT survive a restart".
#
# It did NOT fix the concurrency half, and the honest ceiling is still one.
# langgraph-checkpoint-sqlite's SqliteSaver documents itself as "meant for
# lightweight, synchronous use cases (demos and small projects) and does not
# scale to multiple threads"; its only serialisation is a threading.Lock held
# per instance, which two OS processes do not share. Same story for the
# long-term memory SqliteStore. Two workers would not lose the thread any more
# — both can read the file — but they would race each other's writes with no
# coordination, which is a worse failure than the one we just fixed because it
# is silent. Scaling past one worker means PostgresSaver + PostgresStore
# dropped into those same two seams (WorkflowServices takes both by argument).
CMD ["uvicorn", "openstategraph.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
