"use client";

import { useActionState } from "react";

import { CitationPanel } from "./citation-panel";
import { SubmitButton } from "./submit-button";
import { assessTransaction, initialScreenState } from "@/lib/actions";
import type { ComplianceAssessment } from "@/lib/api";

const EXAMPLE = `{
  "txn_id": "txn-1042",
  "amount": 250000,
  "currency": "USD",
  "counterparty_type": "corporate",
  "jurisdictions": ["IN", "US"],
  "instrument": "cross-border payment",
  "kyc_status": false,
  "high_risk_jurisdiction": true
}`;

function ItemList({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="result-section">
      <h2>{title}</h2>
      {items.length ? (
        <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : (
        <p className="empty-copy">None returned.</p>
      )}
    </section>
  );
}

function ScreenForm({ action }: { action: (formData: FormData) => void }) {
  return (
    <form action={action} className="input-card json-form">
      <label htmlFor="transaction">Transaction JSON</label>
      <textarea id="transaction" name="transaction" rows={14} required
        defaultValue={EXAMPLE} spellCheck={false} />
      <SubmitButton idle="Run screening" pending="Screening…" />
    </form>
  );
}

function AssessmentResult({ result }: { result: ComplianceAssessment }) {
  return (
    <div className="result-grid screening-result">
      <article className="assessment-card">
        <div className="assessment-heading">
          <div>
            <p className="eyebrow">Assessment · {result.txn_id}</p>
            <h2>Transaction review</h2>
          </div>
          <span className={`risk-badge risk-${result.risk_rating}`}>
            {result.risk_rating} risk
          </span>
        </div>
        <ItemList title="Applicable regulations" items={result.applicable_regulations} />
        <ItemList title="Required actions" items={result.required_actions} />
        <section className="result-section unresolved">
          <h2>Unresolved questions</h2>
          {result.unresolved_questions.length ? (
            <ul>{result.unresolved_questions.map((item) => <li key={item}>{item}</li>)}</ul>
          ) : <p className="empty-copy">No unresolved questions.</p>}
        </section>
      </article>
      <CitationPanel citations={result.citations} />
    </div>
  );
}

export function ScreenWorkspace() {
  const [state, action] = useActionState(assessTransaction, initialScreenState);
  return (
    <section className="workspace">
      <ScreenForm action={action} />
      {state.error ? <p className="error-banner" role="alert">{state.error}</p> : null}
      {state.result ? <AssessmentResult result={state.result} /> : null}
    </section>
  );
}
