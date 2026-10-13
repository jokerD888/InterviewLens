-- A committed write and its cache generation must be atomic.
CREATE TABLE IF NOT EXISTS il_read_revision (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    epoch UUID NOT NULL DEFAULT gen_random_uuid(),
    revision BIGINT NOT NULL DEFAULT 0
);
INSERT INTO il_read_revision(id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION advance_read_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    UPDATE public.il_read_revision SET revision = revision + 1 WHERE id = 1;
    RETURN NULL;
END
$$;
REVOKE ALL ON FUNCTION advance_read_revision() FROM PUBLIC;

DO $$
DECLARE relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'posts', 'questions', 'companies', 'positions', 'post_companies',
        'post_company_position', 'post_position_profiles', 'post_processing',
        'post_attribution', 'post_question_refs', 'interview_experiences',
        'question_interviews', 'summaries'
    ] LOOP
        EXECUTE format('CREATE TRIGGER il_advance_read_revision AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION advance_read_revision()', relation_name);
    END LOOP;
END
$$;
