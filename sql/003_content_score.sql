-- Split stable content completeness from the time-dependent freshness score.
-- Run once against an existing database, then run `il rescore --all` to fill
-- content_score from the already stored questions. We intentionally do not
-- copy quality_score: it may contain an old freshness component and cannot be
-- losslessly converted into a content score.

ALTER TABLE posts
    ADD COLUMN IF NOT EXISTS content_score INT,
    ADD COLUMN IF NOT EXISTS content_score_version INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS content_scored_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_posts_content_score ON posts(content_score DESC);
CREATE INDEX IF NOT EXISTS idx_posts_status_content_score
    ON posts(extract_status, content_score DESC);

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
