-- Export LLM-extracted data as readable JSON
-- Usage: psql ... -f export_llm_data.sql -t -A > output.json
WITH post_data AS (
    SELECT
        po.id,
        po.title,
        po.source_url,
        po.posted_at,
        po.cleaned_text,
        po.quality_score,
        po.extract_status,
        po.extract_version,
        -- companies
        (
            SELECT json_agg(json_build_object('id', c.id, 'canonical', c.canonical))
            FROM post_company_position pcp2
            JOIN companies c ON c.id = pcp2.company_id
            WHERE pcp2.post_id = po.id
        ) AS companies,
        -- positions
        (
            SELECT json_agg(json_build_object('id', p.id, 'canonical', p.canonical, 'category', p.category))
            FROM post_company_position pcp3
            JOIN positions p ON p.id = pcp3.position_id
            WHERE pcp3.post_id = po.id
        ) AS positions,
        -- questions
        (
            SELECT json_agg(
                json_build_object(
                    'id', q.id,
                    'round_no', q.round_no,
                    'round_type', q.round_type,
                    'content', q.content,
                    'category', q.category,
                    'answer_brief', q.answer_brief
                )
                ORDER BY q.round_no NULLS LAST, q.id
            )
            FROM questions q
            WHERE q.post_id = po.id
        ) AS questions
    FROM posts po
    WHERE po.extract_status = 'done'
)
SELECT jsonb_pretty(jsonb_agg(jsonb_build_object(
    'id', pd.id,
    'title', pd.title,
    'source_url', pd.source_url,
    'posted_at', pd.posted_at,
    'quality_score', pd.quality_score,
    'extract_version', pd.extract_version,
    'companies', COALESCE(pd.companies, '[]'::json)::jsonb,
    'positions', COALESCE(pd.positions, '[]'::json)::jsonb,
    'question_count', jsonb_array_length(COALESCE(pd.questions, '[]'::json)::jsonb),
    'questions', COALESCE(pd.questions, '[]'::json)::jsonb,
    'cleaned_text', pd.cleaned_text
))) FROM post_data pd;
