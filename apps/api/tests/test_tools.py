from compliance.agent.tools import _risk_rating
from compliance.schemas import RiskRating, TransactionFacts


def _facts(**overrides: object) -> TransactionFacts:
    defaults: dict[str, object] = {
        "txn_id": "txn-1",
        "amount": None,
        "currency": "EUR",
        "counterparty_type": "corporate",
        "jurisdictions": ["IN"],
        "instrument": "cross-border payment",
        "kyc_status": None,
        "missing_fields": [],
    }
    defaults.update(overrides)
    return TransactionFacts(**defaults)  # type: ignore[arg-type]


def test_confirmed_kyc_failure_stays_high_even_with_missing_fields() -> None:
    facts = _facts(kyc_status=False, missing_fields=["currency"])

    assert _risk_rating(facts) is RiskRating.HIGH


def test_confirmed_large_exposure_breach_stays_high_with_missing_fields() -> None:
    facts = _facts(large_exposure_threshold_exceeded=True, missing_fields=["instrument"])

    assert _risk_rating(facts) is RiskRating.HIGH


def test_missing_fields_alone_is_medium() -> None:
    facts = _facts(missing_fields=["kyc_status"])

    assert _risk_rating(facts) is RiskRating.MEDIUM


def test_no_signals_and_no_missing_fields_is_low() -> None:
    facts = _facts(kyc_status=True)

    assert _risk_rating(facts) is RiskRating.LOW
