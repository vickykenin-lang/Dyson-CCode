-- Intelligence plane (cards B, C, Hermes), schema "intelligence". Step 7 of the execution plan.
-- Model identities, routes, acceptance bars, budgets, qualifications and every model call are
-- recorded append-only (LA-RTR-06). Configuration changes each carry the approval that allowed them.

CREATE SCHEMA intelligence;

CREATE TABLE intelligence.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- Approved models and their prices. Latest row per model_id wins; enabled=false retires a model.
CREATE TABLE intelligence.models (
    seq bigserial PRIMARY KEY,
    model_id text NOT NULL,
    spec jsonb NOT NULL,
    enabled boolean NOT NULL,
    approval_id uuid NOT NULL,
    at timestamptz NOT NULL
);

-- Founder-defined acceptance bar per task class (LA-RTR-02).
CREATE TABLE intelligence.acceptance_bars (
    seq bigserial PRIMARY KEY,
    task_class text NOT NULL,
    bar jsonb NOT NULL,
    approval_id uuid NOT NULL,
    at timestamptz NOT NULL
);

-- Founder-approved spend and token budgets per task class (LA-RTR-05).
CREATE TABLE intelligence.budgets (
    seq bigserial PRIMARY KEY,
    task_class text NOT NULL,
    budget jsonb NOT NULL,
    approval_id uuid NOT NULL,
    at timestamptz NOT NULL
);

-- Qualification runs: real task outcomes, latency and cost per model (LA-RTR-03).
CREATE TABLE intelligence.qualifications (
    seq bigserial PRIMARY KEY,
    model_id text NOT NULL,
    task_class text NOT NULL,
    record jsonb NOT NULL,
    at timestamptz NOT NULL
);

-- Every model call attempt. A "reserved" row holds the worst-case cost against the budget before
-- the model is called; the "ok" or "failed" row for the same attempt_id replaces it with the
-- actual cost. The model that served each attempt and the fallbacks tried are kept (LA-RTR-06).
CREATE TABLE intelligence.calls (
    seq bigserial PRIMARY KEY,
    attempt_id uuid NOT NULL,
    call_id uuid NOT NULL,
    attempt integer NOT NULL CHECK (attempt >= 1),
    caller text NOT NULL,
    task_class text NOT NULL,
    model_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('reserved', 'ok', 'failed')),
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cost numeric NOT NULL CHECK (cost >= 0),
    currency text NOT NULL,
    error text NOT NULL DEFAULT '',
    at timestamptz NOT NULL
);
CREATE INDEX calls_budget_idx ON intelligence.calls (task_class, currency, at);

CREATE FUNCTION intelligence.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'intelligence.%: rows are append-only', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['models', 'acceptance_bars', 'budgets', 'qualifications', 'calls'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON intelligence.%I
                        FOR EACH ROW EXECUTE FUNCTION intelligence.forbid_change()', t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON intelligence.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION intelligence.forbid_change()', t || '_no_truncate', t);
    END LOOP;
END $$;

INSERT INTO intelligence.schema_migrations (version) VALUES (1);
