"use client";

import { useActionState, useEffect, useRef } from "react";
import { useFormStatus } from "react-dom";

import { CitationPanel } from "./citation-panel";
import { SubmitButton } from "./submit-button";
import { askQuestion } from "@/lib/actions";
import { initialQueryState } from "@/lib/action-state";
import type { Answer } from "@/lib/api";

function Markers({ count }: { count: number }) {
  return (
    <span className="citation-markers" aria-label={`${count} citations`}>
      {Array.from({ length: count }, (_, index) => (
        <sup key={index}>
          <a href={`#citation-${index + 1}`}>[{index + 1}]</a>
        </sup>
      ))}
    </span>
  );
}

function QuestionForm({ action }: { action: (formData: FormData) => void }) {
  return (
    <form action={action} className="input-card">
      <label htmlFor="question">Regulatory question</label>
      <p className="form-hint">
        Ask about a rule or obligation. For a decision about a specific transaction,
        use <a href="/screen">Transaction screening</a> and provide its details.
      </p>
      <textarea id="question" name="question" rows={5} required
        placeholder="What due diligence is required for a high-risk cross-border payment?" />
      <div className="form-row">
        <label htmlFor="as_of">As of <span>(optional)</span></label>
        <input id="as_of" name="as_of" type="date" />
        <SubmitButton idle="Check regulations" pending="Checking…" />
      </div>
      <QueryProgress />
    </form>
  );
}

function QueryProgress() {
  const { pending } = useFormStatus();
  if (!pending) return null;
  return (
    <div className="query-progress" role="status" aria-live="polite">
      <span className="progress-spinner" aria-hidden="true" />
      <div>
        <strong>Searching and checking regulatory clauses…</strong>
        <p>This local analysis can take a few minutes. Keep this page open.</p>
      </div>
    </div>
  );
}

function QueryResult({ result }: { result: Answer }) {
  const paragraphs = result.text.split(/\n\n+/);
  return (
    <div className="result-grid">
      <article className="answer-card">
        <div className="result-meta">
          <span>As of {result.as_of}</span>
          <span>{result.synthesised ? "Supported answer" : "Source clauses only"}</span>
        </div>
        {!result.synthesised ? (
          <div className="support-warning">
            <strong>Not enough support to answer.</strong>
            <p>Review the retrieved clauses before reaching a conclusion.</p>
          </div>
        ) : (
          <div className="answer-text">
            {paragraphs.map((paragraph, index) => <p key={index}>{paragraph}
              {index === paragraphs.length - 1 ? <Markers count={result.citations.length} /> : null}
            </p>)}
          </div>
        )}
      </article>
      <CitationPanel citations={result.citations} />
    </div>
  );
}

export function QuestionWorkspace() {
  const [state, action] = useActionState(askQuestion, initialQueryState);
  const resultRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (state.error || state.result) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [state]);
  return (
    <section className="workspace">
      <QuestionForm action={action} />
      <div ref={resultRef} className="result-anchor">
        {state.error ? <p className="error-banner" role="alert">{state.error}</p> : null}
        {state.result ? <QueryResult result={state.result} /> : null}
      </div>
    </section>
  );
}
