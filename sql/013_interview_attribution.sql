-- Keep historical links as evidence; mark ambiguous legacy attribution explicitly.
CREATE TABLE IF NOT EXISTS post_attribution (
    post_id BIGINT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK(mode IN ('legacy_single','ambiguous','explicit')),
    single_company_id BIGINT REFERENCES companies(id),
    single_position_id BIGINT REFERENCES positions(id)
);
INSERT INTO post_attribution(post_id, mode, single_company_id, single_position_id)
SELECT post_id, CASE WHEN COUNT(DISTINCT company_id)=1
                         AND COUNT(DISTINCT position_id)=1
                    THEN 'legacy_single' ELSE 'ambiguous' END,
       CASE WHEN COUNT(DISTINCT company_id)=1 THEN MIN(company_id) END,
       CASE WHEN COUNT(DISTINCT position_id)=1 THEN MIN(position_id) END
FROM post_company_position GROUP BY post_id
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS post_question_refs (
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    round_index INTEGER NOT NULL,
    question_index INTEGER NOT NULL,
    question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    PRIMARY KEY(post_id,round_index,question_index)
);
CREATE TABLE IF NOT EXISTS interview_experiences (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    company_id BIGINT REFERENCES companies(id),
    position_id BIGINT REFERENCES positions(id),
    profile_index INTEGER,
    evidence TEXT NOT NULL,
    UNIQUE(post_id,ordinal)
);
CREATE TABLE IF NOT EXISTS question_interviews (
    question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    interview_id BIGINT NOT NULL REFERENCES interview_experiences(id) ON DELETE CASCADE,
    PRIMARY KEY(question_id,interview_id)
);
CREATE INDEX IF NOT EXISTS ix_interview_company_position
    ON interview_experiences(company_id,position_id,post_id);
