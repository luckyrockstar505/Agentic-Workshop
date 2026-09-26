"""The one definition of a valid triage decision.

`TriageDecision` is the contract shared by the agent (Epic 2), which emits it as
LangChain structured output, and the eval (Epic 3), whose `valid_schema` scorer
validates agent output against it. The category, priority and route vocabularies
come from `TRIAGE_POLICY.md`.

A decision is valid when it has exactly the four fields `category`, `priority`,
`route` and `rationale`, each value is in its set, and the rationale is a
non-empty string. Anything else raises a `pydantic.ValidationError` naming the
offending field, so a retrying agent can tell what to fix.

`route` is checked for membership only: pairing a category with another team's
route is the agent's mistake to avoid via `TRIAGE_POLICY.md`, not the schema's to
catch. `rationale` is likewise checked only for being non-empty -- "one sentence"
stays prompt guidance and something the Epic 3 judge weighs.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = ["Category", "Priority", "Route", "TriageDecision"]

Category = Literal["billing", "bug", "access", "performance", "how-to"]
Priority = Literal["P1", "P2", "P3", "P4"]
Route = Literal["billing-team", "bug-team", "access-team", "performance-team", "how-to-team"]


class TriageDecision(BaseModel):
    """One triage decision: where a ticket belongs, how urgent it is and why."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    category: Category
    priority: Priority
    route: Route
    rationale: str

    @field_validator("rationale")
    @classmethod
    def _rationale_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must not be empty: give a one-sentence reason naming the rule applied")
        return value
