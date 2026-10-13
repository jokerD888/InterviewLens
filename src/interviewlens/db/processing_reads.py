"""Keep partially recovered posts out of derived public reads."""
READY_POST_SQL = """NOT EXISTS(
    SELECT 1 FROM post_processing processing WHERE processing.post_id=po.id
    AND (processing.stages->>'normalize' IS DISTINCT FROM 'done'
      OR processing.stages->>'score' IS DISTINCT FROM 'done'
      OR processing.stages->>'index' IS DISTINCT FROM 'done')
)"""

VISIBLE_POST_SQL = f"""po.extract_status='done' AND {READY_POST_SQL}
AND EXISTS(SELECT 1 FROM questions visible_q WHERE visible_q.post_id=po.id)"""
