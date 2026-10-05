-- Additive crawler state only. Apply explicitly before using backfill-crawl.
BEGIN;
CREATE TABLE IF NOT EXISTS crawl_progress (
    source TEXT PRIMARY KEY,
    since_at TIMESTAMPTZ NOT NULL,
    next_page INTEGER NOT NULL DEFAULT 1 CHECK (next_page > 0),
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    last_batch_at TIMESTAMPTZ,
    paused_reason TEXT
);
CREATE TABLE IF NOT EXISTS crawl_queue (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL REFERENCES crawl_progress(source),
    record JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_crawl_queue_pending ON crawl_queue(source, queued_at, url)
    WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS crawl_daily_budget (
    source TEXT NOT NULL REFERENCES crawl_progress(source),
    day DATE NOT NULL,
    detail_attempts INTEGER NOT NULL DEFAULT 0 CHECK (detail_attempts >= 0),
    PRIMARY KEY (source, day)
);
COMMIT;
