-- Preserve transactional cache generations without taking business locks first.
CREATE OR REPLACE FUNCTION lock_read_generation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(73420, 0);
    RETURN NULL;
END
$$;
REVOKE ALL ON FUNCTION lock_read_generation() FROM PUBLIC;

DO $$
DECLARE relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'posts', 'questions', 'companies', 'positions', 'post_companies',
        'post_company_position', 'post_position_profiles', 'post_attribution',
        'post_question_refs', 'interview_experiences', 'question_interviews', 'summaries'
    ] LOOP
        EXECUTE format('CREATE TRIGGER il_lock_read_generation BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION lock_read_generation()', relation_name);
    END LOOP;
END
$$;

-- Lease owner/expiry, payload and diagnostics are not public visibility data.
-- Changes to stages, inserts and removals can change visibility. Row triggers
-- also avoid bumping the generation when a claim inserts no new processing row.
DROP TRIGGER il_advance_read_revision ON post_processing;
CREATE TRIGGER il_lock_processing_generation BEFORE INSERT OR DELETE OR TRUNCATE
ON post_processing FOR EACH STATEMENT EXECUTE FUNCTION lock_read_generation();
CREATE TRIGGER il_lock_processing_stages BEFORE UPDATE OF stages
ON post_processing FOR EACH STATEMENT EXECUTE FUNCTION lock_read_generation();
CREATE TRIGGER il_advance_processing_revision AFTER INSERT OR DELETE
ON post_processing FOR EACH ROW EXECUTE FUNCTION advance_read_revision();
CREATE TRIGGER il_advance_processing_stages AFTER UPDATE OF stages
ON post_processing FOR EACH ROW WHEN (OLD.stages IS DISTINCT FROM NEW.stages)
EXECUTE FUNCTION advance_read_revision();
CREATE TRIGGER il_advance_processing_truncate AFTER TRUNCATE
ON post_processing FOR EACH STATEMENT EXECUTE FUNCTION advance_read_revision();
