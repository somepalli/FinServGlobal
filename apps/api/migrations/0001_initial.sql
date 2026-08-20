CREATE TABLE documents (
    doc_id text PRIMARY KEY,
    framework text NOT NULL,
    jurisdiction text NOT NULL,
    title text NOT NULL,
    source_url text NOT NULL
);

CREATE TABLE document_versions (
    version_id text PRIMARY KEY,
    doc_id text NOT NULL REFERENCES documents,
    version text NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    supersedes text REFERENCES document_versions,
    sha256 text NOT NULL,
    object_key text NOT NULL,
    UNIQUE (doc_id, version)
);

CREATE TABLE clauses (
    clause_id text PRIMARY KEY,
    version_id text NOT NULL REFERENCES document_versions,
    clause_path text NOT NULL,
    text text NOT NULL,
    parent_clause_id text REFERENCES clauses
);

CREATE TABLE transactions (
    txn_id text PRIMARY KEY,
    payload jsonb NOT NULL,
    jurisdiction text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assessments (
    assessment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    txn_id text NOT NULL REFERENCES transactions,
    risk_rating text NOT NULL,
    summary text NOT NULL,
    model_version text NOT NULL,
    prompt_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assessment_citations (
    assessment_id uuid NOT NULL REFERENCES assessments,
    clause_id text NOT NULL REFERENCES clauses,
    support real NOT NULL,
    quote text NOT NULL
);

CREATE TABLE audit_events (
    event_id bigserial PRIMARY KEY,
    actor text NOT NULL,
    action text NOT NULL,
    subject_id text NOT NULL,
    payload jsonb NOT NULL,
    at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION reject_audit_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = '55000',
        MESSAGE = 'audit_events is append-only';
    RETURN NULL;
END;
$$;

CREATE TRIGGER audit_events_are_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();

REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC, CURRENT_USER;

CREATE TABLE eval_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    suite text NOT NULL,
    commit_sha text NOT NULL,
    faithfulness real,
    answer_relevance real,
    context_precision real,
    context_recall real,
    created_at timestamptz NOT NULL DEFAULT now()
);
