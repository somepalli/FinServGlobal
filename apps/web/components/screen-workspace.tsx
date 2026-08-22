"use client";

import { useActionState, useState } from "react";

import { CitationPanel } from "./citation-panel";
import { SubmitButton } from "./submit-button";
import { assessTransaction, assessTransactionDescription } from "@/lib/actions";
import { initialScreenState } from "@/lib/action-state";
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

const DESCRIPTION_EXAMPLE =
  "Cross-border payment of $2M to a non-KYC entity in a high-risk jurisdiction.";

function DescriptionForm({ action }: { action: (formData: FormData) => void }) {
  return (
    <form action={action} className="input-card">
      <label htmlFor="description">Transaction description</label>
      <p className="form-hint">
        Describe the transaction in plain English. The compliance agent extracts
        the transaction facts, then runs the same screening pipeline as the
        structured form.
      </p>
      <textarea id="description" name="description" rows={5} required
        placeholder={DESCRIPTION_EXAMPLE} />
      <SubmitButton idle="Run screening" pending="Screening…" />
    </form>
  );
}

function JsonForm({ action }: { action: (formData: FormData) => void }) {
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

type ScreenMode = "describe" | "json";

function ModeToggle({ mode, onChange }: { mode: ScreenMode; onChange: (mode: ScreenMode) => void }) {
  return (
    <div className="mode-toggle" role="tablist" aria-label="Transaction input mode">
      <button type="button" role="tab" aria-selected={mode === "describe"}
        className={mode === "describe" ? "active" : ""} onClick={() => onChange("describe")}>
        Describe transaction
      </button>
      <button type="button" role="tab" aria-selected={mode === "json"}
        className={mode === "json" ? "active" : ""} onClick={() => onChange("json")}>
        Transaction JSON
      </button>
    </div>
  );
}

export function ScreenWorkspace() {
  const [mode, setMode] = useState<ScreenMode>("describe");
  const [descriptionState, descriptionAction] = useActionState(
    assessTransactionDescription,
    initialScreenState,
  );
  const [jsonState, jsonAction] = useActionState(assessTransaction, initialScreenState);
  const state = mode === "describe" ? descriptionState : jsonState;
  return (
    <section className="workspace">
      <ModeToggle mode={mode} onChange={setMode} />
      {mode === "describe" ? (
        <DescriptionForm action={descriptionAction} />
      ) : (
        <JsonForm action={jsonAction} />
      )}
      {state.error ? <p className="error-banner" role="alert">{state.error}</p> : null}
      {state.result ? <AssessmentResult result={state.result} /> : null}
    </section>
  );
}
