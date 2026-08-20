"""Turn a parsed regulation tree into citation-sized clauses."""

import re
from dataclasses import dataclass

from compliance.schemas import Clause, DocumentMetadata, DocumentNode, ParsedDocument

_TOKEN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'“])")
_ARTICLE = re.compile(r"^Article\s+\d+(?:\([^)]+\))*$", flags=re.IGNORECASE)
_SIMPLE_NUMBER = re.compile(r"^\(?(\d+[A-Za-z]?)\)?$", flags=re.IGNORECASE)


class ChunkingError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Candidate:
    path: str
    text: str


def count_tokens(text: str) -> int:
    """Count deterministic lexical tokens without calling an external service."""
    return len(_TOKEN.findall(text))


def embedding_text(clause: Clause) -> str:
    """Add provenance for embedding while leaving the cited text unchanged."""
    return f"{clause.clause_path}\n\n{clause.text}"


def _has_numbered_descendant(node: DocumentNode) -> bool:
    for child in node.children:
        if child.number is not None or _has_numbered_descendant(child):
            return True
    return False


def _unnumbered_content(node: DocumentNode) -> list[str]:
    content = list(node.content)
    for child in node.children:
        if child.number is None:
            content.append(child.title)
            content.extend(_unnumbered_content(child))
    return content


def _extend_path(parts: tuple[str, ...], component: str) -> tuple[str, ...]:
    paragraph = _SIMPLE_NUMBER.fullmatch(component)
    if parts and _ARTICLE.fullmatch(parts[-1]) and paragraph:
        return (*parts[:-1], f"{parts[-1]}({paragraph.group(1)})")
    return (*parts, component)


def _node_path(parts: tuple[str, ...], node: DocumentNode) -> tuple[str, ...]:
    component = node.number or node.title
    return _extend_path(parts, component)


def _candidate_text(node: DocumentNode) -> str:
    blocks = [node.title, *_unnumbered_content(node)]
    return "\n\n".join(block.strip() for block in blocks if block.strip())


def _collect_candidates(
    nodes: list[DocumentNode], parts: tuple[str, ...], output: list[_Candidate]
) -> None:
    for node in nodes:
        path_parts = _node_path(parts, node)
        if node.number is not None and not _has_numbered_descendant(node):
            output.append(_Candidate(path=" > ".join(path_parts), text=_candidate_text(node)))
        else:
            _collect_candidates(node.children, path_parts, output)


def _parent_path(path: str) -> str:
    return path.rpartition(" > ")[0]


def _merge_short(candidates: list[_Candidate], minimum: int) -> list[_Candidate]:
    merged: list[_Candidate] = []
    index = 0
    while index < len(candidates):
        current = candidates[index]
        following = candidates[index + 1] if index + 1 < len(candidates) else None
        same_parent = following is not None and _parent_path(current.path) == _parent_path(
            following.path
        )
        if count_tokens(current.text) < minimum and following is not None and same_parent:
            parent = _parent_path(current.path)
            numbers = f"{current.path.rpartition(' > ')[2]} + {following.path.rpartition(' > ')[2]}"
            path = f"{parent} > {numbers}" if parent else numbers
            merged.append(_Candidate(path=path, text=f"{current.text}\n\n{following.text}"))
            index += 2
        else:
            merged.append(current)
            index += 1
    return merged


def _sentence_units(text: str) -> list[str]:
    units: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines and all(line.startswith("|") for line in lines):
            units.append("\n".join(lines))
        else:
            units.extend(part.strip() for part in _SENTENCE_BOUNDARY.split(block))
    return [unit for unit in units if unit]


def _split_candidate(candidate: _Candidate, maximum: int) -> list[_Candidate]:
    units = _sentence_units(candidate.text)
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = count_tokens(unit)
        if current and current_tokens + unit_tokens > maximum:
            parts.append(" ".join(current))
            current = []
            current_tokens = 0
        current.append(unit)
        current_tokens += unit_tokens
    if current:
        parts.append(" ".join(current))
    return [
        _Candidate(
            path=candidate.path if index == 1 else f"{candidate.path}#part{index}",
            text=part,
        )
        for index, part in enumerate(parts, start=1)
    ]


def _clause_id(metadata: DocumentMetadata, path: str) -> str:
    suffix = path.rpartition(" > ")[2]
    suffix = re.sub(r"\s+", "", suffix)
    return f"{metadata.doc_id}:{metadata.version}:{suffix}"


def _to_clause(candidate: _Candidate, metadata: DocumentMetadata) -> Clause:
    return Clause(
        clause_id=_clause_id(metadata, candidate.path),
        doc_id=metadata.doc_id,
        version=metadata.version,
        jurisdiction=metadata.jurisdiction,
        framework=metadata.framework,
        clause_path=candidate.path,
        text=candidate.text,
        effective_from=metadata.effective_from,
        effective_to=metadata.effective_to,
    )


def _validate_limits(minimum: int, maximum: int) -> None:
    if minimum < 0:
        raise ChunkingError("minimum token count cannot be negative")
    if maximum < 1:
        raise ChunkingError("maximum token count must be positive")
    if minimum >= maximum and minimum != 0:
        raise ChunkingError("minimum token count must be less than maximum")


def chunk_document(
    document: ParsedDocument,
    metadata: DocumentMetadata,
    *,
    min_tokens: int = 80,
    max_tokens: int = 800,
) -> list[Clause]:
    """Emit the smallest numbered provisions from a parsed document tree."""
    _validate_limits(min_tokens, max_tokens)
    candidates: list[_Candidate] = []
    _collect_candidates(document.children, (), candidates)
    if not candidates:
        raise ChunkingError("document produced no numbered clauses")
    merged = _merge_short(candidates, min_tokens)
    split = [part for item in merged for part in _split_candidate(item, max_tokens)]
    if any(not item.path.strip() or not item.text.strip() for item in split):
        raise ChunkingError("document produced an empty clause path or text")
    clauses = [_to_clause(item, metadata) for item in split]
    identifiers = {clause.clause_id for clause in clauses}
    if len(identifiers) != len(clauses):
        raise ChunkingError("document produced duplicate clause identifiers")
    return clauses
