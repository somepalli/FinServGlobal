import { getPostureReport } from "@/lib/api";

type ReportPageProps = {
  searchParams: Promise<{ start?: string; end?: string }>;
};

function movement(current: number, previous: number): string {
  const difference = current - previous;
  if (difference === 0) return "No change";
  return `${difference > 0 ? "+" : ""}${difference} vs prior period`;
}

export default async function ReportPage({ searchParams }: ReportPageProps) {
  const { start, end } = await searchParams;
  const report = await getPostureReport(start, end);

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <p className="eyebrow">Compliance oversight</p>
        <h1>Posture, backed by recorded decisions.</h1>
        <p className="lede">
          Counts and movement are calculated from the append-only audit record.
          Generated commentary is kept separate from reported figures.
        </p>
      </section>

      <form className="report-filter">
        <label>From <input name="start" type="date" defaultValue={report.period.start} /></label>
        <label>To <input name="end" type="date" defaultValue={report.period.end} /></label>
        <button type="submit">Update report</button>
      </form>

      <section className="metric-grid" aria-label="Compliance activity">
        <article className="metric-card">
          <span>Regulatory queries</span>
          <strong>{report.activity.regulatory_queries}</strong>
          <small>{movement(report.activity.regulatory_queries, report.previous_activity.regulatory_queries)}</small>
        </article>
        <article className="metric-card">
          <span>Transactions screened</span>
          <strong>{report.activity.transaction_screenings}</strong>
          <small>{movement(report.activity.transaction_screenings, report.previous_activity.transaction_screenings)}</small>
        </article>
        <article className="metric-card">
          <span>Unresolved screenings</span>
          <strong>{report.unresolved_screenings}</strong>
          <small>Requires human follow-up</small>
        </article>
      </section>

      <section className="report-grid">
        <article className="report-card">
          <p className="eyebrow">Risk distribution</p>
          <ul className="risk-distribution">
            {report.risk_distribution.map((item) => (
              <li key={item.risk_rating}>
                <span className={`risk-badge risk-${item.risk_rating}`}>{item.risk_rating}</span>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ul>
          {!report.risk_distribution.length && <p className="empty-copy">No recorded screenings in this period.</p>}
        </article>
        <article className="report-card generated-commentary">
          <p className="eyebrow">Generated commentary</p>
          <h2>Interpretation, not reported figures</h2>
          <p>{report.commentary ?? "Commentary was withheld. Refer to the SQL-derived figures."}</p>
          <small>The model cannot add numbers to this section.</small>
        </article>
      </section>
    </main>
  );
}
