-- Orchestrator (card D), schema "orchestrator". Step 5 of the execution plan.
-- tasks is the durable queue (current state, updated in place);
-- transitions is the append-only history of every state change.

CREATE SCHEMA orchestrator;

CREATE TABLE orchestrator.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE orchestrator.tasks (
    task_id uuid PRIMARY KEY,
    -- The caller's key for the instruction: re-sending the same command finds the same task.
    instruction_key text NOT NULL UNIQUE,
    instruction text NOT NULL CHECK (instruction <> ''),
    receptor_id text CHECK (receptor_id ~ '^(T0|R[1-9][0-9]*)$'),
    plan jsonb NOT NULL,
    state text NOT NULL,
    attempt integer NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    consecutive_qa_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_qa_failures >= 0),
    approval_id uuid,
    hold_reason text CHECK (hold_reason IN ('control', 'qa')),
    control_scope text,           -- 'master' or a Receptor ID, for tasks stopped or paused
    resume_to text,               -- the state STOP or PAUSE interrupted (D-007)
    escalated boolean NOT NULL DEFAULT false,
    last_error text NOT NULL DEFAULT '',
    evidence_ids jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX tasks_state_idx ON orchestrator.tasks (state, updated_at);

CREATE TABLE orchestrator.transitions (
    seq bigserial PRIMARY KEY,
    task_id uuid NOT NULL REFERENCES orchestrator.tasks,
    from_state text,
    to_state text NOT NULL,
    trigger text,
    actor text NOT NULL,
    reason text NOT NULL DEFAULT '',
    at timestamptz NOT NULL
);
CREATE INDEX transitions_task_idx ON orchestrator.transitions (task_id, seq);

CREATE FUNCTION orchestrator.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'orchestrator.transitions is append-only' USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER transitions_append_only BEFORE UPDATE OR DELETE ON orchestrator.transitions
    FOR EACH ROW EXECUTE FUNCTION orchestrator.forbid_change();
CREATE TRIGGER transitions_no_truncate BEFORE TRUNCATE ON orchestrator.transitions
    FOR EACH STATEMENT EXECUTE FUNCTION orchestrator.forbid_change();

-- Tasks are never deleted; closed is a state, not a removal.
CREATE FUNCTION orchestrator.forbid_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'orchestrator.tasks rows are never deleted' USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER tasks_no_delete BEFORE DELETE ON orchestrator.tasks
    FOR EACH ROW EXECUTE FUNCTION orchestrator.forbid_delete();
CREATE TRIGGER tasks_no_truncate BEFORE TRUNCATE ON orchestrator.tasks
    FOR EACH STATEMENT EXECUTE FUNCTION orchestrator.forbid_delete();

INSERT INTO orchestrator.schema_migrations (version) VALUES (1);
