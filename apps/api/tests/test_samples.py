from pathlib import Path

from compliance.ingest.run import load_ingestion_manifest
from compliance.schemas import ComplianceAssessment, TransactionPayload


def test_committed_sample_outputs_cite_manifest_documents() -> None:
    root = Path(__file__).resolve().parents[3]
    sample_dir = root / "samples"
    manifest = load_ingestion_manifest(root / "data" / "corpus" / "manifest.yaml")
    inputs = sorted((sample_dir / "input").glob("*.json"))
    assert len(inputs) == 4
    expected_risks = {
        "complex-product": "high",
        "cross-border-payment": "high",
        "intra-group-derivative": "high",
        "nbfc-lending": "low",
    }

    summary = (sample_dir / "output" / "README.md").read_text(encoding="utf-8")
    for input_path in inputs:
        payload = TransactionPayload.model_validate_json(input_path.read_text(encoding="utf-8"))
        output_path = sample_dir / "output" / input_path.name
        assessment = ComplianceAssessment.model_validate_json(
            output_path.read_text(encoding="utf-8")
        )
        expected = [doc.doc_id for doc in manifest.documents if input_path.stem in doc.covers]
        assert len(expected) == 1
        assert assessment.txn_id == payload.txn_id
        assert assessment.risk_rating.value == expected_risks[input_path.stem]
        assert assessment.required_actions
        assert any(item.clause_id.startswith(f"{expected[0]}:") for item in assessment.citations)
        assert input_path.stem in summary
