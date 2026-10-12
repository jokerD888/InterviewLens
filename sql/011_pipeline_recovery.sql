-- Additive processing state. Existing extracted rows and derived data are kept.
CREATE TABLE IF NOT EXISTS post_processing (
    post_id BIGINT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    input_hash TEXT NOT NULL DEFAULT '',
    payload JSONB,
    stages JSONB NOT NULL DEFAULT '{}'::jsonb,
    failed_stage TEXT,
    error TEXT,
    owner TEXT,
    lease_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_post_processing_incomplete
    ON post_processing(updated_at) WHERE stages->>'index' IS DISTINCT FROM 'done';
