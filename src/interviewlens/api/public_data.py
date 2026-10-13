"""An explicit public projection; page archives and provenance remain private.

Never serialize arbitrary crawler/LLM payload dictionaries to public clients.
Evidence quotes can contain a fragment of the page's logged-in SSR context;
the public view only exposes controlled facets. Administrators retain evidence.
"""
import re

from ..position_taxonomy import PositionProfile

_ARCHIVE_CONTEXT = re.compile(r"window\.(?:envInfo|__VUE_SSR_CONTEXT__)|rawNickname|educationInfo")


def protect_question(question):
    # Extraction is fallible: defend derived text as well as the raw archive.
    if any(_ARCHIVE_CONTEXT.search(value or "") for value in
           (question.content, question.answer_brief, question.answer_ai)):
        question.content = "此内容暂不展示，可通过原帖查看。"
        question.answer_brief = question.answer_ai = None
    return question


def public_profile(payload: dict) -> dict:
    profile = PositionProfile.model_validate(payload)
    return profile.model_dump(include={
        "category", "specializations", "domains", "skills", "status", "source",
        "taxonomy_version",
    })
