-- Archived conversations (D-023): nothing is deleted. Archiving and restoring are rows; the
-- latest row for a thread decides. Append-only.
CREATE TABLE integration.thread_archive (
    seq bigserial PRIMARY KEY,
    thread_id uuid NOT NULL,
    archived boolean NOT NULL,
    at timestamptz NOT NULL
);
CREATE INDEX thread_archive_thread_idx ON integration.thread_archive (thread_id, seq);

CREATE TRIGGER thread_archive_append_only BEFORE UPDATE OR DELETE ON integration.thread_archive
    FOR EACH ROW EXECUTE FUNCTION integration.forbid_change();
CREATE TRIGGER thread_archive_no_truncate BEFORE TRUNCATE ON integration.thread_archive
    FOR EACH STATEMENT EXECUTE FUNCTION integration.forbid_change();

INSERT INTO integration.schema_migrations (version) VALUES (2);
