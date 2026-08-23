-- InterviewLens database integrity and provenance improvements.
-- Run after 001-006. New constraints are NOT VALID so existing rows do not
-- block the migration; they still protect all future writes. Clean legacy
-- violations and VALIDATE CONSTRAINT afterwards.

ALTER TABLE posts
    ADD COLUMN IF NOT EXISTS interview_date DATE;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedding_version INT;

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedding_version INT;

ALTER TABLE questions
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedding_version INT;

CREATE INDEX IF NOT EXISTS idx_pcp_company_position_post
    ON post_company_position(company_id, position_id, post_id);

DROP INDEX IF EXISTS idx_summaries_lookup;

DO $constraints$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_posts_content_score_range') THEN
        ALTER TABLE posts ADD CONSTRAINT ck_posts_content_score_range
            CHECK (content_score IS NULL OR content_score BETWEEN 0 AND 70) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_posts_extract_status') THEN
        ALTER TABLE posts ADD CONSTRAINT ck_posts_extract_status
            CHECK (extract_status IN ('pending', 'done', 'failed', 'skipped')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_questions_round_no_positive') THEN
        ALTER TABLE questions ADD CONSTRAINT ck_questions_round_no_positive
            CHECK (round_no IS NULL OR round_no >= 1) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_questions_answer_ai_version_nonnegative') THEN
        ALTER TABLE questions ADD CONSTRAINT ck_questions_answer_ai_version_nonnegative
            CHECK (answer_ai_version >= 0) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_summaries_sample_count_nonnegative') THEN
        ALTER TABLE summaries ADD CONSTRAINT ck_summaries_sample_count_nonnegative
            CHECK (sample_count >= 0) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_summaries_period_format') THEN
        ALTER TABLE summaries ADD CONSTRAINT ck_summaries_period_format
            CHECK (period = 'all' OR period ~ '^[0-9]{4}Q[1-4]$') NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_company_alias_confidence') THEN
        ALTER TABLE company_aliases ADD CONSTRAINT ck_company_alias_confidence
            CHECK (confidence BETWEEN 0 AND 1) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_position_alias_confidence') THEN
        ALTER TABLE position_aliases ADD CONSTRAINT ck_position_alias_confidence
            CHECK (confidence BETWEEN 0 AND 1) NOT VALID;
    END IF;
END
$constraints$;
