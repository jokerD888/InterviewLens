-- ============================================================
-- InterviewLens · Initial schema (current)
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
    embedding   vector(1024),
    embedding_model TEXT,
    embedding_version INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_companies_embedding
    ON companies USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ----------------------------------------------------------------
-- positions
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    id          BIGSERIAL PRIMARY KEY,
    canonical   TEXT NOT NULL UNIQUE,
    category    TEXT,
    embedding   vector(1024),
    embedding_model TEXT,
    embedding_version INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_positions_embedding
    ON positions USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

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
    interview_date  DATE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content_score   INT,
    content_score_version INT NOT NULL DEFAULT 1,
    content_scored_at TIMESTAMPTZ,
    -- Deprecated compatibility column; ranking/filtering uses content_score.
    quality_score   INT,
    extract_status  TEXT NOT NULL DEFAULT 'pending',
    extract_error   TEXT,
    extract_version INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_posts_content_score_range
        CHECK (content_score IS NULL OR content_score BETWEEN 0 AND 70),
    CONSTRAINT ck_posts_extract_status
        CHECK (extract_status IN ('pending', 'done', 'failed', 'skipped'))
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(extract_status);
CREATE INDEX IF NOT EXISTS idx_posts_posted ON posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_version ON posts(extract_version);
CREATE INDEX IF NOT EXISTS idx_posts_content_score ON posts(content_score DESC);
CREATE INDEX IF NOT EXISTS idx_posts_status_content_score
    ON posts(extract_status, content_score DESC);

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
CREATE INDEX IF NOT EXISTS idx_pcp_company_position_post
    ON post_company_position(company_id, position_id, post_id);

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
    answer_ai    TEXT,
    answer_ai_version INT NOT NULL DEFAULT 0,
    embedding    vector(1024),
    embedding_model TEXT,
    embedding_version INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_questions_round_no_positive
        CHECK (round_no IS NULL OR round_no >= 1),
    CONSTRAINT ck_questions_answer_ai_version_nonnegative
        CHECK (answer_ai_version >= 0)
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
    input_fingerprint TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, position_id, period),
    CONSTRAINT ck_summaries_sample_count_nonnegative CHECK (sample_count >= 0),
    CONSTRAINT ck_summaries_period_format CHECK (
        period = 'all' OR period ~ '^[0-9]{4}Q[1-4]$'
    )
);

-- ----------------------------------------------------------------
-- Entity-specific alias tables (self-learning)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_aliases (
    id            BIGSERIAL PRIMARY KEY,
    alias         TEXT NOT NULL,
    company_id    BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    confidence    REAL NOT NULL DEFAULT 1.0,
    learned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias),
    CONSTRAINT ck_company_alias_confidence CHECK (confidence BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS idx_company_alias_canonical ON company_aliases(company_id);

CREATE TABLE IF NOT EXISTS position_aliases (
    id            BIGSERIAL PRIMARY KEY,
    alias         TEXT NOT NULL,
    position_id   BIGINT NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    confidence    REAL NOT NULL DEFAULT 1.0,
    learned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias),
    CONSTRAINT ck_position_alias_confidence CHECK (confidence BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS idx_position_alias_canonical ON position_aliases(position_id);

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
    AVG(po.content_score)::INT AS avg_quality,
    MAX(po.posted_at) AS latest_posted_at
FROM post_company_position pcp
JOIN companies c ON c.id = pcp.company_id
JOIN positions p ON p.id = pcp.position_id
JOIN posts po ON po.id = pcp.post_id
WHERE po.extract_status = 'done'
GROUP BY c.id, c.canonical, p.id, p.canonical;
