"""A fixed service registry, so a reviewer's claims can be checked against something.

Every fact a worker states about a service is either in here or invented. That
is the whole point: this package exists to find out whether a fan-out, a join
and a grader can produce an answer that is *wrong in a way nothing reports*.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from openstategraph.abc import BaseTool, ToolResult

SERVICES: dict[str, dict[str, str]] = {
    "checkout-api": {
        "owner": "payments-team",
        "oncall": "Ada Okonkwo",
        "slo": "99.95% availability, p99 400ms",
        "depends_on": "ledger-svc, fraud-scoring, session-cache",
        "depended_on_by": "storefront-web, mobile-bff",
        "data_class": "PCI cardholder data",
        "deploy": "blue-green, 12 releases/week",
    },
    "ledger-svc": {
        "owner": "payments-team",
        "oncall": "Ada Okonkwo",
        "slo": "99.99% availability, p99 120ms",
        "depends_on": "postgres-primary",
        "depended_on_by": "checkout-api, refunds-worker, finance-export",
        "data_class": "financial records, 7-year retention",
        "deploy": "rolling, 2 releases/week, change-advisory-board gated",
    },
    "session-cache": {
        "owner": "platform-team",
        "oncall": "Bo Lindqvist",
        "slo": "99.9% availability, p99 8ms",
        "depends_on": "redis-cluster-eu",
        "depended_on_by": "checkout-api, storefront-web",
        "data_class": "session tokens, no PII at rest",
        "deploy": "rolling, 5 releases/week",
    },
    "fraud-scoring": {
        "owner": "risk-team",
        "oncall": "Chidi Vasquez",
        "slo": "99.5% availability, p99 900ms",
        "depends_on": "feature-store, model-registry",
        "depended_on_by": "checkout-api",
        "data_class": "derived behavioural features",
        "deploy": "canary, 1 release/week",
    },
}


class RegistryArgs(BaseModel):
    service: str = Field(description="The exact service name, e.g. checkout-api.")


class ServiceRegistryTool(BaseTool):
    """Returns the registry record for one service, by exact name."""

    name = "service_registry"
    side_effecting = False
    node_type = "tool.service-registry"
    description = (
        "Look up one service in the service registry by its exact name. Returns "
        "its owning team, on-call engineer, SLO, what it depends on, what depends "
        "on it, its data classification and its deployment style. Known services: "
        "checkout-api, ledger-svc, session-cache, fraud-scoring. Returns nothing "
        "for any other name."
    )
    Args = RegistryArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        key = str(getattr(args, "service", "")).strip().lower()
        record = SERVICES.get(key)
        if record is None:
            return ToolResult(
                content=(
                    f"No service named {key or '(none given)'} is in the registry. "
                    "The registry holds only: checkout-api, ledger-svc, "
                    "session-cache, fraud-scoring."
                )
            )
        fields = "\n".join(f"- {k}: {v}" for k, v in record.items())
        return ToolResult(content=f"Service {key}:\n{fields}")
