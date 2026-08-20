import type { Citation } from "@/lib/api";

function effectiveRange(citation: Citation): string {
  if (!citation.effective_from) {
    return "Effective dates unavailable";
  }
  return `${citation.effective_from} — ${citation.effective_to ?? "current"}`;
}

export function CitationPanel({ citations }: { citations: Citation[] }) {
  return (
    <aside className="evidence-panel" aria-label="Cited clauses">
      <div className="panel-heading">
        <p className="eyebrow">Evidence</p>
        <span>{citations.length} cited</span>
      </div>
      {citations.length === 0 ? (
        <p className="empty-copy">No supporting clauses were returned.</p>
      ) : (
        <ol className="citation-list">
          {citations.map((citation, index) => (
            <li id={`citation-${index + 1}`} key={`${citation.clause_id}-${index}`}>
              <div className="citation-index">{String(index + 1).padStart(2, "0")}</div>
              <div>
                <h3>{citation.clause_path}</h3>
                <p className="effective-date">{effectiveRange(citation)}</p>
                <blockquote>{citation.quote}</blockquote>
                <p className="support">Support {Math.round(citation.support * 100)}%</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}
