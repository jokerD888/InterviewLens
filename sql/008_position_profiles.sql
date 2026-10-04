-- Additive: legacy positions, links, questions and summaries remain untouched.
BEGIN;
-- Company mentions must survive even when the job category is unknown.
CREATE TABLE IF NOT EXISTS post_companies (
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, company_id)
);
INSERT INTO post_companies (post_id, company_id)
SELECT DISTINCT post_id,company_id FROM post_company_position ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS idx_post_companies_company ON post_companies(company_id, post_id);
CREATE TABLE IF NOT EXISTS post_position_profiles (
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    category TEXT CHECK (category IN ('后端','前端','客户端','算法/AI','测试','运维/SRE','数据','安全','游戏','嵌入式/系统','其他')),
    status TEXT NOT NULL CHECK (status IN ('classified','uncertain','out_of_scope')),
    needs_review BOOLEAN NOT NULL DEFAULT TRUE,
    taxonomy_version INTEGER NOT NULL CHECK (taxonomy_version > 0),
    input_hash TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('extractor','historical_preview')),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (post_id, ordinal),
    CHECK ((status = 'classified') = (category IS NOT NULL)),
    CHECK (jsonb_typeof(payload) = 'object')
);
CREATE INDEX IF NOT EXISTS idx_position_profiles_category ON post_position_profiles(category, post_id);
CREATE INDEX IF NOT EXISTS idx_position_profiles_payload ON post_position_profiles USING GIN(payload);
COMMIT;
