from datetime import date

import pytest
from compliance.schemas import Citation, Clause, RiskRating
from pydantic import ValidationError


def test_clause_preserves_required_provenance() -> None:
    clause = Clause(
        clause_id="rbi-kyc-md:2016-amended:3.1.2",
        doc_id="rbi-kyc-md",
        version="2016-amended",
        jurisdiction="IN",
        framework="RBI",
        clause_path="Chapter III > 3.1 > 3.1.2",
        text="A regulated entity must retain the record.",
        effective_from=date(2016, 2, 25),
        effective_to=None,
    )

    assert clause.clause_path == "Chapter III > 3.1 > 3.1.2"
    assert clause.effective_to is None


def test_citation_support_must_be_a_probability() -> None:
    with pytest.raises(ValidationError):
        Citation(clause_id="c1", clause_path="1", quote="text", support=1.01)


def test_risk_rating_values_match_persisted_contract() -> None:
    assert [rating.value for rating in RiskRating] == ["low", "medium", "high", "blocked"]
