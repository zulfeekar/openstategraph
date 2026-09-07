"""A customer directory, looked up by exact email address.

The tool exists so the example can prove something a mock could not: that the
**inbound** guardrail really did let the true address through. This lookup is
an exact match on the address it is given, so a redacted one finds nothing —
if the `email → pass` row on `guard-in` were `redact` instead, the agent would
receive `[REDACTED_EMAIL]`, the tool would return "no customer", and the run
would visibly fail rather than quietly return the same answer.

The records are the fictional ones from the Chinook sample database, which is
a fixture rather than a set of people. They are in this file rather than in a
copy of the 1 MB SQLite file that `sql-qa` already ships: this example is
about the policy, not about SQL, and a second copy of a database in the wheel
would be a megabyte spent on scenery.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from openstategraph.abc import BaseTool, ToolResult

#: Six fictional customers. Every field here is the kind of thing an outbound
#: guardrail exists to catch: an address the user never supplied, a phone
#: number, a support URL with an id in it.
DIRECTORY: dict[str, dict[str, str]] = {
    "luisg@embraer.com.br": {
        "name": "Luís Gonçalves",
        "phone": "+55 (12) 3923-5555",
        "city": "São José dos Campos, Brazil",
        "support": "https://support.example.com/tickets/1",
        "plan": "Standard",
    },
    "leonekohler@surfeu.de": {
        "name": "Leonie Köhler",
        "phone": "+49 0711 2842222",
        "city": "Stuttgart, Germany",
        "support": "https://support.example.com/tickets/2",
        "plan": "Standard",
    },
    "ftremblay@gmail.com": {
        "name": "François Tremblay",
        "phone": "+1 (514) 721-4711",
        "city": "Montréal, Canada",
        "support": "https://support.example.com/tickets/3",
        "plan": "Premium",
    },
    "bjorn.hansen@yahoo.no": {
        "name": "Bjørn Hansen",
        "phone": "+47 22 44 22 22",
        "city": "Oslo, Norway",
        "support": "https://support.example.com/tickets/4",
        "plan": "Premium",
    },
    "frantisekw@jetbrains.com": {
        "name": "František Wichterlová",
        "phone": "+420 2 4172 5555",
        "city": "Prague, Czech Republic",
        "support": "https://support.example.com/tickets/5",
        "plan": "Standard",
    },
    "hholy@gmail.com": {
        "name": "Helena Holý",
        "phone": "+420 2 4177 0449",
        "city": "Prague, Czech Republic",
        "support": "https://support.example.com/tickets/6",
        "plan": "Premium",
    },
}


class LookupArgs(BaseModel):
    email: str = Field(description="The customer's exact email address.")


class CustomerLookupTool(BaseTool):
    """Finds one customer record by exact email address."""

    name = "customer_lookup"
    #: Reads only — `launch-readiness` 121. Running it twice changes nothing.
    side_effecting = False
    node_type = "tool.customer-lookup"
    description = (
        "Look up a customer by their exact email address. Returns their name, "
        "phone number, city, support ticket URL and plan. Returns nothing if "
        "the address is not an exact match for a customer on file."
    )
    Args = LookupArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        email = str(getattr(args, "email", "")).strip().lower()
        record = DIRECTORY.get(email)
        if record is None:
            # Names what it was given, deliberately: this is how a run that
            # lost the address to an over-eager inbound rule diagnoses itself
            # in one line instead of looking like a customer who does not
            # exist.
            return ToolResult(
                content=f"No customer on file with the address {email or '(none given)'}."
            )
        fields = "\n".join(f"- {key}: {value}" for key, value in record.items())
        return ToolResult(content=f"Customer {email}:\n{fields}")
