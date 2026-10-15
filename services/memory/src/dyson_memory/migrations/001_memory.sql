-- Memory & Evidence Layer (card I), schema "memory". Step 2 of the execution plan.
-- Everything here is append-only: history is never rewritten (LA-AMD-04, LA-MEM-07).
-- Row-level security isolates each Receptor (LA-MEM-04, LA-IF-07). The session sets
-- dyson.scope to 'core' (Layer A components) or a Receptor ID such as 'T0' or 'R11'.

CREATE SCHEMA memory;

CREATE TABLE memory.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION memory.current_scope() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT coalesce(current_setting('dyson.scope', true), '') $$;

-- Core sees every row; a Receptor sees only its own rows. No scope sees nothing.
CREATE FUNCTION memory.visible(rid text) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT memory.current_scope() = 'core'
        OR (rid IS NOT NULL AND rid = memory.current_scope())
$$;

CREATE FUNCTION memory.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'memory.%: rows are append-only', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE DOMAIN memory.receptor_id AS text CHECK (VALUE ~ '^(T0|R[1-9][0-9]*)$');

-- Conversation archive (LA-MEM-01) ------------------------------------------------------
CREATE TABLE memory.threads (
    thread_id uuid PRIMARY KEY,
    receptor_id memory.receptor_id,
    title text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL
);

CREATE TABLE memory.messages (
    message_id uuid PRIMARY KEY,
    thread_id uuid NOT NULL REFERENCES memory.threads,
    receptor_id memory.receptor_id,
    participant text NOT NULL CHECK (participant <> ''),
    modality text NOT NULL CHECK (modality IN ('text', 'voice')),
    body text NOT NULL CHECK (body <> ''),
    language text NOT NULL CHECK (language IN ('hi', 'en', 'hinglish', 'unknown')),
    transcription_uncertain boolean NOT NULL DEFAULT false,
    raw_transcript_ref text,
    attachments jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(attachments) = 'array'),
    -- Only Dyson's own conversations are archived. Importing ChatGPT history needs a
    -- separately approved transfer and a schema change (LA-PRIV-03).
    source text NOT NULL DEFAULT 'dyson' CHECK (source = 'dyson'),
    sent_at timestamptz NOT NULL,
    seq bigserial UNIQUE,
    search tsvector GENERATED ALWAYS AS (to_tsvector('simple', body)) STORED,
    CHECK (modality = 'voice' OR NOT transcription_uncertain)
);
CREATE INDEX messages_thread_idx ON memory.messages (thread_id, sent_at, seq);
CREATE INDEX messages_search_idx ON memory.messages USING gin (search);

CREATE FUNCTION memory.message_receptor() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- A message always belongs to its thread's Receptor; callers cannot choose another.
    SELECT t.receptor_id INTO NEW.receptor_id FROM memory.threads t WHERE t.thread_id = NEW.thread_id;
    RETURN NEW;
END $$;
CREATE TRIGGER messages_receptor BEFORE INSERT ON memory.messages
    FOR EACH ROW EXECUTE FUNCTION memory.message_receptor();

-- Long-term memory with provenance (LA-MEM-02, LA-MEM-09) -------------------------------
CREATE TABLE memory.memory_items (
    item_id uuid PRIMARY KEY,
    receptor_id memory.receptor_id,
    kind text NOT NULL CHECK (kind IN ('fact', 'preference', 'project_status', 'summary')),
    content text NOT NULL CHECK (content <> ''),
    sources jsonb NOT NULL CHECK (jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) > 0),
    uncertain boolean NOT NULL DEFAULT false,
    supersedes uuid REFERENCES memory.memory_items,
    created_at timestamptz NOT NULL,
    search tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);
CREATE INDEX memory_items_search_idx ON memory.memory_items USING gin (search);

-- Shared learnings cross Receptor boundaries only with approval and verification (AMD-8).
CREATE TABLE memory.shared_learnings (
    learning_id uuid PRIMARY KEY,
    content text NOT NULL CHECK (content <> ''),
    origin_receptor_id memory.receptor_id,
    sources jsonb NOT NULL CHECK (jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) > 0),
    approval_id uuid NOT NULL,
    verified_evidence_id uuid NOT NULL,
    created_at timestamptz NOT NULL
);

-- Decision and amendment register (LA-MEM-03, LA-AMD-04) --------------------------------
CREATE TABLE memory.register_entries (
    seq bigserial PRIMARY KEY,
    entry_id uuid NOT NULL UNIQUE,
    rule_id text NOT NULL CHECK (rule_id ~ '^(AMD-[1-9][0-9]*|D-[0-9]{3})$'),
    version text NOT NULL CHECK (version <> ''),
    status text NOT NULL
        CHECK (status IN ('PROPOSED', 'OPEN', 'DESIGN LOCKED', 'APPROVED', 'SUPERSEDED')),
    title text NOT NULL CHECK (title <> ''),
    body text NOT NULL CHECK (body <> ''),
    decision_date date,
    evidence jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence) = 'array'),
    founder_approval_ref text,
    recorded_at timestamptz NOT NULL,
    -- A locked or approved entry must carry the decision date and the Founder's approval.
    CHECK (status NOT IN ('DESIGN LOCKED', 'APPROVED')
           OR (decision_date IS NOT NULL AND coalesce(founder_approval_ref, '') <> ''))
);
CREATE INDEX register_rule_idx ON memory.register_entries (rule_id, seq);

-- Evidence registry, eight AMD-3 stages (LA-EVD-03) -------------------------------------
CREATE TABLE memory.evidence (
    seq bigserial UNIQUE,
    evidence_id uuid PRIMARY KEY,
    receptor_id memory.receptor_id,
    capability text NOT NULL CHECK (capability <> ''),
    provider text NOT NULL CHECK (provider <> ''),
    stage smallint NOT NULL CHECK (stage BETWEEN 1 AND 8),
    outcome text NOT NULL CHECK (outcome IN ('passed', 'failed', 'negative')),
    environment text NOT NULL CHECK (environment <> ''),
    scope text NOT NULL CHECK (scope <> ''),
    recorded_by text NOT NULL,
    recorded_at timestamptz NOT NULL,
    expires_at timestamptz,
    artifact_ref text NOT NULL CHECK (artifact_ref <> ''),
    task_id uuid,
    detail text NOT NULL DEFAULT '',
    CHECK (expires_at IS NULL OR expires_at > recorded_at),
    -- Stages 6-8 are passed only by an independent verifier: F (QA/QC) or H (Financial).
    CHECK (NOT (outcome = 'passed' AND stage >= 6 AND recorded_by NOT IN ('F', 'H')))
);
CREATE INDEX evidence_capability_idx ON memory.evidence (capability, provider, environment, stage, seq);

-- Audit log, hash-chained (LA-MEM-07) ---------------------------------------------------
CREATE TABLE memory.audit_log (
    seq bigserial PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    kind text NOT NULL,
    actor text NOT NULL,
    at timestamptz NOT NULL,
    summary text NOT NULL CHECK (summary <> ''),
    task_id uuid,
    ref_id uuid,
    data jsonb NOT NULL DEFAULT '{}',
    prev_hash text NOT NULL,
    hash text NOT NULL UNIQUE
);

CREATE FUNCTION memory.audit_digest(prev text, r memory.audit_log) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(convert_to(concat_ws('|',
        prev, r.event_id::text, r.kind, r.actor,
        to_char(r.at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        r.summary, coalesce(r.task_id::text, ''), coalesce(r.ref_id::text, ''), r.data::text
    ), 'UTF8')), 'hex')
$$;

-- The database computes the chain; callers cannot supply or forge a hash.
CREATE FUNCTION memory.audit_chain() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('memory.audit_log'));
    SELECT coalesce((SELECT hash FROM memory.audit_log ORDER BY seq DESC LIMIT 1), 'genesis')
        INTO NEW.prev_hash;
    NEW.hash := memory.audit_digest(NEW.prev_hash, NEW);
    RETURN NEW;
END $$;
CREATE TRIGGER audit_chain BEFORE INSERT ON memory.audit_log
    FOR EACH ROW EXECUTE FUNCTION memory.audit_chain();

-- Returns the seq of the first broken link, or NULL when the whole chain verifies.
CREATE FUNCTION memory.verify_audit_chain() RETURNS bigint
LANGUAGE plpgsql STABLE AS $$
DECLARE
    r memory.audit_log;
    prev text := 'genesis';
BEGIN
    FOR r IN SELECT * FROM memory.audit_log ORDER BY seq LOOP
        IF r.prev_hash <> prev OR r.hash <> memory.audit_digest(prev, r) THEN
            RETURN r.seq;
        END IF;
        prev := r.hash;
    END LOOP;
    RETURN NULL;
END $$;

-- Append-only everywhere ----------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['threads', 'messages', 'memory_items', 'shared_learnings',
                             'register_entries', 'evidence', 'audit_log'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON memory.%I
                        FOR EACH ROW EXECUTE FUNCTION memory.forbid_change()', t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON memory.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION memory.forbid_change()', t || '_no_truncate', t);
        EXECUTE format('ALTER TABLE memory.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE memory.%I FORCE ROW LEVEL SECURITY', t);
    END LOOP;
END $$;

-- Row-level security --------------------------------------------------------------------
-- Receptor-scoped tables: core sees all, a Receptor sees and writes only its own rows.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['threads', 'messages', 'memory_items', 'evidence'] LOOP
        EXECUTE format('CREATE POLICY %I ON memory.%I FOR SELECT USING (memory.visible(receptor_id))',
                       t || '_read', t);
        EXECUTE format('CREATE POLICY %I ON memory.%I FOR INSERT WITH CHECK (memory.visible(receptor_id))',
                       t || '_write', t);
    END LOOP;
END $$;

-- Central tables: any scope may read; only core may write.
CREATE POLICY shared_learnings_read ON memory.shared_learnings FOR SELECT
    USING (memory.current_scope() <> '');
CREATE POLICY shared_learnings_write ON memory.shared_learnings FOR INSERT
    WITH CHECK (memory.current_scope() = 'core');
CREATE POLICY register_read ON memory.register_entries FOR SELECT
    USING (memory.current_scope() <> '');
CREATE POLICY register_write ON memory.register_entries FOR INSERT
    WITH CHECK (memory.current_scope() = 'core');

-- The audit log is core-only.
CREATE POLICY audit_read ON memory.audit_log FOR SELECT USING (memory.current_scope() = 'core');
CREATE POLICY audit_write ON memory.audit_log FOR INSERT WITH CHECK (memory.current_scope() = 'core');

INSERT INTO memory.schema_migrations (version) VALUES (1);
