from datetime import date
from pathlib import Path

import pytest
from compliance.ingest.chunk import chunk_document
from compliance.ingest.parse import document_to_tree, parse_document
from compliance.schemas import DocumentMetadata
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.table.table_data import TableCell, TableData
from docling_core.types.doc.labels import DocItemLabel, GroupLabel


def _table_data() -> TableData:
    values = (("Control", "Owner"), ("CDD", "Compliance"))
    cells = [
        TableCell(
            text=text,
            start_row_offset_idx=row,
            end_row_offset_idx=row + 1,
            start_col_offset_idx=column,
            end_col_offset_idx=column + 1,
            column_header=row == 0,
        )
        for row, values_row in enumerate(values)
        for column, text in enumerate(values_row)
    ]
    return TableData(table_cells=cells, num_rows=2, num_cols=2)


def test_builds_heading_tree_and_keeps_table_with_owning_clause() -> None:
    source = DoclingDocument(name="fixture")
    chapter = source.add_heading("CHAPTER III", level=1)
    section = source.add_heading("Customer Due Diligence", level=2, parent=chapter)
    clause = source.add_heading("10. Customer Acceptance Policy", level=3, parent=section)
    source.add_text(
        DocItemLabel.PARAGRAPH,
        "A regulated entity must document its controls.",
        parent=clause,
    )
    source.add_table(_table_data(), parent=clause)

    parsed = document_to_tree(source)
    clause_node = parsed.children[0].children[0].children[0]

    assert clause_node.number == "10"
    assert clause_node.title == "10. Customer Acceptance Policy"
    assert any("Control" in block and "Compliance" in block for block in clause_node.content)


def test_promotes_numbered_list_items_to_provisions() -> None:
    source = DoclingDocument(name="fixture")
    chapter = source.add_heading("CHAPTER I", level=1)
    list_group = source.add_group(GroupLabel.LIST, parent=chapter)
    source.add_list_item(
        "Definitions apply to every regulated entity.",
        enumerated=True,
        marker="3.",
        parent=list_group,
    )

    parsed = document_to_tree(source)

    assert parsed.children[0].children[0].number == "3"
    assert parsed.children[0].children[0].title.startswith("3.")


_RBI_PDF = Path(__file__).resolve().parents[3] / "data" / "corpus" / "rbi-kyc-md.pdf"


@pytest.mark.skipif(not _RBI_PDF.exists(), reason="RBI corpus PDF is not checked in")
def test_rbi_page_emits_known_clause_numbers() -> None:
    parsed = parse_document(_RBI_PDF, page_range=(4, 4))
    metadata = DocumentMetadata(
        doc_id="rbi-kyc-md",
        version="2016-amended",
        jurisdiction="IN",
        framework="RBI",
        effective_from=date(2016, 2, 25),
    )

    clauses = chunk_document(parsed, metadata, min_tokens=0)
    numbers = {clause.clause_path.rpartition(" > ")[2].partition("#part")[0] for clause in clauses}

    assert {"1", "2", "3"}.issubset(numbers)
    assert all(clause.clause_path.strip() for clause in clauses)
