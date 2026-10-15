-- Integration schema: which Founder thread started which task, so a reconnecting app gets its
-- tasks back (LA-APP-05). Append-only.
CREATE SCHEMA integration;

CREATE TABLE integration.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE integration.thread_tasks (
    seq bigserial PRIMARY KEY,
    thread_id uuid NOT NULL,
    task_id uuid NOT NULL UNIQUE,
    message_id uuid NOT NULL,
    at timestamptz NOT NULL
);
CREATE INDEX thread_tasks_thread_idx ON integration.thread_tasks (thread_id, seq);

CREATE FUNCTION integration.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'integration.%: rows are append-only', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER thread_tasks_append_only BEFORE UPDATE OR DELETE ON integration.thread_tasks
    FOR EACH ROW EXECUTE FUNCTION integration.forbid_change();
CREATE TRIGGER thread_tasks_no_truncate BEFORE TRUNCATE ON integration.thread_tasks
    FOR EACH STATEMENT EXECUTE FUNCTION integration.forbid_change();

INSERT INTO integration.schema_migrations (version) VALUES (1);
