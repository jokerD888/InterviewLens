-- Remove the unused/mis-modelled recruitment-level column from positions.
-- The extracted level (实习/校招/社招/未知) is currently transient in
-- ExtractedPost; it has no persistence path.  IF EXISTS keeps this migration
-- idempotent.
ALTER TABLE positions DROP COLUMN IF EXISTS level;
