from datetime import date

import pytest
from compliance.ingest.chunk import ChunkingError, chunk_document, embedding_text
from compliance.schemas import DocumentMetadata, DocumentNode, ParsedDocument


def _metadata() -> DocumentMetadata:
    return DocumentMetadata(
        doc_id="rbi-kyc-md",
        version="2016-amended",
        jurisdiction="IN",
        framework="RBI",
        effective_from=date(2016, 2, 25),
    )


def _document(*children: DocumentNode) -> ParsedDocument:
    return ParsedDocument(title="RBI KYC", children=list(children))


def test_emits_only_the_smallest_numbered_provision() -> None:
    provision = DocumentNode(
        title="3.1 Record keeping",
        number="3.1",
        content=["Introductory wording owned by the parent."],
        children=[
            DocumentNode(
                title="3.1.2 Retention period",
                number="3.1.2",
                content=["Records must be retained for five years."],
            )
        ],
    )
    chapter = DocumentNode(title="Chapter III", children=[provision])

    clauses = chunk_document(_document(chapter), _metadata(), min_tokens=0)

    assert [clause.clause_path for clause in clauses] == ["Chapter III > 3.1 > 3.1.2"]
    assert "Introductory wording" not in clauses[0].text


def test_merges_a_short_clause_with_its_following_sibling() -> None:
    chapter = DocumentNode(
        title="Chapter I",
        children=[
            DocumentNode(title="10. Notice", number="10", content=["Give notice."]),
            DocumentNode(
                title="11. Records",
                number="11",
                content=["Records must remain available for inspection."],
            ),
        ],
    )

    clauses = chunk_document(_document(chapter), _metadata(), min_tokens=20, max_tokens=100)

    assert len(clauses) == 1
    assert clauses[0].clause_path == "Chapter I > 10 + 11"
    assert "10. Notice" in clauses[0].text
    assert "11. Records" in clauses[0].text


def test_splits_long_clauses_without_cutting_sentences() -> None:
    sentences = [
        "The first control records every approved account.",
        "The second control checks every retained identity.",
        "The third control reports every unresolved exception.",
    ]
    chapter = DocumentNode(
        title="Chapter I",
        children=[
            DocumentNode(
                title="12. Ongoing controls.",
                number="12",
                content=[" ".join(sentences)],
            )
        ],
    )

    clauses = chunk_document(_document(chapter), _metadata(), min_tokens=0, max_tokens=12)

    assert len(clauses) > 1
    assert clauses[0].clause_path == "Chapter I > 12"
    assert clauses[1].clause_path == "Chapter I > 12#part2"
    for sentence in sentences:
        assert sum(sentence in clause.text for clause in clauses) == 1


def test_combines_article_and_paragraph_numbers() -> None:
    article = DocumentNode(
        title="Article 25",
        number="Article 25",
        children=[
            DocumentNode(
                title="(2) Processing safeguards",
                number="(2)",
                content=["Processing must use appropriate safeguards."],
            )
        ],
    )

    clauses = chunk_document(_document(article), _metadata(), min_tokens=0)

    assert clauses[0].clause_path == "Article 25(2)"


def test_embedding_text_does_not_replace_raw_citation_text() -> None:
    node = DocumentNode(
        title="52. Monitoring",
        number="52",
        content=["Monitor the relationship."],
    )
    clause = chunk_document(_document(node), _metadata(), min_tokens=0)[0]

    assert clause.text.startswith("52. Monitoring")
    assert embedding_text(clause) == f"{clause.clause_path}\n\n{clause.text}"


def test_document_without_numbered_provisions_is_rejected() -> None:
    document = _document(DocumentNode(title="Unnumbered guidance"))

    with pytest.raises(ChunkingError, match="no numbered clauses"):
        chunk_document(document, _metadata())
