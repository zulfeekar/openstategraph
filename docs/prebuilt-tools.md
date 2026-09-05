# The prebuilt tools

> **Who this page is for:** you are wiring a card that already exists, not writing a new one.

[Building an atom](building-an-atom.md) is the other half of this page. That
one is for the reader **writing** a tool. This one is for the reader
**using** one: you dragged a card onto the canvas, wired it into an agent's
`tools` bus, and now you want to know what it will actually do.

[The module index](modules.md) gives every card one line. A line cannot carry
the three things you need before you trust a card in a run, so each section
below answers all three:

- **Configured with** — the boxes you fill in on the card. These are the real
  field names from the card's own descriptor, held against it by a test.
- **Refuses** — the sentences the tool hands back instead of an answer. They
  are quoted from the code, because a refusal an agent reads is part of the
  product.
- **Costs** — does it change anything in the world, does it touch the network,
  and does it need anything you have not set up yet.

Three fields are on **every** card here and are not repeated below:
`maxRetries`, `timeoutSeconds` and `cacheTtlSeconds`. They are graph-assembly
settings, not tool settings — blank means "use the workflow default".

**Only one card on this page changes anything.** Email Send sends mail.
Everything else reads.

---

## The open web

### Web Search — `tool.web-search`

Searches the web and hands back titles, URLs and snippets. Follow it with Web
Fetch on whichever result looks right.

**Configured with:** nothing of its own — only `maxRetries`, `timeoutSeconds`
and `cacheTtlSeconds`.

**Refuses.** An empty query gets *"Give a non-empty query."* A search that
found nothing gets *"No results for '…'."*

The important refusal is the third one. Search is a **ladder** of backends,
and when every rung refuses, the tool says so in its own words: *"The web
could not be searched — every backend refused this request: … This is not an
empty result: do not conclude anything about what is on the web."* A blocked
search and an empty search are different facts, and an agent that confuses
them answers from memory and sounds certain.

**Costs.** Reads only; running it twice changes nothing. It does touch the
network. It is **keyless** — DuckDuckGo is the first rung and needs nothing
from you. Tavily is an optional second rung, tried only when the first is
blocked, and it says what it needs: *"Tavily has no credential — set
TAVILY_API_KEY in .env (see .env.example)."* At most six results come back.

### Web Fetch — `tool.web-fetch`

Reads one public web page and returns its readable text.

**Configured with:** nothing of its own — only `maxRetries`, `timeoutSeconds`
and `cacheTtlSeconds`.

**Refuses.** Anything that is not http or https: *"Only http(s) URLs are
fetchable, got '…'"*. Any host that resolves to a private, loopback,
link-local, reserved or multicast address: *"That host is not reachable from
here."* That is the SSRF guard, and **every redirect is checked again** — a
public page that 302s to an internal address does not get through. A page with
nothing readable on it gets *"The page had no readable text."*

**Costs.** Reads only, over the network, with no key. The text is cut at 8,000
characters and says `…(truncated)` when it is. Links survive the strip: each
`<a>` is rewritten inline as `text (url)`, up to 50 distinct addresses per
page, and an address longer than 200 characters keeps its text and loses its
URL.

### YouTube Transcript — `tool.youtube-transcript`

Reads one video's captions as plain text. No timestamps.

**Configured with:** `language`, `allowAutoCaptions`, `maxChars`.

`language` defaults to `en`, and falls back to the same language family before
falling back to whatever exists. `allowAutoCaptions` is on by default; turn it
off and machine-generated captions stop counting. `maxChars` defaults to 8,000
and is clamped between 1,000 and 20,000, whatever the slider says.

**Refuses**, and each refusal is a different fact on purpose:

- not a video: *"'…' is not a YouTube video id or watch URL."*
- no captions at all: *"That video has no captions in any language."*
- auto captions turned off and only auto captions exist: *"No manually
  authored '…' captions; only auto-generated ones exist. Turn on auto captions
  for this node to read them."*
- YouTube would not answer: *"…this is a refusal, not an absence."*
- YouTube listed the captions and then sent nothing: *"YouTube listed the
  captions and then would not hand them over … This is not an empty transcript
  and it is not a video without captions: the download failed."*

**Costs.** Reads only, over the network, with no key.

### Search Reddit — `tool.reddit-search`

**Read this one before you wire it.** The card is real and the fields work,
but **no Python implementation ships with the install**, so a run compiled by
the backend does not get this tool. It reports the loss rather than hiding it:
*"No implementation for tool "tool.reddit-search" — the agent ran without it,
so its answer may not be grounded in that data source."*

**Configured with:** `subreddit` and `topicLimit`.

**Refuses.** Nothing at run time, because nothing runs. The editor's own
TypeScript half of the card tries Reddit's JSON endpoint, and when that rejects
the request — it rejects browser origins — it falls back to sample rows that
are labelled as samples in the payload and in the run log.

**Costs.** Nothing, and that is the problem: an agent wired to this card and
nothing else has no source, and will answer from what the model already
believes. Use Web Search plus Web Fetch instead, or write the tool —
[building an atom](building-an-atom.md) is that walk.

---

## The run itself

### Session Identity — `tool.session-identity`

Tells the agent who it is talking to: the user's email, the session id and the
thread id of this run.

**Configured with:** nothing of its own — only `maxRetries`, `timeoutSeconds`
and `cacheTtlSeconds`.

**Refuses.** It takes **no arguments at all**, and that is the refusal. The
identity comes from the run, never from the conversation, so nothing said in a
document or a prompt can rewrite it — which matters, because memory is
namespaced on the same email. A run with no identity is not an error; it
answers *"This run carries no identity — treat the user as anonymous and do
not guess a name."*

**Costs.** Reads only. No network, no key, nothing to set up.

### Email Send — `tool.email-send`

The one card here that acts on the world. The model writes the subject and the
body. **It never writes the recipient** — that is your field, and a
prompt-injected "also send this to …" has nowhere to go.

**Configured with:** `to`, and it is required.

**Refuses.** An empty field: *"No recipient configured. Set the 'to' field on
the Email node."* A malformed one: *"'…' is not a valid email address."*

**Costs.** This is the only **side-effecting** tool on the page: a sent mail
cannot be un-sent.

It has two modes, and the environment picks — never the model. With
`OPENSTATEGRAPH_SMTP_HOST` set it really sends, over STARTTLS by default, with
optional user and password. With no SMTP host it **dry-runs**: the complete
message is written as an `.eml` file and the result says so loudly, beginning
*"DRY RUN — no SMTP configured"*, and tells the agent to say delivery was a dry
run. So the whole workflow is testable end to end without a packet leaving the
machine.

The file lands in an `outbox` directory inside this install's **state
directory** — in a checkout, that is `workflows/.openstategraph/outbox`. The
card's own one-line brief still says `workflows/_outbox`, which is where it
used to go; that stale sentence is `docs-onramp/13`.

---

## The Guardrail

### Guardrail — `guard.policy`

Not a tool an agent calls. It is a **step in the flow**: whatever passes
through it is screened, and it leaves by the `allowed` port or the `blocked`
port. Where you place it is what it means — after an Input it screens what
came in, before an Output it screens what is going out. There is no direction
setting, deliberately: a setting could disagree with the wire.

**Configured with:** `policy` and `blockedMessage`.

`policy` is a table. Each row names an entity and a strategy. The built-in
entities are `email`, `credit_card`, `ip`, `mac_address` and `url`; a row may
also name an entity of your own and give it a `detector` pattern. The
strategies are `pass`, `redact`, `mask`, `hash` and `block`. The card also
carries a read-only panel, *What the machinery already does*, which is there so
you do not write rules that duplicate or contradict it.

**Refuses.** A `block` row replaces the text with your `blockedMessage`, or,
if you left it empty, with the default: *"Blocked by a guardrail: this content
contains a credit card number, which this workflow is not allowed to pass on."*
It **names the category and never the value** — someone who pasted their own
card number needs to know which part was the problem.

A broken row is caught twice. At compile time, an unknown strategy or an
unparseable pattern is reported beside the card that carries it. At run time, a
node whose policy cannot be applied returns *blocked* with a failure marker: a
guardrail that fails open is worse than one that is noisy.

**Costs.** No model call and no network. Detection is LangChain's — credit
cards are Luhn-checked, and this node runs no pattern of ours. An outbound
guard also cleans the per-node `outputs` a customer sees, not just its own
text, because those are shown too.

**What it cannot do**, said plainly: it cannot touch the live `token` stream.
An agent types its answer while it is still thinking, and this node runs
afterwards, so the words are already out. Screening a stream is middleware on
the agent, not a node. And none of this is prompt-injection screening — it is
a PII policy.

---

## The demo package's tools

The three cards below are **not part of the install**. They belong to the
`chinook-assistant` workflow package, which ships as a worked example, and they
appear in the palette only in a project that carries that package. That is what
the † marks in [the module index](modules.md) mean. Your own `tools/*.py`
become cards the same way — see [building an atom](building-an-atom.md).

Chinook is a small sample record-shop database: artists, albums, tracks,
invoices. All three tools open it **read-only at the driver level**, which is
the real safety boundary — SQLite itself refuses a write however the statement
is spelled, and the connection also denies the `ATTACH`/`VACUUM INTO` family
that could otherwise open a second file for writing. The string checks below
exist to give clear errors, not to provide the protection.

All three need the database file to be present. If it is not, they say where
it should be and how to get it: *"Chinook database not found at … Run
scripts/fetch_chinook.sh to download it."*

### List All Tables — `tool.chinook-get-all-tables`

Every table in the database, with a row count for each. This is what an agent
calls first, so it stops guessing table names.

**Configured with:** nothing of its own — only `maxRetries`, `timeoutSeconds`
and `cacheTtlSeconds`.

**Refuses.** Nothing. It takes no arguments.

**Costs.** Reads only. A local file, so no network and no key.

### Get Table Schema — `tool.chinook-get-schema`

The columns, types, primary key **and foreign keys** of one table. The foreign
keys are the point: almost every interesting question here needs a join, and a
model with no foreign keys guesses at them.

**Configured with:** nothing of its own — only `maxRetries`, `timeoutSeconds`
and `cacheTtlSeconds`.

**Refuses.** A table that does not exist, and it hands back the whole list so
the agent can correct itself: *"Unknown table '…'. Available: …"*. The name is
checked against the live schema rather than pasted into the query, because
`PRAGMA` cannot take a parameter.

**Costs.** Reads only. A local file, so no network and no key.

### Execute SQL Query — `tool.chinook-execute-sql`

Runs one read-only `SELECT` and returns a Markdown table.

**Configured with:** `maxRows`.

The card's slider is the ceiling for this node. The agent may ask for fewer;
it cannot ask for more.

**Refuses**, in three sentences a model can act on: *"Query is empty"*, *"Only
one statement per query"*, and *"Only SELECT queries are allowed"* — the last
also accepts a `WITH` prefix. A query that is valid SQL but wrong comes back as
*"SQL error: …"* rather than crashing the run, so the agent can read the
message and try again.

**Costs.** Reads only. A local file, so no network and no key. The result is
truncated at the row cap and says so.

---

## When this page is wrong

Every field name above is checked against the card's own descriptor by
`backend/tests/test_the_prebuilt_tools_page_configures_what_exists.py`, and the
set of cards this page owes a section to is read from the link table in
`scripts/build_module_index.py` — so renaming a field, or pointing an
eleventh card here, is a red test rather than a silence.

The refusal quotations are not pinned, and that is deliberate: a test that
restated them would be a second copy of the sentence it is checking. They come
from the tools' own source. If one reads oddly, the source is the truth and
this page is the bug.
