-- Governed Tool Hub (card G), schema "toolhub". Step 4 of the execution plan.
-- Every decision, execution and kill switch is recorded; nothing is ever updated or deleted.

CREATE SCHEMA toolhub;

CREATE TABLE toolhub.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- One row per evaluated call, allowed or denied (LA-TOOL-04).
CREATE TABLE toolhub.decisions (
    seq bigserial PRIMARY KEY,
    call_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    caller text,
    allowed boolean NOT NULL,
    decision jsonb NOT NULL,
    request jsonb NOT NULL,
    decided_at timestamptz NOT NULL
);

-- At most one execution per idempotency key: a retry never runs the action twice.
CREATE TABLE toolhub.executions (
    idempotency_key text PRIMARY KEY,
    call_id uuid NOT NULL,
    receptor_id text,
    tool_id text NOT NULL,
    amount numeric NOT NULL DEFAULT 0,
    currency text,
    claimed_at timestamptz NOT NULL
);

CREATE TABLE toolhub.outcomes (
    idempotency_key text PRIMARY KEY REFERENCES toolhub.executions,
    status text NOT NULL CHECK (status IN ('executed', 'failed')),
    result jsonb,
    error text NOT NULL DEFAULT '',
    finished_at timestamptz NOT NULL
);

CREATE TABLE toolhub.switches (
    seq bigserial PRIMARY KEY,
    target_kind text NOT NULL CHECK (target_kind IN ('tool', 'connector')),
    target_id text NOT NULL,
    killed boolean NOT NULL,
    reason text NOT NULL,
    approval_id uuid,
    at timestamptz NOT NULL,
    CHECK (killed OR approval_id IS NOT NULL)  -- reviving needs an approval
);

CREATE FUNCTION toolhub.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'toolhub.%: rows are append-only', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['decisions', 'executions', 'outcomes', 'switches'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON toolhub.%I
                        FOR EACH ROW EXECUTE FUNCTION toolhub.forbid_change()', t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON toolhub.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION toolhub.forbid_change()', t || '_no_truncate', t);
    END LOOP;
END $$;

INSERT INTO toolhub.schema_migrations (version) VALUES (1);
