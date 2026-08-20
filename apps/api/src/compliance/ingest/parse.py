"""Convert regulator PDFs into a heading-preserving document tree."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError, DocumentLoadError
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.text import ListItem, SectionHeaderItem, TextItem
from docling_core.types.doc.labels import DocItemLabel

from compliance.schemas import DocumentNode, ParsedDocument

_NUMBER_PREFIX = re.compile(
    r"^\s*(?P<number>"
    r"Article\s+\d+(?:\([^)]+\))*"
    r"|¶\s*\d+[A-Za-z]?"
    r"|\(\d+[A-Za-z]?\)"
    r"|\d+(?:\.\d+)+"
    r"|\d+\."
    r")(?=\s|$)",
    flags=re.IGNORECASE,
)
_TEXT_LABELS = {DocItemLabel.PARAGRAPH, DocItemLabel.TEXT}


class DocumentParseError(RuntimeError):
    pass


@dataclass
class _StackEntry:
    level: int
    node: DocumentNode
    derived: bool


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _provision_number(text: str) -> str | None:
    match = _NUMBER_PREFIX.match(text)
    if match is None:
        return None
    number = _normalise_text(match.group("number"))
    return number[:-1] if number.endswith(".") else number


def _list_number(item: ListItem) -> str | None:
    if not item.enumerated:
        return None
    marker = _normalise_text(item.marker)
    return _provision_number(marker) or _provision_number(item.text)


def _text_number(item: TextItem) -> str | None:
    if isinstance(item, ListItem):
        return _list_number(item)
    if item.label not in _TEXT_LABELS:
        return None
    return _provision_number(item.text)


def _source_text(item: TextItem) -> str:
    text = _normalise_text(item.text)
    if not isinstance(item, ListItem) or not item.enumerated:
        return text
    marker = _normalise_text(item.marker)
    if not marker or text.startswith(marker):
        return text
    return f"{marker} {text}"


def _attach_node(
    roots: list[DocumentNode], stack: list[_StackEntry], node: DocumentNode, level: int
) -> None:
    while stack and stack[-1].level >= level:
        stack.pop()
    target = stack[-1].node.children if stack else roots
    target.append(node)


def _add_heading(
    roots: list[DocumentNode], stack: list[_StackEntry], item: SectionHeaderItem
) -> None:
    title = _normalise_text(item.text)
    if not title:
        return
    node = DocumentNode(title=title, number=_provision_number(title))
    _attach_node(roots, stack, node, item.level)
    stack.append(_StackEntry(level=item.level, node=node, derived=False))


def _add_derived_provision(
    roots: list[DocumentNode], stack: list[_StackEntry], text: str, number: str
) -> None:
    while stack and stack[-1].derived:
        stack.pop()
    level = stack[-1].level + 1 if stack else 1
    node = DocumentNode(title=text, number=number)
    _attach_node(roots, stack, node, level)
    stack.append(_StackEntry(level=level, node=node, derived=True))


def _append_content(root_content: list[str], stack: list[_StackEntry], content: str) -> None:
    if not content:
        return
    target = stack[-1].node.content if stack else root_content
    target.append(content)


def document_to_tree(document: DoclingDocument) -> ParsedDocument:
    roots: list[DocumentNode] = []
    root_content: list[str] = []
    stack: list[_StackEntry] = []
    for item, _level in document.iterate_items():
        if isinstance(item, SectionHeaderItem):
            _add_heading(roots, stack, item)
        elif isinstance(item, TableItem):
            if item.label == DocItemLabel.TABLE:
                _append_content(root_content, stack, item.export_to_markdown(document))
        elif isinstance(item, TextItem):
            text = _source_text(item)
            number = _text_number(item)
            if text and number is not None:
                _add_derived_provision(roots, stack, text, number)
            else:
                _append_content(root_content, stack, text)
    return ParsedDocument(title=document.name, content=root_content, children=roots)


@lru_cache(maxsize=1)
def _converter() -> DocumentConverter:
    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        force_backend_text=True,
        enable_remote_services=False,
        allow_external_plugins=False,
    )
    options.heading_hierarchy_options.enabled = True
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def parse_document(source: Path, *, page_range: tuple[int, int] | None = None) -> ParsedDocument:
    if not source.is_file():
        raise DocumentParseError(f"source document does not exist: {source}")
    try:
        if page_range is None:
            result = _converter().convert(source)
        else:
            result = _converter().convert(source, page_range=page_range)
    except (ConversionError, DocumentLoadError) as exc:
        raise DocumentParseError(f"failed to parse {source}: {exc}") from exc
    if result.status != ConversionStatus.SUCCESS:
        raise DocumentParseError(f"incomplete parse for {source}: {result.status.value}")
    return document_to_tree(result.document)
