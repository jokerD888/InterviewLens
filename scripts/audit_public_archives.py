"""Read-only archive contamination audit. Outputs IDs/counts, never page bodies.

Run with the project's DATABASE_URL_SYNC. This does not call LLMs or crawl.
Keep originals for administrator investigation; public responses use projections.
"""
import json
import psycopg
from interviewlens.config import settings

PATTERN = r"window\.(envInfo|__VUE_SSR_CONTEXT__)|rawNickname|educationInfo"


def audit():
    with psycopg.connect(settings.database_url_sync.replace("postgresql+psycopg://", "postgresql://", 1)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        posts = conn.execute("SELECT id FROM posts WHERE cleaned_text ~ %s ORDER BY id", (PATTERN,)).fetchall()
        questions = conn.execute("SELECT id FROM questions WHERE concat_ws(' ',content,answer_brief,answer_ai) ~ %s ORDER BY id", (PATTERN,)).fetchall()
        return {"archive_post_ids": [row[0] for row in posts],
                "structured_question_ids": [row[0] for row in questions],
                "archive_count": len(posts), "structured_count": len(questions),
                "action": "Preserve originals privately; do not expose archives/evidence quotes publicly"}


if __name__ == "__main__":
    print(json.dumps(audit()))
