"""One test per row of story 1.1's I/O & Edge-Case Matrix.

Each rejection test asserts both that the decision is refused and that the
stringified error names the offending field, because a retrying agent has only
that text to work from.
"""

import pytest
from pydantic import ValidationError

from triage_schema import TriageDecision

VALID = {
    "category": "billing",
    "priority": "P2",
    "route": "billing-team",
    "rationale": "Double charge is money at stake.",
}


def test_valid_decision_parses_and_round_trips():
    decision = TriageDecision(**VALID)
    assert decision.category == "billing"
    assert decision.priority == "P2"
    assert decision.route == "billing-team"
    assert decision.rationale == "Double charge is money at stake."
    assert decision.model_dump() == VALID


def test_missing_field_names_route():
    payload = {k: v for k, v in VALID.items() if k != "route"}
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**payload)
    message = str(exc.value)
    assert "route" in message
    assert "missing" in message.lower()


def test_extra_field_is_rejected_and_named():
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**VALID, confidence=0.9)
    message = str(exc.value)
    assert "confidence" in message
    assert "not permitted" in message.lower()


def test_priority_outside_the_set_lists_allowed_values():
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**{**VALID, "priority": "P5"})
    message = str(exc.value)
    assert "priority" in message
    for allowed in ("P1", "P2", "P3", "P4"):
        assert allowed in message


def test_unknown_category_lists_allowed_values():
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**{**VALID, "category": "refund"})
    message = str(exc.value)
    assert "category" in message
    for allowed in ("billing", "bug", "access", "performance", "how-to"):
        assert allowed in message


def test_wrong_type_priority_int_is_rejected():
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**{**VALID, "priority": 2})
    message = str(exc.value)
    assert "priority" in message
    for allowed in ("P1", "P2", "P3", "P4"):
        assert allowed in message


def test_wrong_type_rationale_int_names_the_expected_type():
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**{**VALID, "rationale": 5})
    message = str(exc.value)
    assert "rationale" in message
    assert "string" in message.lower()


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_empty_or_whitespace_rationale_is_rejected(blank):
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**{**VALID, "rationale": blank})
    message = str(exc.value)
    assert "rationale" in message
    assert "empty" in message.lower()


def test_json_schema_has_exactly_the_four_fields():
    """Epic 2 hands this model straight to LangChain as a structured-output schema."""
    schema = TriageDecision.model_json_schema()
    assert set(schema["properties"]) == {"category", "priority", "route", "rationale"}
    assert set(schema["required"]) == {"category", "priority", "route", "rationale"}


def test_assignment_after_construction_is_validated():
    """A caller applying the Enterprise priority bump must not be able to set a bad value."""
    decision = TriageDecision(**VALID)
    with pytest.raises(ValidationError) as exc:
        decision.priority = "P9"
    assert "priority" in str(exc.value)
    assert decision.priority == "P2"
    decision.priority = "P1"
    assert decision.priority == "P1"


def test_route_is_membership_only_not_matched_to_category():
    """Human decision, 2026-09-26: the category-to-route table is the agent's job, not the schema's."""
    decision = TriageDecision(**{**VALID, "route": "bug-team"})
    assert decision.route == "bug-team"
    assert decision.category == "billing"


def test_multi_sentence_rationale_with_abbreviation_is_accepted():
    """Human decision, 2026-09-26: no sentence-count check, so abbreviations never trip a false rejection."""
    rationale = "Cust. is on Enterprise. Money is at stake."
    decision = TriageDecision(**{**VALID, "rationale": rationale})
    assert decision.rationale == rationale


def test_padded_rationale_round_trips_unstripped():
    rationale = "  Double charge is money at stake.  "
    decision = TriageDecision(**{**VALID, "rationale": rationale})
    assert decision.model_dump()["rationale"] == rationale


def test_unknown_route_lists_allowed_values():
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**{**VALID, "route": "refund-team"})
    message = str(exc.value)
    assert "route" in message
    for allowed in ("billing-team", "bug-team", "access-team", "performance-team", "how-to-team"):
        assert allowed in message


@pytest.mark.parametrize("field", ["category", "route", "rationale"])
def test_explicit_null_is_rejected(field):
    """Structured output can emit an explicit null, which is distinct from omitting the key."""
    with pytest.raises(ValidationError) as exc:
        TriageDecision(**{**VALID, field: None})
    assert field in str(exc.value)


def test_json_round_trip():
    """Epic 3's valid_schema scorer may receive a JSON string rather than a dict."""
    decision = TriageDecision(**VALID)
    assert TriageDecision.model_validate_json(decision.model_dump_json()).model_dump() == VALID
