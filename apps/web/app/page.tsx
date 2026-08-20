import { QuestionWorkspace } from "@/components/question-workspace";

export default function QueryPage() {
  return (
    <main className="page-shell">
      <section className="hero">
        <p className="eyebrow">Regulatory intelligence</p>
        <h1>Ask the corpus. Check the evidence.</h1>
        <p className="lede">
          Receive an answer grounded in effective regulatory clauses, with every
          source kept beside the conclusion.
        </p>
      </section>
      <QuestionWorkspace />
    </main>
  );
}
