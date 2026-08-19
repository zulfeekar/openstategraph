# test-as-a-user

**When the owner says "test", this is what it means.** Not run the suite. Not
call the API. Open the browser, talk to the workflow like a person, and hunt
what you find until it is dead.

## The loop, and none of it is optional

1. **Act as a user, interactively, in the browser.** Type into the chat. Press
   the buttons. Read what comes back.
2. **Identify the gap or bug** from what is on screen — the answer, the trace,
   the card, the canvas.
3. **TDD.** Write the failing test first, at the layer the defect actually
   lives.
4. **Act as a user again.** Same question, same path, in the browser. If it is
   not fixed on screen, it is not fixed.

Step 4 is the one that gets skipped and it is the one that matters. A green
suite is not the verification; the chat is.

## Read the whole response, not the last line

The single most expensive mistake on this map was aiming at the wrong sentence.
The transcript said:

    web_search   → returned six results, one with the price
    web_fetch    → Error: web_fetch is not a valid tool
    answer       → Error: web_fetch is not a valid tool …

Three separate defects sit in that, and only one is about the final sentence:

- the agent **already had** the answer and did not use it,
- it asked for `web_fetch`, **which exists in the library**, and nothing offered
  to add it,
- the raw error string was published **as the answer**.

Before deciding what to fix, list every wrong thing in the response. Then ask
which one, fixed, makes the others impossible.

## Prefer the deterministic signal over the model's cooperation

If the runtime already knows something, use it — do not ask a model to say it.

`web_fetch is not a valid tool` is our own error, with the name in it, and
`tool.web-fetch` is in the catalogue. That is a fact the code can act on. Two
rounds of prompt wording were spent trying to persuade a model to reach the
same conclusion it was already handing us in plain text.

**A prompt is the last resort, not the first.** When the fix can be a lookup,
make it a lookup.

## What to try, as a person

- the lazy half-sentence · the correction · the vague follow-up
- the thing it cannot do — it must **say so**, or offer the missing piece
- the gate: approve one, reject one with a note, reject one in silence
- rude input: empty, one character, another language

## Instrument rules, each one paid for here

- **Read DOM structure, never `innerText`.** Three false findings.
  `.ask__turn` › `.ask__steps` · `.ask__tools` · `.ask__answer-block` ·
  `.ask__suggestion` · `.ask__warning`.
- **The editor caches a draft per slug** in `localStorage`. A file corrected on
  disk can be masked for a whole session. Check the node count on the canvas
  against the file before believing anything.
- **uvicorn does not auto-reload.** Restart it after a backend edit.
- **The browser console is cumulative** across navigations. Stamp a per-boot id
  on probes.
- **Three data points** before calling anything systematic.
- **Check the environment before blaming the code.** `tool.web-search` answering
  HTTP 202 makes a correct refusal look like a bug.

## Then

Ticket with `/wayfinder`: what the user saw, the chain back, what was ruled
out, the reproduction. Fix one at a time. **Verify by trying to break it** —
twice on this map a fix was incomplete and only a live re-run showed it.

An honest *"reproduced, not diagnosed"* is finished work. A guessed fix is not.
