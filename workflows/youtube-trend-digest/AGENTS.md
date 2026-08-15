# YouTube Trend Digest

Gallery example 16 of twenty — **the flagship**. Find what is trending on
YouTube right now, read the top video's actual transcript, and hand both to
Claude for a three-sentence synthesis. The only multi-provider example, the
only one that spends money, and the only one whose acceptance test is external
reachability.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the request enters |
| `t-search` **Search** / `t-fetch` **Fetch** | the two keyless web atoms |
| `trend1` **Trend finder** | search → fetch a server-rendered ranking → search the title back to a `watch?v=` id |
| `t-transcript` **Transcript** | `tool.youtube-transcript`, `en`, auto-captions allowed, 8 000 chars |
| `read1` **Transcript reader** | fetches the captions and quotes them under a TREND block |
| `synth1` **Synthesis** | `data.model: "anthropic/claude-haiku-4-5"` — the one paid call |
| `out1` **Digest** | markdown |

`t-search` is bound to **both** agents from one node: its `tool` port is
`maxConnections: null`, so it fans out and no second card is needed.

The wiring is not a guess. Ticket 01 probed every route live before a line of
this document existed, and `research/01-youtube.md` §5 is the diagram this file
implements node for node.

## Why it is three agents and not one

Because `agent.prompt` is `maxConnections: 1`, and that constraint decides the
whole shape.

The reader cannot be handed both the question and the trend report, so the
**trend report is its question**. And the synthesis cannot be handed both the
trend context and the transcript, so the reader has to carry the trend forward
— which is why its prompt ends by writing two named blocks, `TREND:` and
`TRANSCRIPT:`, and why the synthesis prompt names the same two. `tests/`
asserts both halves, because the failure mode is silent: hand Claude a
transcript with nothing to place it against and it will still produce three
fluent sentences.

## Two model strings, two spellings, and they are not interchangeable

This is the first shipped `workflow.json` to set a per-node model, so the trap
is worth stating where someone will read it:

| Where | Form | Example |
| --- | --- | --- |
| `settings.model` (document) | **colon** — `init_chat_model` | `ollama:gpt-oss:120b-cloud` |
| `data.model` (node) | **slash** — selection | `anthropic/claude-haiku-4-5` |

`NodeRuntime._base_model` partitions the node's value on `/` and rebuilds
`f"{provider}:{model_id}"`. A colon in the node field resolves the provider
`"anthropic:claude-haiku-4-5"`, which is not a provider. An empty string means
"use the workflow default", which is what the two other agents leave it as.

**This document sets no `settings.model`** — the row above shows the spelling,
not this file's contents. Every shipped example dropped its pin so a copied
example runs on whatever the adopter installed; the two unpinned agents
therefore run on the instance default, and only `synth1` names a vendor,
because this example is *about* mixing two of them. The recorded run below was
made where this repository pins its own default, `ollama:gpt-oss:120b-cloud`.

`synth1` holds **no tools**, deliberately: one call, one price. A tool on the
paid node turns it into a loop of unknown length.

## Why the transcript needed a new atom

`web_fetch` is GET-only and strips `<script>` before anything sees it. Every
`timedtext` URL a web client can obtain returns **HTTP 200 with 0 bytes** — for
ASR and authored tracks, VOD and livestream alike. The only route that returns
caption text is a JSON **POST** to InnerTube with a non-web client identity,
followed by a GET of the URL that answer issues, and a POST body is not a `url`
argument. So `tool.youtube-transcript` was built (gallery ticket 09) with a
client ladder — `IOS` → `ANDROID_VR` → `WEB` — because the same video answered
`OK` to one client and `LOGIN_REQUIRED` to another seconds apart.

Its failure messages are distinguishable on purpose, and the reader's prompt
leans on that: *a bot check is not "no captions"; an empty caption track is not
an empty transcript.* An atom that collapsed those into one message would let
the reader summarise from the title and call it a transcript.

## The run, and what it cost

Two runs on 2026-08-15, and they have to be read together because the first one
found the boundary and the second one crossed everything past it.

### Run 1 — the whole thing, and where it stopped

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy youtube-trend-digest
openstategraph run workflows/youtube-trend-digest \
  "What is trending on YouTube right now, and what is the top video actually about?"
```

81 seconds, `attempts: 3`, `warnings: []`, and **no digest**. `trend1` came back
with `{"url":"https://www.noxinfluencer.com/trending"}` — a tool argument, not
an answer — and `read1` reported, correctly:

> I'm unable to retrieve the current YouTube-trending list … the web-search
> tool is being rate-limited and I don't have a way to fetch the page directly.

**`tool.web-search` was refusing every request, machine-wide**, and still was
after an hour and fifty minutes of probing and backing off:

```
The search endpoint refused this request (HTTP 202) — it is rate-limiting or
challenging automated searches, so the web could not be searched at all. This
is not an empty result: do not conclude anything about what is on the web.
```

That is the atom behaving exactly as it should, and it is fatal to this
example's first step. Ticket 01's route is *`web_search` → `web_fetch` an
aggregator → `web_search` the title for the `watch?v=` id*, and **two of its
three rungs are the tool that is down.** `web_fetch` is fine — the aggregator
came back with today's ranking, 8 013 characters of rank/category/channel/
title/views — but `_strip_html` deletes attributes with their tags, so the page
carries no link and no id. Nine other candidate sources were probed and not one
put a `watch?v=` id in its text.

The full failure, and the fallback it names, is gallery ticket 34.

### Run 2 — seeded at the id, and everything downstream is real

To isolate the failure, the same document was run with the trend context in the
question: today's #2 from that same aggregator fetch — *Total War: WARHAMMER
III – Lords of The End Times – Cinematic trailer*, Gaming, 364.7K views, 16
hours old — plus its video id, recovered **out of band** because `web_search`
could not. Everything after that point is the workflow doing its own work.

`read1` fetched the captions live and quoted them:

> "How can it be possible that you do not know me? I… masterminder of schemes
> within schemes most powerful of Grey Seers! … I allied with rot-things -
> yes-yes - but wait for right time to cut-slit throats … START ENGINE NOW!
> Blast-smash moon! … The chosen of the horned rat will rise! Now none shall
> forget Grey Seer Thanquol!"

1 140 characters of real transcript, both XML shapes handled, no bot check.
Then `synth1` — the one Claude call:

> This is a cinematic trailer for Total War: WARHAMMER III that introduces a
> villainous character, Grey Seer Thanquol, who has orchestrated an elaborate
> scheme involving multiple factions to power up a mysterious weapon called
> "The Engine". The video is trending because it showcases dramatic
> storytelling and high-stakes conflict, with the antagonist declaring **"The
> chosen of the horned rat will rise!"** as he activates his master plan
> against various fantasy factions. The trailer emphasizes Thanquol's
> manipulative genius as he reveals how he **"allied with rot-things"** and
> deceived other forces to achieve his ultimate goal of devastating power.

Three sentences, two phrases quoted from the transcript, one character name
that appears nowhere but the captions. **Grounded in what was read, not in the
title** — which is the whole claim this example makes.

### Cost, measured rather than estimated

`RunResult` carries no token usage, so the figures below come from wrapping the
same `ask()` in `langchain_core.callbacks.get_usage_metadata_callback` — an
in-process aggregator, no tracer, no account. That the platform cannot answer
this itself is gallery ticket 35.

| | in | out | total | $ |
| --- | --- | --- | --- | --- |
| `gpt-oss:120b` (two agents, cloud) | 7 456 | 1 765 | **9 221** | — |
| `claude-haiku-4-5` (one call) | 1 486 | 141 | **1 627** | **$0.0022** |

23.8 seconds end to end. At $1/$5 per MTok that is **a fifth of a US cent**,
against ticket 01's ~$0.006 estimate — the synthesis input came in at 1 486
tokens rather than the budgeted 4 800, because the transcript is a 169-second
trailer.

Run 1, by contrast, burned **61 832** cloud tokens producing nothing: three
laps of an agent retrying a refusing tool. The gallery's ~24 000-token estimate
for this example is right for a run that works and 2.5× low for one that
fights. That asymmetry is the argument for ticket 35.

### Against the catalogue's expected shape

> *A short synthesis naming a specific, currently-trending video and quoting
> from its transcript — not a generic essay.*

**Met on every clause except the discovery of the video, which no atom could
perform today.** The trend is today's and came from a live fetch; the
transcript is that video's and was fetched by the atom built for it; the
synthesis is Claude's, three sentences, quoting the captions. The one thing the
workflow could not do for itself was turn a title into an id, and that is one
refusing search backend, named in ticket 34.

## Tests

`tests/` asserts the four-step chain and its exits, that each agent holds the
tools its step needs and the paid node holds none, that exactly one node
overrides the model and in the slash form while the document uses the colon
form, that both TREND/TRANSCRIPT blocks are named on both sides of the seam,
and that the reader is told never to write a transcript it was not given. No
model is called and no packet leaves the machine.

## It resists both fixture formats, and the reason is the calendar

`tests/` asserts the document, as everywhere. It cannot assert the answer, and
neither format would fix that.

An `evals/*.eval.json` needs a reference output that stays true. This
workflow's correct answer is *today's* trending video and a quotation from a
transcript that did not exist last week — a gold row committed this morning is
a wrong assertion tomorrow, and the test that fails would be reporting the
calendar rather than a regression. A shape assertion over a completed run has
the same defect one level up: it would pin that a video was named, which a
stubbed search satisfies without the network ever having answered.

So the acceptance test is external reachability, run deliberately and written
down above — including the run where `web-search` refused for two hours, which
is the kind of finding a fixture would have converted into a red test with no
information in it. See `docs/evaluation.md` §"Grading during a run vs grading a
dataset".
