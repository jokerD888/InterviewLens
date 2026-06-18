-- AI-generated answers for individual questions (see answerer module).
ALTER TABLE questions ADD COLUMN IF NOT EXISTS answer_ai TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS answer_ai_version INT NOT NULL DEFAULT 0;
