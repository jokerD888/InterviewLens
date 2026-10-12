CREATE TABLE IF NOT EXISTS site_request_state (
    site TEXT PRIMARY KEY,
    next_request_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paused_until TIMESTAMPTZ,
    paused_reason TEXT
);
INSERT INTO site_request_state(site) VALUES('nowcoder') ON CONFLICT DO NOTHING;
