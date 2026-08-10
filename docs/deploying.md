# Deploying OpenStateGraph for other people

Everything else in these docs assumes the process is yours and the machine is
yours. This page is about the moment that stops being true: a teammate opens
the editor, a customer opens `/chat`, an MCP client connects from a laptop.

Two questions decide the whole deployment, and both used to be answered by a
sentence in a document. They are answered by the code now, and this page says
which is which.

---

## 1. The threat model, in three sentences

**An OpenStateGraph deployment with no authentication gives anyone who can
reach its port the same power the deployer has:** they can run arbitrary
workflows — any hosted one, and any document they compose themselves — read
every workflow file under the workflows root (`workflow.json`, tools, skills
and knowledge), spend the deployer's model budget without limit, and write
drafts to disk.
The provider API keys themselves never leave the server — the browser never
sees them, `/api/capabilities` reports only whether a key is *present*, and the
MCP layer exposes no credential tool at all — but that is a narrow consolation,
because an attacker who can run arbitrary workflows can spend those keys as
freely as you can. **The one-line fix: set `OPENSTATEGRAPH_API_TOKEN` to a long
random string, or put the process behind `deploy/Caddyfile`.**

What that does *not* cover, said plainly:

- **No per-user identity.** The token is one shared secret. Everyone who holds
  it is the same principal. There is no audit trail attributing an action to a
  person, and building authorization on top of the token would be building on
  sand — see "Not solved here" at the end.
- **No rate limiting or quota.** A holder of the token can start runs as fast
  as the models answer. Put a rate limit in the proxy (gap register SEC-02).
- **Nothing protects you from someone you gave the token to.** Publishing,
  deleting and credential entry are editor actions available to any
  authenticated caller.

---

## 2. Authentication: two supported answers

### A reverse proxy — the supported path for anything public

`deploy/Caddyfile` and `deploy/nginx.conf` are committed, and
`backend/tests/test_reverse_proxy.py` checks them against the app's real routes
on every CI run. They are not illustrations; they work.

```bash
openstategraph serve --host 127.0.0.1 --port 8000   # loopback only
caddy run --config deploy/Caddyfile                  # TLS + credentials
```

Both files carry the three things that are easy to get wrong and invisible
until a customer hits them:

| | Why it matters |
| --- | --- |
| Buffering off on the SSE routes | Otherwise a run's `update` frames pile up in the proxy and the editor's live node highlighting arrives in one lump at the end — indistinguishable from a frozen canvas. |
| A 24-hour read timeout on those routes | nginx's default is 60 seconds. A `human.approval` waits on a person; a run waits on a model. Sixty seconds severs both. |
| No compression on those routes | A compressor is a buffer. |

**Bind the app to loopback.** A proxy in front of a process listening on
`0.0.0.0` is decoration — the port is reachable around it. `serve` defaults to
`127.0.0.1` for exactly this reason, and prints a warning naming what you just
exposed if you override it without a token.

### The built-in shared token — the floor

The commonest deployment is not public: it is an MCP server or an
`openstategraph serve` on a laptop or a team VM, where there is no proxy and
there never will be one. "Configure a reverse proxy" is advice, and advice does
not stop the `--host 0.0.0.0` somebody types at six in the evening. So there is
a first-party option:

```bash
export OPENSTATEGRAPH_API_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
openstategraph serve --host 0.0.0.0
```

- **Off by default.** Unset means no gate, exactly as before. A first run must
  not require a secret.
- **Environment only, never `openstategraph.yaml`.** That file is committed and
  the config loader refuses to let a credential into it — which is what makes
  it safe to commit.
- **Two ways to present it, one secret.** Machines send
  `Authorization: Bearer <token>`. Browsers get a minimal `/login` form once
  and then carry an HttpOnly, `SameSite=Strict` session cookie, so the editor
  and `/chat` keep working unchanged. A security control that breaks the
  product is a security control that gets switched off.
- **`GET /api/health` stays open.** A liveness probe runs before anything has
  credentials, and a probe that 401s is an outage. It answers a fixed literal
  and reads no state.
- **The MCP `streamable-http` transport uses the same variable**, machine-only
  (no form — an MCP client cannot fill one in). `stdio` is deliberately not
  gated: the client is the process that spawned it, and a token on a pipe is
  theatre.

The two answers compose. Use the proxy for TLS, rate limiting and your
organisation's identity provider; use the token as the floor underneath it, so
a misconfigured proxy is a degraded deployment rather than an open one.

```bash
curl -H "Authorization: Bearer $OPENSTATEGRAPH_API_TOKEN" \
     http://localhost:8000/api/workflows
```

---

## 3. One worker, and it is refused rather than recommended

**`openstategraph` supports exactly one worker per state directory, and a
second one is refused at startup.** This used to be a note in five documents
and enforced nowhere, which meant the first person to type `--workers 4` got a
deployment that looked fine and corrupted a paused approval eventually.

Two independent things in the process are per-process:

1. **The checkpointer and the memory store.** `SqliteSaver` and `SqliteStore`
   serialise writes with a `threading.Lock` held per *instance*. Two OS
   processes do not share it, so two workers interleave writes to the same
   file with no error anywhere.
2. **The catalogue event fan-out** behind `GET /api/events` — an in-process
   queue. A workflow published on worker A never reaches a browser subscribed
   to worker B, so a customer's picker is silently missing rows.

Both halves have to be fixed together, and only the first one is shipped. So
the refusal is unconditional, and it happens two ways:

- `openstategraph serve --workers 2`, `WEB_CONCURRENCY`, `UVICORN_WORKERS` and
  `GUNICORN_WORKERS` are read and refused **before a socket is bound**.
- `uvicorn --workers 4` and `gunicorn -w 4` leave no trace in a child's
  environment, so the serving process takes an **exclusive OS lock** on
  `<state dir>/serve.lock`. The second process to try is refused by name.

**Scale by giving one worker more concurrency** — the endpoints are async and
a run's cost is model latency, not CPU — or by running several one-worker
instances with **separate state directories** (`OPENSTATEGRAPH_STATE_DIR`)
behind a session-affinity proxy, accepting that a thread paused on one instance
must be resumed on the same instance.

### Postgres: worth doing, and not the lift

```bash
pip install 'openstategraph[postgres]'
export OPENSTATEGRAPH_POSTGRES_URL="postgresql://osg:...@db.internal:5432/osg"
```

This moves checkpoints and long-term memory into a database your operations
team already backs up, replicates and restores, instead of a sqlite file whose
durability story is "do not lose the container". That is worth having on one
worker.

**It does not raise the worker ceiling**, and the refusal does not soften when
it is set. The event fan-out still has no cross-process transport — closing
that means Postgres `LISTEN`/`NOTIFY` or Redis behind
`CatalogueBroadcaster`'s existing `publish`/`subscribe` pair, which is real
work that has not been done. Shipping the checkpointer half alone and letting
people infer the rest is exactly the silent failure this decision exists to
avoid.

Precedence, most specific first:

| Setting | Effect |
| --- | --- |
| `OPENSTATEGRAPH_CHECKPOINT_PATH=memory` | No persistence at all. Deliberate opt-out; wins over everything. |
| `OPENSTATEGRAPH_CHECKPOINT_PATH=/path.sqlite` | That file. |
| `OPENSTATEGRAPH_POSTGRES_URL=...` | That database. |
| *(nothing)* | sqlite under `state_dir()`. |

The store follows the same shape with `OPENSTATEGRAPH_MEMORY_PATH` on top.
Unlike every other backend here, an unreachable Postgres **fails startup**
rather than degrading: nobody sets that variable by accident, and quietly
writing their approvals to a local file instead is a surprise discovered at
restore time.

---

## 4. A deployment checklist

```bash
# 1. State goes somewhere you back up, and somewhere writable.
export OPENSTATEGRAPH_STATE_DIR=/var/lib/openstategraph
# ...or a database:
# pip install 'openstategraph[postgres]'
# export OPENSTATEGRAPH_POSTGRES_URL=postgresql://...

# 2. Something authenticates. Pick at least one.
export OPENSTATEGRAPH_API_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"

# 3. Provider keys in the environment, never in openstategraph.yaml.
export ANTHROPIC_API_KEY=...

# 4. Loopback, one worker, proxy in front.
openstategraph serve --host 127.0.0.1 --port 8000
caddy run --config deploy/Caddyfile
```

Read the startup log. Three lines state what you actually got, and each of them
is there because the alternative was somebody finding out later:

```
approvals persist at /var/lib/openstategraph/checkpoints.sqlite
authentication: on — shared token from OPENSTATEGRAPH_API_TOKEN
editor  http://127.0.0.1:8000
```

## Not solved here

Stated so nobody infers otherwise from the presence of a login form:

- **Identity and per-user authorization.** One shared secret is not identity.
  Every holder is the same principal, and no draft, publish or run is
  attributed to a person.
- **Rate limiting, quotas and an audit log** (gap register SEC-02). A token
  holder can spend the model budget as fast as the providers answer. The proxy
  is the place to put a limit today.
- **Multi-tenancy.** One process serves one workflows directory. Per-tenant
  roots are not a feature.
- **A CLI run alongside a server.** The serve lock covers HTTP processes;
  `openstategraph run` and the stdio MCP server are not locked, because they
  are short-lived single writers and locking them would break running a
  workflow in one terminal while `serve` holds another. Two *servers* on one
  state directory is the hazard, and that is the one that is refused.
