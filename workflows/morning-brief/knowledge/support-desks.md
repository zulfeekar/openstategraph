Support desks — the three queues, what belongs in each, and when a ticket stops being a ticket.

# Support desks

Three queues, and a ticket lives in exactly one of them.

| Desk | Owns | Does not own |
| --- | --- | --- |
| **Billing** | invoices, charges, refunds, failed payments, renewals | why the product broke while they were paying for it |
| **Technical** | something is broken, slow, or not doing what it says | who is allowed to use it |
| **Account** | sign-in, seats, permissions, contact details, cancellation | anything with a figure on it |

Route on **what must be fixed**, never on tone. A furious message about a wrong
charge is billing; a polite one about a broken export is technical.

## When a ticket stops being a ticket

Three tickets naming the same symptom within one hour is an **incident**, and
the on-call rota owns it from that moment (`on-call`). The desk does not keep
answering them individually — it answers once, in the incident thread, and the
replies point there.

## Nothing is sent without a person

Every customer-facing reply is drafted, graded and then held until a human
approves it. A rejection is recorded with the reviewer's reason and the ticket
returns to the queue; it is never silently redrafted and sent.

The gallery's `support-triage` example (`gallery`) is this policy drawn as a
graph, and it is the closest thing to a specification the desks have.
