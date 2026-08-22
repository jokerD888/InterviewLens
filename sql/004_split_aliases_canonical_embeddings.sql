-- ============================================================
-- InterviewLens · Split aliases and persist canonical embeddings
-- Run once against an existing database after 001-003.
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS embedding vector(1024);
ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

CREATE INDEX IF NOT EXISTS idx_companies_embedding
    ON companies USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_positions_embedding
    ON positions USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- On an existing database, migrate the old polymorphic table. On a fresh
-- database, 001 already created the new tables, so this block is a no-op.
DO $migration$
DECLARE
    legacy_exists BOOLEAN;
    orphan_exists BOOLEAN;
BEGIN
    SELECT to_regclass('public.alias_dict') IS NOT NULL INTO legacy_exists;
    IF NOT legacy_exists THEN
        RAISE NOTICE 'alias_dict not present; fresh schema already uses split alias tables';
        RETURN;
    END IF;

    -- The old polymorphic table had no foreign keys. Refuse to migrate
    -- silently corrupted references; fix them before retrying the migration.
    EXECUTE $sql$
        SELECT EXISTS (
            SELECT 1
            FROM alias_dict a
            LEFT JOIN companies c
                ON a.entity_type = 'company' AND c.id = a.canonical_id
            LEFT JOIN positions p
                ON a.entity_type = 'position' AND p.id = a.canonical_id
            WHERE (a.entity_type = 'company' AND c.id IS NULL)
               OR (a.entity_type = 'position' AND p.id IS NULL)
        )
    $sql$ INTO orphan_exists;
    IF orphan_exists THEN
        RAISE EXCEPTION 'alias_dict contains orphan canonical references';
    END IF;
END
$migration$;

CREATE TABLE IF NOT EXISTS company_aliases (
    id            BIGSERIAL PRIMARY KEY,
    alias         TEXT NOT NULL,
    company_id    BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    confidence    REAL NOT NULL DEFAULT 1.0,
    learned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
CREATE INDEX IF NOT EXISTS idx_company_alias_canonical
    ON company_aliases(company_id);

CREATE TABLE IF NOT EXISTS position_aliases (
    id            BIGSERIAL PRIMARY KEY,
    alias         TEXT NOT NULL,
    position_id   BIGINT NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    confidence    REAL NOT NULL DEFAULT 1.0,
    learned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
CREATE INDEX IF NOT EXISTS idx_position_alias_canonical
    ON position_aliases(position_id);

-- The copy/drop is in a second guarded block because on a fresh database the
-- legacy table does not exist at all (this file is also mounted by Docker).
DO $copy$
BEGIN
    IF to_regclass('public.alias_dict') IS NOT NULL THEN
        EXECUTE $sql$
            INSERT INTO company_aliases (alias, company_id, confidence, learned_at)
            SELECT a.alias, a.canonical_id, a.confidence, a.learned_at
            FROM alias_dict a
            WHERE a.entity_type = 'company'
            ON CONFLICT (alias) DO NOTHING
        $sql$;
        EXECUTE $sql$
            INSERT INTO position_aliases (alias, position_id, confidence, learned_at)
            SELECT a.alias, a.canonical_id, a.confidence, a.learned_at
            FROM alias_dict a
            WHERE a.entity_type = 'position'
            ON CONFLICT (alias) DO NOTHING
        $sql$;
        EXECUTE 'DROP TABLE public.alias_dict';
    END IF;
END
$copy$;

COMMIT;
