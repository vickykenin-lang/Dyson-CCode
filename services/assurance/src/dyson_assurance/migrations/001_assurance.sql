-- Assurance plane (cards E, F, H, J), schema "assurance". Step 6 of the execution plan.
-- Every table is append-only: verdicts, health, ledgers and matches are history, never rewritten.

CREATE SCHEMA assurance;

CREATE TABLE assurance.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- F: QA/QC ------------------------------------------------------------------------------
CREATE TABLE assurance.qa_standards (
    standard_id text NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    body jsonb NOT NULL,
    defined_at timestamptz NOT NULL,
    PRIMARY KEY (standard_id, version)
);

CREATE TABLE assurance.qa_verdicts (
    seq bigserial PRIMARY KEY,
    task_id uuid NOT NULL,
    receptor_id text,
    standard_id text NOT NULL,
    standard_version integer NOT NULL,
    technical_success boolean NOT NULL,
    fit_for_purpose boolean NOT NULL,
    findings jsonb NOT NULL,
    evidence_id uuid NOT NULL,
    at timestamptz NOT NULL,
    FOREIGN KEY (standard_id, standard_version) REFERENCES assurance.qa_standards
);
CREATE INDEX qa_verdicts_task_idx ON assurance.qa_verdicts (task_id, seq);

-- F and E: escalations received and raised ---------------------------------------------
CREATE TABLE assurance.escalations (
    seq bigserial PRIMARY KEY,
    source text NOT NULL,          -- receptor, qa, monitoring
    receptor_id text,
    task_id uuid,
    message text NOT NULL CHECK (message <> ''),
    at timestamptz NOT NULL
);

-- E: health -----------------------------------------------------------------------------
CREATE TABLE assurance.health (
    seq bigserial PRIMARY KEY,
    subject_kind text NOT NULL CHECK (subject_kind IN ('receptor', 'model', 'tool', 'core')),
    subject_id text NOT NULL,
    status text NOT NULL,
    report jsonb NOT NULL,
    at timestamptz NOT NULL
);
CREATE INDEX health_subject_idx ON assurance.health (subject_kind, subject_id, seq);

-- H: revenue, statements, reconciliation, payments --------------------------------------
CREATE TABLE assurance.revenue_reports (
    report_id uuid PRIMARY KEY,
    receptor_id text NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    amount numeric NOT NULL CHECK (amount >= 0),
    currency text NOT NULL,
    payment_method text NOT NULL,
    reference text NOT NULL DEFAULT '',
    reported_at timestamptz NOT NULL
);

-- Only what reconciliation needs is kept: no account numbers, no balances, no raw file.
CREATE TABLE assurance.statement_uploads (
    upload_id uuid PRIMARY KEY,
    file_sha256 text NOT NULL UNIQUE,
    period_start date NOT NULL,
    period_end date NOT NULL,
    uploaded_at timestamptz NOT NULL
);

CREATE TABLE assurance.statement_lines (
    line_id uuid PRIMARY KEY,
    upload_id uuid NOT NULL REFERENCES assurance.statement_uploads,
    line_date date NOT NULL,
    direction text NOT NULL CHECK (direction IN ('credit', 'debit')),
    amount numeric NOT NULL CHECK (amount > 0),
    currency text NOT NULL,
    reference text NOT NULL DEFAULT ''
);

CREATE TABLE assurance.reconciliations (
    seq bigserial PRIMARY KEY,
    report_id uuid NOT NULL REFERENCES assurance.revenue_reports,
    status text NOT NULL CHECK (status IN ('reported_not_final', 'final')),
    line_id uuid UNIQUE REFERENCES assurance.statement_lines,  -- one line proves one report
    upload_id uuid REFERENCES assurance.statement_uploads,
    evidence_id uuid,
    at timestamptz NOT NULL,
    CHECK ((status = 'final') = (line_id IS NOT NULL))
);

-- Money-out actions are recorded only with the Founder approval that allowed them.
CREATE TABLE assurance.payments (
    payment_id uuid PRIMARY KEY,
    receptor_id text NOT NULL,
    amount numeric NOT NULL CHECK (amount > 0),
    currency text NOT NULL,
    approval_id uuid NOT NULL,
    reference text NOT NULL DEFAULT '',
    recorded_at timestamptz NOT NULL
);

CREATE TABLE assurance.payment_matches (
    payment_id uuid PRIMARY KEY REFERENCES assurance.payments,
    line_id uuid NOT NULL UNIQUE REFERENCES assurance.statement_lines,
    at timestamptz NOT NULL
);

CREATE FUNCTION assurance.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'assurance.%: rows are append-only', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['qa_standards', 'qa_verdicts', 'escalations', 'health',
                             'revenue_reports', 'statement_uploads', 'statement_lines',
                             'reconciliations', 'payments', 'payment_matches'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON assurance.%I
                        FOR EACH ROW EXECUTE FUNCTION assurance.forbid_change()', t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON assurance.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION assurance.forbid_change()', t || '_no_truncate', t);
    END LOOP;
END $$;

INSERT INTO assurance.schema_migrations (version) VALUES (1);
