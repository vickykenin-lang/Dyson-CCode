-- E: Founder alerts and reminders (D-009). Every issue E raises stays open, and the Founder is
-- reminded at the approved interval, until the Founder acts on it or puts it on hold.
-- Append-only: an alert's state is its latest event.

CREATE TABLE assurance.alert_events (
    seq bigserial PRIMARY KEY,
    alert_id uuid NOT NULL,
    subject_kind text NOT NULL,
    subject_id text NOT NULL,
    issue text NOT NULL,           -- bad_status, repeated_failure, silent
    message text NOT NULL CHECK (message <> ''),
    event text NOT NULL CHECK (event IN ('raised', 'reminded', 'acted', 'held', 'released')),
    by_component text NOT NULL,
    note text NOT NULL DEFAULT '',
    at timestamptz NOT NULL
);
CREATE INDEX alert_events_alert_idx ON assurance.alert_events (alert_id, seq);

CREATE TRIGGER alert_events_append_only BEFORE UPDATE OR DELETE ON assurance.alert_events
    FOR EACH ROW EXECUTE FUNCTION assurance.forbid_change();
CREATE TRIGGER alert_events_no_truncate BEFORE TRUNCATE ON assurance.alert_events
    FOR EACH STATEMENT EXECUTE FUNCTION assurance.forbid_change();

INSERT INTO assurance.schema_migrations (version) VALUES (2);
