import { ScreenWorkspace } from "@/components/screen-workspace";

export default function ScreenPage() {
  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <p className="eyebrow">Transaction controls</p>
        <h1>Screen a transaction before it moves.</h1>
        <p className="lede">
          Submit transaction facts and review the risk, actions, open questions,
          and supporting clauses together.
        </p>
      </section>
      <ScreenWorkspace />
    </main>
  );
}
