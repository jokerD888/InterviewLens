-- ============================================================
-- InterviewLens · Initial schema (v1)
-- Auto-loaded by docker-compose on first postgres startup.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ----------------------------------------------------------------
-- companies
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id          BIGSERIAL PRIMARY KEY,
    canonical   TEXT NOT NULL UNIQUE,
    industry    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------
-- positions
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    id          BIGSERIAL PRIMARY KEY,
    canonical   TEXT NOT NULL UNIQUE,
    category    TEXT,
    level       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------
-- posts
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS posts (
    id              BIGSERIAL PRIMARY KEY,
    source_url      TEXT NOT NULL UNIQUE,
    title           TEXT,
    raw_html        TEXT,
    cleaned_text    TEXT,
    posted_at       TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    quality_score   INT,
    extract_status  TEXT NOT NULL DEFAULT 'pending',
    extract_error   TEXT,
    extract_version INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(extract_status);
CREATE INDEX IF NOT EXISTS idx_posts_posted ON posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_version ON posts(extract_version);

-- ----------------------------------------------------------------
-- post_company_position (many-to-many)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS post_company_position (
    post_id     BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    company_id  BIGINT NOT NULL REFERENCES companies(id),
    position_id BIGINT NOT NULL REFERENCES positions(id),
    PRIMARY KEY (post_id, company_id, position_id)
);
CREATE INDEX IF NOT EXISTS idx_pcp_company ON post_company_position(company_id);
CREATE INDEX IF NOT EXISTS idx_pcp_position ON post_company_position(position_id);

-- ----------------------------------------------------------------
-- questions (search granularity)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS questions (
    id           BIGSERIAL PRIMARY KEY,
    post_id      BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    round_no     INT,
    round_type   TEXT,
    content      TEXT NOT NULL,
    category     TEXT,
    answer_brief TEXT,
    embedding    vector(1024),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_questions_post ON questions(post_id);
CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
CREATE INDEX IF NOT EXISTS idx_questions_embedding
    ON questions USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ----------------------------------------------------------------
-- summaries (precomputed by Aggregator)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS summaries (
    id           BIGSERIAL PRIMARY KEY,
    company_id   BIGINT NOT NULL REFERENCES companies(id),
    position_id  BIGINT NOT NULL REFERENCES positions(id),
    period       TEXT NOT NULL,
    content_md   TEXT NOT NULL,
    sample_count INT NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, position_id, period)
);
CREATE INDEX IF NOT EXISTS idx_summaries_lookup
    ON summaries(company_id, position_id, period);

-- ----------------------------------------------------------------
-- alias_dict (self-learning)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alias_dict (
    id            BIGSERIAL PRIMARY KEY,
    entity_type   TEXT NOT NULL CHECK (entity_type IN ('company', 'position')),
    alias         TEXT NOT NULL,
    canonical_id  BIGINT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 1.0,
    learned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_type, alias)
);
CREATE INDEX IF NOT EXISTS idx_alias_lookup ON alias_dict(entity_type, alias);
CREATE INDEX IF NOT EXISTS idx_alias_canonical ON alias_dict(entity_type, canonical_id);

-- ----------------------------------------------------------------
-- Convenience view: post stats per company × position
-- ----------------------------------------------------------------
CREATE OR REPLACE VIEW v_company_position_stats AS
SELECT
    c.id   AS company_id,
    c.canonical AS company_name,
    p.id   AS position_id,
    p.canonical AS position_name,
    COUNT(DISTINCT po.id) AS post_count,
    AVG(po.quality_score)::INT AS avg_quality,
    MAX(po.posted_at) AS latest_posted_at
FROM post_company_position pcp
JOIN companies c ON c.id = pcp.company_id
JOIN positions p ON p.id = pcp.position_id
JOIN posts po ON po.id = pcp.post_id
WHERE po.extract_status = 'done'
GROUP BY c.id, c.canonical, p.id, p.canonical;
