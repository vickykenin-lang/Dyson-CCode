-- Bi-temporal personal facts for the Jarvis engine (D-026, phase 2). Card I, schema "memory".
-- Long-term memory (migration 001) remembers what was said; a fact remembers what is true, and
-- for how long. Two timelines (LA-MEM-02, LA-MEM-09):
--   valid_from / valid_to  -- when the fact is true in the world
--   recorded_at            -- when Dyson learned it
-- A fact is never changed or deleted (append-only, LA-AMD-04). A newer fact supersedes an older
-- one by naming it, so "as of last month" and "now" both have an honest answer. Every fact cites
-- its source. Row-level security isolates each Receptor, exactly like the rest of this schema.

-- Trigram index support for fuzzy subject/value lookup. pg_trgm is a trusted extension.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE memory.facts (
    fact_id uuid PRIMARY KEY,
    receptor_id memory.receptor_id,          -- NULL = a core (personal) fact about the Founder
    subject text NOT NULL CHECK (subject <> ''),       -- who/what, e.g. 'founder' or 'bank:primary'
    attribute text NOT NULL CHECK (attribute <> ''),   -- which property, e.g. 'name' or 'bank'
    value text NOT NULL CHECK (value <> ''),           -- the property's value
    statement text NOT NULL CHECK (statement <> ''),   -- the fact as a sentence, for search
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,                    -- NULL = still true (open interval)
    sources jsonb NOT NULL CHECK (jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) > 0),
    confidence double precision NOT NULL DEFAULT 1.0 CHECK (confidence > 0 AND confidence <= 1),
    supersedes uuid REFERENCES memory.facts,  -- the fact this one replaces, if any
    recorded_at timestamptz NOT NULL,
    seq bigserial UNIQUE,
    search tsvector GENERATED ALWAYS AS (to_tsvector('simple', statement)) STORED,
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE INDEX facts_subject_idx ON memory.facts (subject, attribute, recorded_at DESC);
CREATE INDEX facts_search_idx ON memory.facts USING gin (search);
CREATE INDEX facts_trgm_idx ON memory.facts USING gin (subject gin_trgm_ops, value gin_trgm_ops);
CREATE INDEX facts_supersedes_idx ON memory.facts (supersedes);

-- Append-only and per-Receptor, like every other table here.
CREATE TRIGGER facts_append_only BEFORE UPDATE OR DELETE ON memory.facts
    FOR EACH ROW EXECUTE FUNCTION memory.forbid_change();
CREATE TRIGGER facts_no_truncate BEFORE TRUNCATE ON memory.facts
    FOR EACH STATEMENT EXECUTE FUNCTION memory.forbid_change();
ALTER TABLE memory.facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.facts FORCE ROW LEVEL SECURITY;

CREATE POLICY facts_read ON memory.facts FOR SELECT USING (memory.visible(receptor_id));
CREATE POLICY facts_write ON memory.facts FOR INSERT WITH CHECK (memory.visible(receptor_id));

INSERT INTO memory.schema_migrations (version) VALUES (2);
