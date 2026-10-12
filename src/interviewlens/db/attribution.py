"""Explicit company/position/question attribution; unknown is never a cross product."""

from collections import Counter

from sqlalchemy import text


async def save_attribution(session, post_id, extracted, companies, positions, author):
    interviews = extracted.get("interviews") or []
    valid = []
    ref_counts = Counter(
        (r["round_index"], r["question_index"])
        for item in interviews
        for r in item.get("questions", [])
    )
    for interview in interviews:
        quote = interview.get("evidence") or ""
        company, position = interview.get("company"), interview.get("position")
        if not quote or quote not in author:
            continue
        if company and (company not in companies or company not in quote):
            continue
        if position and (position not in positions or position not in quote):
            continue
        refs = []
        for ref in interview.get("questions", []):
            key = (ref["round_index"], ref["question_index"])
            if ref_counts[key] != 1:
                # Ambiguous repeated assignment is left unassigned.
                continue
            refs.append(ref)
        valid.append((interview, refs))
    company_ids, position_ids = set(companies.values()), set(positions.values())
    single_company = next(iter(company_ids)) if len(company_ids) == 1 else None
    single_position = next(iter(position_ids)) if len(position_ids) == 1 else None
    mode = (
        "explicit"
        if valid
        else ("legacy_single" if single_company and single_position else "ambiguous")
    )
    await session.execute(
        text("""
        INSERT INTO post_attribution(post_id,mode,single_company_id,single_position_id)
        VALUES(:id,:mode,:company,:position)
        ON CONFLICT(post_id) DO UPDATE SET mode=EXCLUDED.mode,
            single_company_id=EXCLUDED.single_company_id,
            single_position_id=EXCLUDED.single_position_id
    """),
        {"id": post_id, "mode": mode, "company": single_company, "position": single_position},
    )
    await session.execute(
        text("DELETE FROM interview_experiences WHERE post_id=:id"), {"id": post_id}
    )
    pairs = set()
    for ordinal, (interview, refs) in enumerate(valid):
        cid, pid = companies.get(interview.get("company")), positions.get(interview.get("position"))
        if cid and pid:
            pairs.add((cid, pid))
        profile_index = interview.get("profile_index")
        profiles = extracted.get("position_profiles") or []
        if profile_index is not None and not 0 <= profile_index < len(profiles):
            profile_index = None
        if profile_index is None:
            matched = [
                i for i, p in enumerate(profiles) if p.get("raw_title") == interview.get("position")
            ]
            if len(matched) == 1:
                profile_index = matched[0]
            elif len(profiles) == 1 and len(positions) == 1:
                profile_index = 0
        iid = (
            await session.execute(
                text("""
            INSERT INTO interview_experiences(post_id,ordinal,company_id,position_id,profile_index,evidence)
            VALUES(:post,:ordinal,:company,:position,:profile,:quote) RETURNING id
        """),
                {
                    "post": post_id,
                    "ordinal": ordinal,
                    "company": cid,
                    "position": pid,
                    "profile": profile_index,
                    "quote": interview["evidence"],
                },
            )
        ).scalar_one()
        for ref in refs:
            await session.execute(
                text("""
                INSERT INTO question_interviews(question_id,interview_id)
                SELECT question_id,:interview FROM post_question_refs
                WHERE post_id=:post AND round_index=:round AND question_index=:question
                ON CONFLICT DO NOTHING
            """),
                {
                    "interview": iid,
                    "post": post_id,
                    "round": ref["round_index"],
                    "question": ref["question_index"],
                },
            )
    if mode == "legacy_single":
        pairs.add((next(iter(companies.values())), next(iter(positions.values()))))
    return sorted(pairs), mode


def question_scope_sql(*, company=":company", position=":position", canonical=True):
    """One experience must satisfy BOTH filters; never inherit unrelated post tags."""
    match = []
    if company:
        match.append(f"{'c.canonical' if canonical else 'ie.company_id'} = {company}")
    if position:
        match.append(f"{'pos.canonical' if canonical else 'ie.position_id'} = {position}")
    explicit = " AND ".join(match) or "TRUE"
    legacy = []
    single = []
    if company:
        legacy.append(f"{'c.canonical' if canonical else 'pcp.company_id'} = {company}")
        single.append(f"{'c.canonical' if canonical else 'pa.single_company_id'} = {company}")
    if position:
        legacy.append(f"{'pos.canonical' if canonical else 'pcp.position_id'} = {position}")
        single.append(f"{'pos.canonical' if canonical else 'pa.single_position_id'} = {position}")
    return f"""(
        EXISTS(SELECT 1 FROM question_interviews qi
            JOIN interview_experiences ie ON ie.id=qi.interview_id
            LEFT JOIN companies c ON c.id=ie.company_id
            LEFT JOIN positions pos ON pos.id=ie.position_id
            WHERE qi.question_id=q.id AND {explicit})
        OR EXISTS(SELECT 1 FROM post_attribution pa
            LEFT JOIN companies c ON c.id=pa.single_company_id
            LEFT JOIN positions pos ON pos.id=pa.single_position_id
            WHERE pa.post_id=q.post_id AND pa.mode<>'explicit' AND {" AND ".join(single) or "TRUE"})
        OR (NOT EXISTS(SELECT 1 FROM post_attribution pa WHERE pa.post_id=q.post_id)
            {"AND (SELECT COUNT(DISTINCT company_id) FROM post_company_position pc WHERE pc.post_id=q.post_id)=1" if company else ""}
            {"AND (SELECT COUNT(DISTINCT position_id) FROM post_company_position pc WHERE pc.post_id=q.post_id)=1" if position else ""}
            AND EXISTS(SELECT 1 FROM post_company_position pcp
                LEFT JOIN companies c ON c.id=pcp.company_id
                LEFT JOIN positions pos ON pos.id=pcp.position_id
                WHERE pcp.post_id=q.post_id AND {" AND ".join(legacy) or "TRUE"}))
    )"""
