"""Shared safe SQL predicate: one profile must satisfy all selected facets."""

from fastapi import HTTPException

from ..position_taxonomy import DOMAINS, SKILLS, SPECIALIZATIONS, TAXONOMY_VERSION


def profile_predicate(
    category, specializations, domains, skills, include_unreviewed, params, *, question_scope=False
):
    clauses = ["pp.post_id = po.id", "pp.taxonomy_version=:taxonomy_version"]
    params["taxonomy_version"] = TAXONOMY_VERSION
    if category:
        clauses.append("pp.category=:position_category")
        params["position_category"] = str(category)
    for field, values, vocabulary in (
        ("specializations", specializations, SPECIALIZATIONS),
        ("domains", domains, DOMAINS),
        ("skills", skills, SKILLS),
    ):
        if set(values or []) - set(vocabulary):
            raise HTTPException(422, f"unsupported {field}")
        if values:
            clauses.append(f"(pp.payload->'{field}') ?| CAST(:{field} AS text[])")
            params[field] = list(dict.fromkeys(values))
    if not (category or specializations or domains or skills):
        return None
    if question_scope:
        clauses.append("""
            ((NOT EXISTS(SELECT 1 FROM post_attribution pa WHERE pa.post_id=po.id
                AND pa.mode='explicit')
              AND (SELECT COUNT(*) FROM post_position_profiles pp2 WHERE pp2.post_id=po.id)=1)
             OR EXISTS(SELECT 1 FROM question_interviews qi
                JOIN interview_experiences ie ON ie.id=qi.interview_id
                WHERE qi.question_id=q.id AND ie.profile_index=pp.ordinal))
        """)
    # Legacy review flag is accepted for URL compatibility; all classifications are searchable.
    return "EXISTS (SELECT 1 FROM post_position_profiles pp WHERE " + " AND ".join(clauses) + ")"
