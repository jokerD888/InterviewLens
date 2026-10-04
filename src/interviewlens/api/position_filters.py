"""Shared safe SQL predicate: one profile must satisfy all selected facets."""

from fastapi import HTTPException

from ..position_taxonomy import DOMAINS, SKILLS, SPECIALIZATIONS, TAXONOMY_VERSION


def profile_predicate(category, specializations, domains, skills, include_unreviewed, params):
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
    if not include_unreviewed:
        clauses.append("NOT pp.needs_review")
    return "EXISTS (SELECT 1 FROM post_position_profiles pp WHERE " + " AND ".join(clauses) + ")"
