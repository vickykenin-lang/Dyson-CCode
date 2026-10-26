-- Knowledge layer (the "second brain"), schema "knowledge".
-- Not append-only (unlike memory): a re-ingested file replaces its chunks, a deleted file is
-- tombstoned. One document per (source, path); chunks carry a pgvector embedding plus metadata so
-- retrieval can route by folder/tag as well as by meaning, and a generated tsvector enables hybrid
-- (keyword + vector) search. Embedding dimension is 768 (EmbeddingGemma; truncate + re-embed to
-- change it).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA knowledge;

CREATE TABLE knowledge.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE knowledge.documents (
    doc_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source          text NOT NULL,
    path            text NOT NULL,
    content_hash    text NOT NULL,
    generation      integer NOT NULL,
    mime            text NOT NULL DEFAULT 'text/markdown',
    tags            text[] NOT NULL DEFAULT '{}',
    embedding_model text NOT NULL,
    folder          text NOT NULL DEFAULT '',
    filename        text NOT NULL DEFAULT '',
    deleted         boolean NOT NULL DEFAULT false,   -- tombstone
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, path)
);
CREATE INDEX documents_live ON knowledge.documents (source, folder) WHERE NOT deleted;

CREATE TABLE knowledge.chunks (
    chunk_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id     uuid NOT NULL REFERENCES knowledge.documents(doc_id) ON DELETE CASCADE,
    source     text NOT NULL,
    path       text NOT NULL,
    folder     text NOT NULL DEFAULT '',
    ord        integer NOT NULL,
    text       text NOT NULL,
    tags       text[] NOT NULL DEFAULT '{}',
    embedding  vector(768) NOT NULL,
    -- 'simple' config: no stemming, safe for mixed Hinglish/code. Hybrid search uses this.
    tsv        tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chunks_embedding_hnsw ON knowledge.chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_doc ON knowledge.chunks (doc_id);
CREATE INDEX chunks_source_folder ON knowledge.chunks (source, folder);
CREATE INDEX chunks_tsv ON knowledge.chunks USING gin (tsv);

INSERT INTO knowledge.schema_migrations (version) VALUES (1);
