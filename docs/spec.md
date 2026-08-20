# System spec

Ground truth for implementation tasks. If a task file and this file disagree,
this file wins. If both are silent, ask rather than invent.

## Contracts

Everything crossing a module boundary is a Pydantic model in
`compliance.schemas`. No dicts, no tuples.

```python
class Clause(BaseModel):
    clause_id: str            # "rbi-kyc-md:2016-amended:3.1.2"
    doc_id: str
    version: str
    jurisdiction: Literal["IN", "EU", "US", "GLOBAL"]
    framework: str            # "RBI" | "MiFID II" | "Basel III"
    clause_path: str          # "Chapter III > 3.1 > 3.1.2"
    text: str
    effective_from: date
    effective_to: date | None

class RetrievedClause(BaseModel):
    clause: Clause
    dense_score: float
    sparse_score: float
    rerank_score: float | None

class Citation(BaseModel):
    clause_id: str
    clause_path: str
    quote: str                # verbatim span from clause.text
    support: float            # 0..1 entailment score

class Answer(BaseModel):
    text: str
    citations: list[Citation]
    synthesised: bool         # False when we fell back to clauses only
    as_of: date

class RiskRating(StrEnum):
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"; BLOCKED = "blocked"

class ComplianceAssessment(BaseModel):
    txn_id: str
    risk_rating: RiskRating
    applicable_regulations: list[str]
    required_actions: list[str]
    citations: list[Citation]
    unresolved_questions: list[str]   # non-empty => insufficient information
    model_version: str
    prompt_version: str
```

## Rules that are not negotiable

1. A chunk without full provenance is never indexed. Missing `clause_path`
   is a hard failure, not a warning.
2. Retrieval always filters on `as_of` against `effective_from/effective_to`.
   Default `as_of` is today.
3. If mean citation support < `settings.min_citation_support`, return
   `Answer(synthesised=False)` carrying the retrieved clauses. Never generate
   an unattributed answer.
4. When the transaction payload lacks a field a regulation depends on, populate
   `unresolved_questions` and cap `risk_rating` at MEDIUM. Do not guess.
5. Nothing writes to Qdrant without a matching row in Postgres first.

## Postgres schema

```sql
create table documents (
  doc_id text primary key,
  framework text not null,
  jurisdiction text not null,
  title text not null,
  source_url text not null
);

create table document_versions (
  version_id text primary key,
  doc_id text not null references documents,
  version text not null,
  effective_from date not null,
  effective_to date,
  supersedes text references document_versions,
  sha256 text not null,
  object_key text not null,
  unique (doc_id, version)
);

create table clauses (
  clause_id text primary key,
  version_id text not null references document_versions,
  clause_path text not null,
  text text not null,
  parent_clause_id text references clauses
);

create table transactions (
  txn_id text primary key,
  payload jsonb not null,
  jurisdiction text not null,
  ingested_at timestamptz not null default now()
);

create table assessments (
  assessment_id uuid primary key default gen_random_uuid(),
  txn_id text not null references transactions,
  risk_rating text not null,
  summary text not null,
  model_version text not null,
  prompt_version text not null,
  created_at timestamptz not null default now()
);

create table assessment_citations (
  assessment_id uuid not null references assessments,
  clause_id text not null references clauses,
  support real not null,
  quote text not null
);

create table audit_events (
  event_id bigserial primary key,
  actor text not null,
  action text not null,
  subject_id text not null,
  payload jsonb not null,
  at timestamptz not null default now()
);

create table eval_runs (
  run_id uuid primary key default gen_random_uuid(),
  suite text not null,
  commit_sha text not null,
  faithfulness real, answer_relevance real,
  context_precision real, context_recall real,
  created_at timestamptz not null default now()
);
```

`audit_events` is append-only: revoke update and delete from the app role and
add a trigger that raises on either.

## Qdrant collection

Named vectors on one collection `regulations`:
- `dense` — 1024 dims, cosine (BGE-M3 dense)
- `sparse` — sparse vector (BGE-M3 lexical weights)

Payload mirrors `Clause` plus `effective_from`/`effective_to` as integer
timestamps so range filters work. Indexed payload fields: `jurisdiction`,
`framework`, `doc_id`, `effective_from`, `effective_to`.
