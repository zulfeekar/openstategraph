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
sees them, `/api/providers` reports only whether a key is *present*, and the
MCP layer exposes no credential tool at all — but that is a narrow consolation,
because an attacker who can run arbitrary workflows can spend those keys as
freely as you can. **The one-line fix: set `OPENSTATEGRAPH_API_TOKEN` to a long
random string, or put the process behind `deploy/Caddyfile`.**

What that does *not* cover, said plainly:

- **No per-user identity.** The token is one shared secret. Everyone who holds
  it is the same principal. There is no audit trail attributing an action to a
  person, and building authorization on top of the token would be building on
  sand — see "Not solved here" at the end. Identity for *memory* is a separate,
  narrower question with an answer: §1b.
- **No rate limiting or quota.** A holder of the token can start runs as fast
  as the models answer. Put a rate limit in the proxy (gap register SEC-02).
- **Nothing protects you from someone you gave the token to.** Publishing,
  deleting and credential entry are editor actions available to any
  authenticated caller.

What it *does* cover, since it was probed and closed: a workflow's SQL tools
open their database `mode=ro`, and `mode=ro` describes **one file**. `ATTACH`
and `VACUUM INTO` carry their own mode, so one model-authored statement used to
copy a whole database to any absolute path the process could write. Every
read-only connection now installs a `set_authorizer` denying
`SQLITE_ATTACH`/`SQLITE_DETACH` (`backend/openstategraph/readonly_sqlite.py`,
`test_a_read_only_database_opens_no_second_file.py`) — denied by action, not by
path, so nothing here parses SQL.

---

## 1b. Identity, and what per-person memory needs before it works

Authentication answers *may this request happen*. Identity answers *on whose
behalf*, and they are not the same question — the shared token has exactly one
principal, so it cannot answer the second one at all.

This matters for one feature specifically: **long-term memory is namespaced per
person**. A workflow's `save_memory(scope="user")` writes into
`("memories", <who>)`, and `search_memory` reads it back.

**The server decides who, and there is no way for a client to say.** Until
2026-08-13 there was: `user_email` was a field on the run request, typed into a
box in `/chat`, and used unverified as that namespace key — so any caller could
read and write any person's memories by naming them. The field is gone, `/chat`
has no identity box, and sending `user_email` is now a `422`.

### Telling the deployment how to know who someone is

One environment variable, naming the header your authenticating proxy sets:

```bash
OPENSTATEGRAPH_PRINCIPAL_HEADER=X-Forwarded-Email
```

This is the shape §2's reverse-proxy path already assumes: oauth2-proxy,
Cloudflare Access or an ALB with OIDC terminates authentication and forwards
the verified identity as a header.

> **The proxy must strip any client-supplied copy of that header.** A header a
> client can also set is not identity — it is the same defect one layer out.

Until 2026-08-29 that sentence was the whole answer, and §2 four sections below
handed you a committed, CI-tested proxy config that did not do it. A deployer
who followed both sections of this page got exactly the arrangement the
sentence warns about. Both halves are fixed, and the fix is not a strip
directive — because it could not be one.

**Why not.** The header being stripped is named by *you*. Cloudflare Access
says `X-Forwarded-Email`, oauth2-proxy says `X-Auth-Request-Email`, an ALB says
whatever you configured. A config we ship can only strip a literal it knows, so
it would be wrong — silently — for everybody who chose a different name.

**So the strip is inverted.** Every proxy config here now *sets* one header
whose name is ours:

```
X-OpenStateGraph-Proxy: 1
```

- `deploy/nginx.conf` — `proxy_set_header X-OpenStateGraph-Proxy 1;` in **every**
  `location` that proxies (nginx does not inherit `proxy_set_header` into a
  location that sets its own, so it is written twice on purpose).
- `deploy/Caddyfile` — `header_up X-OpenStateGraph-Proxy 1` in **every**
  `reverse_proxy` block.

Setting overwrites, in both proxies, so a client's copy cannot survive the hop.
And **the app refuses to read the identity header unless that assertion is
present** — so the forged-identity request is refused whatever your header is
called, and the one thing you must get right is a line we wrote for you rather
than a string only you know.
`backend/tests/test_reverse_proxy.py::TestTheIdentityHeaderCannotBeClientSupplied`
fails if either file loses it.

**If your proxy is not one of ours**, add the equivalent line to it: one hop
must set `X-OpenStateGraph-Proxy` on every request it forwards, and — because
it is the outermost hop — it must be the one overwriting your identity header
too. Whatever terminates authentication is the only thing that can do that;
this application cannot see it, which is why it asks to be told.

**What a wrong configuration looks like.** Not silence. A request arriving with
your identity header and no assertion is a client naming itself, and the app
logs it once per process — naming your header, the assertion, and this
section — then identifies nobody. "The proxy stripped it" and "the client sent
it" used to be one indistinguishable output; they are two now.

### What happens when you do not set it

Nothing breaks, and nothing is silently wrong:

- `workflow`- and `app`-scoped memory work exactly as before — they are keyed
  on the workflow, not the person.
- `user`-scoped memory **does not bind**. `save_memory(scope="user")` tells the
  agent there is no identified user for this run and points it at
  `scope="workflow"` instead. It does not fall back to a shared bucket, which
  is what it used to do: one namespace holding every unidentified person's
  facts, while the tool described it to the model as "facts about this person".

A library caller embedding `openstategraph` **is** the server, so identity is
theirs to supply directly: `workflow.ask(question, user_email="ada@example.com")`.

## 1c. Whose API key pays, and why a browser cannot answer that here

The editor has a **Models and credentials** dialog. Keys pasted there live in
the browser, and every run request carries them — otherwise a developer who
pasted a key would still see "no model configured" from Chat.

A request credential is written into the server's `os.environ`, which is
**process-global and outlives the request**. Read together with the old rule —
*absent → fill, present → leave alone* — that means the first browser to send a
key on a server whose operator configured none does not merely run: it
**becomes the configuration**. From that moment every other caller's runs
authenticate as that person, every prompt and every customer question reaches
their vendor account under their logging and their organisation's data
agreement, and rotating their key or revoking their access to the machine
changes nothing until the process restarts.

**So the deployment decides, not the request.** A credential in a request body
is taken only when all three are true:

| | |
| --- | --- |
| no `OPENSTATEGRAPH_API_TOKEN` | a gate exists because more than one person calls this server |
| no `X-OpenStateGraph-Proxy` on the request | a proxy in front means the caller is on a network |
| the caller's address is loopback | otherwise they are on another machine |

That is a laptop, where the dialog is the point. Anywhere else the credentials
are **dropped**, with one `WARNING` per variable naming the variable — never
the value — and the run continues on the server's own environment. It is not
an error: a shared deployment whose operator *did* set a key was already
ignoring these values, and refusing the request would break a working server to
make a point. If the operator set nothing, the run fails with the usual message
naming the variable to export.

**On a shared deployment, put provider keys in the server's environment**
(checklist step 3 below). The dialog is a single-user convenience, and after
this it says so by behaving like one.

The one case the check cannot see: a loopback bind with no token, reached over
an SSH tunnel, presents as local because at the socket it *is*. That deployment
has no authentication of any kind — §1 is the part of it to fix first.

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

They also carry the identity assertion §1b describes — `X-OpenStateGraph-Proxy`,
set in every proxying block of both files. It costs nothing when you have not
set `OPENSTATEGRAPH_PRINCIPAL_HEADER`, and it is what makes per-person memory
safe when you have. Do not delete it as noise.

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
  credentials, and a probe that 401s is an outage. It opens no socket and no
  database: it reads environment variables, and — for the `editor_stale` field
  — takes two `stat` walks over a directory the process already sits in,
  returning `None` the moment there is no source tree to compare against, which
  is every installed wheel. **The editor reads it**: a chip beside the runtime
  dot in the toolbar says *Editor is stale* when the served bundle predates
  `src/`, and says nothing at all for the other two answers — `false` and
  `null` both render nothing, because a surface that reported "current" for a
  wheel that cannot tell would be making a claim the server declined to make.
  This said "a
  fixed literal": `model_configured` *was* the constant `True`, on the
  reasoning that Ollama was always available, which was itself the defect. It
  is now computed — true when any registered provider has the environment it
  needs — so a machine with nothing configured no longer reports ready
  (providers-and-credentials ticket 02). Still not a reachability check: a
  configured provider that is down is a different question, and one this
  endpoint has never answered.
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
  `<state dir>/serve.lock`. The second process to try is refused by name —
  and it is refused *before* `serve` prints its three URLs, not after. The
  lock is checked twice: a cheap, non-blocking check in `cmd_serve` itself,
  ahead of the socket bind, so the common case (a second `serve` started
  against an already-served state directory) never sees a URL it cannot
  reach; and the authoritative check in the FastAPI lifespan, which is what
  actually holds the lock for the life of the process, because that is where
  the checkpointer, the memory store and the `/api/events` fan-out are
  constructed (workflow-gallery ticket 40).

**Scale by giving one worker more concurrency** — the endpoints are async and
a run's cost is model latency, not CPU — or by running several one-worker
instances with **separate state directories** (`OPENSTATEGRAPH_STATE_DIR`)
behind a session-affinity proxy, accepting that a thread paused on one instance
must be resumed on the same instance.

### Postgres: worth doing, and not the lift

```bash
pip install 'openstategraph[postgres]==0.3.0'
export OPENSTATEGRAPH_POSTGRES_URL="postgresql://osg:...@db.internal:5432/osg"
```

**That line names a version on purpose.** `openstategraph` is on PyPI as of
`0.3.0rc18`, so no index flag is needed — but the shipped version is a
pre-release, and pip excludes pre-releases from an unpinned requirement, so a
bare `pip install 'openstategraph[postgres]'` returns what looks like a 404.
The pin goes away with the first final release ([Releasing](releasing.md)).

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

`OPENSTATEGRAPH_KANBAN_URL` is a **different** setting and never this one: it
puts the patrol board in a database several maintainers share, and pointing one
URL at both would file a maintainer's cards into an adopter's checkpoint
database ([The patrol board](the-patrol-board.md) § Team board).

The store follows the same shape — the same four rows, with
`OPENSTATEGRAPH_MEMORY_PATH` in the checkpoint variable's place and
`memory.sqlite` beside `checkpoints.sqlite` in the last one. Since
install-experience wave 2 the *default* row is the same too: say nothing and
long-term memories are durable, exactly as approvals are, and one startup line
says where they landed. Two files rather than one database, because the two
have different lifetimes — wiping threads while keeping what was learned is a
thing a deployment legitimately does.

**There is a third file**, on the same reasoning and with no variable of its
own: `runs.sqlite` beside the other two, the run journal every door writes a
finished run into (`openstategraph runs path` prints it, `runs list` and
`runs export` read it). It holds questions, health and usage rather than state
a run resumes from, so losing it loses history and no work in flight — but it
is a third file under `state_dir()`, and back-up advice naming two of three is
the kind that is discovered at restore time.
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

# 3. Provider keys in the environment, never in openstategraph.yaml — and
#    never left to a browser to supply on a shared deployment (§1c).
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

## 5. Upgrading on the same port

A release that reuses the port is the ordinary case, and it used to hand every
returning browser a white page: the shell it had cached named
`assets/index-<oldhash>.js`, the new server did not have that file, and the
only evidence was a 404 in a console nobody had open.

The server states its own caching, and you do not configure it:

| What | `Cache-Control` |
| --- | --- |
| the shell — `/`, `/index.html`, `/w/<slug>`, `/chat` | `no-cache` |
| hashed assets — `assets/<name>-<hash>.<ext>` | `public, max-age=31536000, immutable` |

`no-cache` stores the document and revalidates it; the `ETag` already sent
makes that a 304 rather than a re-download. The `immutable` half is what keeps
it cheap — a hashed file's name changes when its bytes do, so nothing ever asks
about it twice.

**If a proxy sits in front, let both through.** A cache that rewrites or drops
`Cache-Control` on the shell restores exactly the failure above. The shell also
carries a plain inline fallback that says "this page is from an older build —
reload" when a script or stylesheet will not load, so a stripped header is a
sentence rather than a blank page — but it is a backstop, not the fix.

## Not solved here

Stated so nobody infers otherwise from the presence of a login form:

- **Per-user authorization.** One shared secret is not identity. Every holder
  is the same principal, and no draft, publish or run is attributed to a
  person. §1b closes exactly one part of this — which *memory namespace* a run
  may touch — and closes it by refusing rather than guessing. It is not a
  general authorization layer, and nothing else in the product is per-user yet:
  thread listing filters by `user_email`, and `api/threads.py` says in as many
  words that this is "a filter, not an authorization check". Reading one
  thread is the exception: `GET` on a thread takes an `audience`, capped by the
  same `resolve()` the run doors use and defaulting to `customer`, so a
  deployment pinned to `OPENSTATEGRAPH_AUDIENCE=customer` cannot be talked into
  a run's machinery through its history either.
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
