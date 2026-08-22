-- Make Aggregator cache validity depend on its actual input, not only a count.
-- Existing rows have NULL and will be regenerated once on the next aggregate.
ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS input_fingerprint TEXT;
