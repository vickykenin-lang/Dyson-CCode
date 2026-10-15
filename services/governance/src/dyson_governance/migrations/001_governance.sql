-- Governance Core (card A), schema "governance". Step 3 of the execution plan.
-- One append-only event log; current state is rebuilt from it (STOP survives restarts).

CREATE SCHEMA governance;

CREATE TABLE governance.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE governance.events (
    seq bigserial PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    type text NOT NULL,
    at timestamptz NOT NULL,
    body jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION governance.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'governance.events is append-only' USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON governance.events
    FOR EACH ROW EXECUTE FUNCTION governance.forbid_change();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON governance.events
    FOR EACH STATEMENT EXECUTE FUNCTION governance.forbid_change();

INSERT INTO governance.schema_migrations (version) VALUES (1);
