-- Additive state. Repeated pages are an incomplete scan, never "history complete".
BEGIN;
CREATE TABLE IF NOT EXISTS crawl_scan_pages (
    source TEXT NOT NULL REFERENCES crawl_progress(source),
    page INTEGER NOT NULL CHECK (page > 0),
    fingerprint TEXT,
    oldest_at TIMESTAMPTZ,
    newest_at TIMESTAMPTZ,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(source,page)
);
CREATE INDEX IF NOT EXISTS idx_crawl_scan_fingerprint
    ON crawl_scan_pages(source,fingerprint);
CREATE TABLE IF NOT EXISTS crawl_date_repairs (
    post_id BIGINT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    posted_at TIMESTAMPTZ NOT NULL,
    evidence_source TEXT NOT NULL,
    evidence TEXT NOT NULL,
    repaired_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS crawl_date_unavailable (
    post_id BIGINT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMIT;
