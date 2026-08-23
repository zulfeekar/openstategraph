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
therefore run on the installation default, and only `synth1` names a vendor,
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

Three runs, and they have to be read together because the first one found the
boundary, the second one crossed everything past it in isolation, and the
third — after both halves of `workflow-gallery` 34 and its split-out 67
shipped — crossed it live, unseeded, end to end.

### Run 1 — unseeded, end to end, 2026-08-23

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy youtube-trend-digest
openstategraph run workflows/youtube-trend-digest \
  "What is trending on YouTube right now, and what is the top video actually about?"
```

`attempts: 3`, `warnings: []`, and a real digest — no id was seeded, no
aggregator was named in the question. `trend1` returned the ranking with a
resolved link:

> 1, Avengers: Doomsday | Special Look | In Theaters December 18, Marvel
> Entertainment, Film & Animation, 33.3M, X1aFkAkFASk,
> https://www.youtube.com/watch?v=X1aFkAkFASk, lenostube.com

`read1` fetched the captions for that id and quoted them under `TREND:` /
`TRANSCRIPT:`; `synth1` produced:

> The top trending video on YouTube right now is Marvel's "Avengers: Doomsday
> | Special Look" trailer, which has accumulated 33.3 million views. The video
> focuses on the character Victor, exploring his tragic transformation from
> "the smartest guy in every room" who "used to be kind" and "caring" into
> someone broken after losing everything he loved. This emotional character
> study appears to be a key emotional hook in the marketing for the film,
> positioning Victor's fall from grace as central to the Doomsday storyline
> coming to theaters December 18.

152 227 tokens on `gpt-oss:120b` (two unpinned agents, cloud) and 1 731 on
`claude-haiku-4-5` (the one paid call). This is what changed between the first
attempt and this one: `trend1`'s first rung is `tool.web-search`, which on
2026-08-15 was `html.duckduckgo.com` alone and refusing every request
machine-wide. `workflow-gallery` **67** gave it a second, keyed rung —
Tavily, behind `TAVILY_API_KEY` — and DuckDuckGo is still the blocked rung
today (HTTP 202, same challenge, eight days on); the ladder fell through to
Tavily and the run finished. **`web_fetch`'s link-preserving fetch, the other
half of ticket 34, is what let the third rung skip search entirely** — the
same aggregator fetch that once needed a follow-up search now carries the
`watch?v=` id inline, which is why `trend1` needed only one search call
(the first rung) rather than the two ticket 01 originally routed.

### Run 2 (superseded) — the boundary this replaced

The original Run 1, 2026-08-15: 81 seconds, `attempts: 3`, `warnings: []`, and
**no digest**. `trend1` came back with
`{"url":"https://www.noxinfluencer.com/trending"}` — a tool argument, not an
answer — and `read1` reported, correctly, that `tool.web-search` was refusing
every request, machine-wide, after an hour and fifty minutes of probing:

```
The search endpoint refused this request (HTTP 202) — it is rate-limiting or
challenging automated searches, so the web could not be searched at all. This
is not an empty result: do not conclude anything about what is on the web.
```

That was the atom behaving exactly as it should, and it was fatal to this
example's first step at the time. Ticket 01's route is *`web_search` →
`web_fetch` an aggregator → `web_search` the title for the `watch?v=` id*, and
two of its three rungs were the tool that was down. `web_fetch` was fine — the
aggregator came back with that day's ranking, 8 013 characters of
rank/category/channel/title/views — but `_strip_html` deleted attributes with
their tags, so the page carried no link and no id. Both defects are now fixed:
the link-preserving fetch and the second search rung, both `workflow-gallery`
34 (split into 67 for the backend decision). Run 1 above is the replacement
live measurement; this section stays only as the record of the boundary that
was found.

### Run 3 (superseded) — seeded at the id, and everything downstream is real

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

`RunResult` carries no token usage, so the figures below come from the CLI's
own `--json usage` block (Run 1) and, for Run 3, from wrapping the same
`ask()` in `langchain_core.callbacks.get_usage_metadata_callback` — an
in-process aggregator, no tracer, no account. That the platform cannot answer
this itself is gallery ticket 35.

| | in | out | total | $ |
| --- | --- | --- | --- | --- |
| Run 1, `gpt-oss:120b` (two agents, cloud, one extra search rung) | 146 397 | 5 830 | **152 227** | — |
| Run 1, `claude-haiku-4-5` (one call) | 1 606 | 125 | **1 731** | ~$0.0022 |
| Run 3, `gpt-oss:120b` (two agents, cloud) | 7 456 | 1 765 | **9 221** | — |
| Run 3, `claude-haiku-4-5` (one call) | 1 486 | 141 | **1 627** | **$0.0022** |

Run 1's `gpt-oss:120b` figure is far above both Run 3 and the gallery's
~24 000-token estimate — it includes the ReAct loop's own back-and-forth
across `attempts: 3` and the ladder's extra rung (DuckDuckGo blocked, Tavily
answered), not a fixed per-run cost. The paid call is unchanged either way:
one Claude call, a fifth of a US cent, because the synthesis input is sized by
the transcript, not by how the trend was found.

The original Run 1 (now "Run 2, superseded") burned **61 832** cloud tokens
producing nothing at all: three laps of an agent retrying a refusing tool with
no fallback rung to fall to. A ladder that can fall through, even at ~15×
Run 3's token cost in the worst case measured so far, is strictly better than
one with no second rung — it still finishes. That asymmetry is the argument
for ticket 35 (measuring this cost natively) and for keeping the ladder
short: adding a third, slower rung would raise the worst case further.

### Against the catalogue's expected shape

> *A short synthesis naming a specific, currently-trending video and quoting
> from its transcript — not a generic essay.*

**Met, unseeded, live, 2026-08-23.** The trend is today's and came from a live
fetch; the video id came from that same fetch's inlined link, `trend1` needed
only its first search rung; the transcript is that video's and was fetched by
the atom built for it; the synthesis is Claude's, naming the video and film,
quoting the trailer's dialogue. `workflow-gallery` 34 and 67 are what closed
the gap this section used to describe.

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
