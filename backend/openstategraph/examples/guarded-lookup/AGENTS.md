# Guarded Lookup

Gallery example 22 — **one policy, two directions**, and the only example
where the same rule reaches opposite conclusions depending on where you put
the card.

| Node | One line |
| --- | --- |
| `in1` — Question | The turn. |
| `guard-in` — At the door | `email → pass`, `credit_card → block`. |
| `lookup` — Customer directory | `customer_lookup`, bound to the agent. Exact match on the address. |
| `agent1` — Support desk | Calls the tool, answers in two or three sentences. |
| `guard-out` — On the way out | `email → redact`, `url → redact`, `phone → mask`. |
| `out1` — Answer | What a person reads. |
| `refused` — Refusal | Where a blocked message goes. |

## What it exists to exercise

The unit of policy is **`entity × direction`**, and direction is not a
setting — it is which of the two cards you dropped the rule on.

A user gives an email address so a customer can be looked up. Inbound that
address must **pass**: `customer_lookup` matches on the exact string, so a
redacted one finds nothing. Outbound the same entity is **redacted**, because
what comes back is data the user never supplied — a phone number, a support
link, an address on file.

Both cards are the same node type, the same class and the same builder.
Nothing in either one knows which direction it is.

The `credit_card → block` row is the other half: a refusal is a **wire**. It
leaves `guard-in` by the `blocked` port, reaches `refused`, and a person reads
a sentence naming the category. No model is called at all.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy guarded-lookup
openstategraph run workflows/guarded-lookup "What plan is bjorn.hansen@yahoo.no on, and how do I reach him?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`.

**The redact path**, asking for the full contact details on file for
`ftremblay@gmail.com` — 2.4 s:

> François Tremblay lives in Montréal, Canada, is on the Premium plan, and can
> be reached at \*\*\*\* 721‑4711. Their support ticket is `[REDACTED_URL]` and
> their email is `[REDACTED_EMAIL]`.

with, on the developer channel:

```
redactions: guard-out → email ×1 (redact), url ×1 (redact), phone ×1 (mask)
```

and, in the run's own record, the thing the whole design is about:

```
outputs["in1"]       "…on file for ftremblay@gmail.com, including their email address."
outputs["agent1"]    "…their email is [REDACTED_EMAIL]."
```

The address the user typed is still there, exactly as typed, which is how you
can tell the tool received the real one. What the *agent produced* is
scrubbed. Nothing anywhere says which card is which; the wire does.

**The block path**, `"My card is 5105-1051-0510-5100, please look up
hholy@gmail.com for me."` — 0.0 s, because no model runs:

> Blocked by a guardrail: this content contains a credit card number, which
> this workflow is not allowed to pass on.

`decisions` is `{"guard-in": "blocked"}`, the refusal reaches `refused`, and
the card number is gone from **every** `outputs` entry — including `in1`,
which a redaction would have left alone. A redaction means the reader must
not see it; a block means the workflow must not hold it, and a checkpointed
trace outlives the run.

## The thing this example found, twice

`phone` has no built-in detector — LangChain ships `email`, `credit_card`
(Luhn-validated), `ip`, `mac_address` and `url`, and nothing else — so the
phone row carries a regex. The first version was
`\+[0-9][0-9 ()\-]{6,}[0-9]`, which is correct against a phone number and
useless against a model:

- the first live run came back with `+47 22 44 22 22` —
  **narrow no-break spaces**, U+202F — and the ASCII space in the class did
  not match, so the number went out in full;
- with `\s` in its place it matched, and the very next run produced
  `721‑4711` with a **non-breaking hyphen**, U+2011, so the mask stopped one
  group short: `**** 721‑4711`.

That is worth more than the example itself. The built-in shapes are borrowed
for a reason, and a custom pattern is the developer's own risk in a way a
Luhn check is not — model prose is typeset, not typed. If you add a row, test
it against something a model actually wrote.

## Tests

`tests/` asserts the **document**, and specifically the asymmetry: `email` is
`pass` on one card and `redact` on the other. If a future edit made the two
agree, the example would still run and would have stopped demonstrating
anything.

It calls no model. Whether the agent phrases the answer well is a model
question; that no address survives to the reader is a mechanism question, and
`backend/tests/test_guardrail_node.py` proves that against a stub.

## The directory

`tools/directory.py` holds six records in a dict rather than a database. They
are the Chinook sample database's fictional customers, and there is no second
copy of that 1 MB SQLite file in the wheel: this example is about the policy,
not about SQL. `sql-qa` is where the database lives.

The tool returns *nothing* for an address it does not match exactly, and says
which address it was given. That is deliberate — it is how a run that lost the
address to an over-eager inbound rule diagnoses itself in one line instead of
looking like a customer who does not exist.
