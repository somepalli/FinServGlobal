"use client";

import { useActionState } from "react";

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
      <textarea id="question" name="question" rows={5} required
        placeholder="What due diligence is required for a high-risk cross-border payment?" />
      <div className="form-row">
        <label htmlFor="as_of">As of <span>(optional)</span></label>
        <input id="as_of" name="as_of" type="date" />
        <SubmitButton idle="Check regulations" pending="Checking…" />
      </div>
    </form>
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
  return (
    <section className="workspace">
      <QuestionForm action={action} />
      {state.error ? <p className="error-banner" role="alert">{state.error}</p> : null}
      {state.result ? <QueryResult result={state.result} /> : null}
    </section>
  );
}
