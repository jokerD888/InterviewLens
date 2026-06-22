"""All LLM prompts. Mirrors docs/PROMPT_LIBRARY.md, single source of truth in code."""
from __future__ import annotations

from ..config import settings

# ---------------------------------------------------------------- Extractor

EXTRACTOR_SYSTEM = """你是面经信息抽取助手。任务：从用户给的面经文本中抽取结构化信息。

铁律：
1. 不臆造内容。原文没说的字段一律填 null 或留空数组。
2. 公司/岗位名保持原文形式，不要主动规范化（这一步交给后续节点）。
3. 题目原文必须完整保留，不要总结、不要改写、不要合并。
4. 如果一段话明显是抒情/吐槽/无关内容，跳过不抽。
5. 答案要点（answer_brief）只在原帖明确给出时填写，不要替原帖编答案。

输出：调用 extract_interview_post 函数，参数严格符合 schema。"""


def get_extractor_prompt_version() -> int:
    return settings.extract_prompt_version


def build_extractor_messages(cleaned_text: str) -> list[dict]:
    """Compose chat messages for Extractor."""
    return [
        {"role": "system", "content": EXTRACTOR_SYSTEM},
        {
            "role": "user",
            "content": f"以下是一篇面经文本，请抽取结构化信息：\n\n---\n{cleaned_text}\n---",
        },
    ]


# --------------------------------------------------------------- Normalizer

NORMALIZER_SYSTEM = """你是实体归一化助手。任务：判断给定别名是否对应已有规范实体，
或新建一个规范名。

判断原则：
- 公司：「字节」「Bytedance」「ByteDance」「抖音」「TikTok」均归到「字节跳动」；
  「鹅厂」→ 腾讯；「猪厂」→ 网易；「狼厂」→ 百度；「淘天」「蚂蚁」需独立建条目，不归到「阿里巴巴」。
- 岗位：「Java 后端」「服务端」「后台开发」「Java 开发」均归到「后端开发」；
  「推荐算法」「广告算法」「NLP 算法」均归到「算法工程师」；
  「LLM 算法」「大模型算法」独立建条目「大模型算法」。
- 不确定时 confidence < 0.7，宁可新建不要错配。

输出：调用 decide_canonical 函数，参数严格符合 schema。"""


def build_normalizer_messages(
    *,
    entity_type: str,
    alias: str,
    candidates: list[dict],
) -> list[dict]:
    """Compose messages for Normalizer.

    candidates: list of {id, canonical, similarity} sorted by similarity desc.
    """
    cand_lines = "\n".join(
        f"- id={c['id']} canonical={c['canonical']} sim={c['similarity']:.3f}"
        for c in candidates
    ) or "(无候选)"
    user = (
        f"实体类型：{entity_type}\n"
        f"待判断别名：「{alias}」\n\n"
        f"候选规范实体（按 embedding 相似度排序的 top-5）：\n{cand_lines}"
    )
    return [
        {"role": "system", "content": NORMALIZER_SYSTEM},
        {"role": "user", "content": user},
    ]


NORMALIZE_FUNCTION_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "decide_canonical",
        "description": "判断别名是否对应已有规范实体，或建议新建",
        "parameters": {
            "type": "object",
            "required": ["decision", "confidence", "reason"],
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["match", "new"],
                    "description": "match 表示命中候选；new 表示需要新建规范条目",
                },
                "canonical_id": {
                    "type": ["integer", "null"],
                    "description": "decision=match 时填候选 id；否则 null",
                },
                "canonical_name": {
                    "type": ["string", "null"],
                    "description": "decision=new 时建议的规范名",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "reason": {
                    "type": "string",
                    "description": "一句话理由",
                },
            },
        },
    },
}


# --------------------------------------------------------------- Aggregator

AGGREGATOR_SYSTEM = """你是面试备考助手。基于用户给出的真实面试题目（已按公司+岗位+季度筛选），
总结高频考点并给出备考建议。

你必须输出一个 JSON 对象，严格遵守下方 schema。不要输出任何 JSON 之外的文字。

铁律：
1. high_frequency_topics 至少 3 条，每条 sample_questions 至少 1 道原题（必须来自给定列表）。
2. focus_areas 至少 3 条，要具体到技术点（如「BTree vs LSM 比较」「ZSet 内部结构」），不要空话。
3. edge_cases 至少 1 条（没有偏门题也要挑一道相对冷门的填入）。
4. prep_advice 至少 3 条，针对该公司该岗位，不要通用空话。
5. 不要编造题目；sample_questions 必须来自给定列表。
6. 只输出 JSON，不要加 markdown 代码围栏，不要加任何解释性文字。
7. 【最重要】禁止输出空数组 [] 或空字符串，每个字段都必须有内容。"""


# JSON schema for aggregator output — structured data, rendered to markdown in code.
# This guarantees 100% format consistency across all LLM calls.
AGGREGATOR_JSON_SCHEMA: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "interview_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "required": [
                "high_frequency_topics",
                "focus_areas",
                "edge_cases",
                "prep_advice",
            ],
            "properties": {
                "high_frequency_topics": {
                    "type": "array",
                    "description": "高频考点 Top 10，按频次降序。最多 10 条。",
                    "items": {
                        "type": "object",
                        "required": ["topic", "frequency", "sample_questions"],
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "考点名称，如「大模型微调实践」",
                            },
                            "frequency": {
                                "type": "integer",
                                "description": "出现频次",
                            },
                            "sample_questions": {
                                "type": "array",
                                "description": "1-2 道原题原文，必须来自题目列表",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "focus_areas": {
                    "type": "array",
                    "description": "重点考察方向，3-5 个分类总结",
                    "items": {"type": "string"},
                },
                "edge_cases": {
                    "type": "array",
                    "description": "易忽略的偏门题（频次 1-2 但有特点）",
                    "items": {
                        "type": "object",
                        "required": ["topic", "questions"],
                        "properties": {
                            "topic": {"type": "string"},
                            "questions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "prep_advice": {
                    "type": "array",
                    "description": "针对该公司该岗位的备考建议，3-5 条",
                    "items": {"type": "string"},
                },
            },
            "additionalProperties": False,
        },
    },
}


def render_aggregator_md(data: dict) -> str:
    """Render structured aggregator JSON → consistent markdown.

    This is the single source of truth for summary formatting.
    LLM only fills data; formatting is 100% deterministic.
    """
    parts: list[str] = []

    # ── 高频考点 Top 10 ──
    topics = data.get("high_frequency_topics") or []
    if topics:
        parts.append("## 高频考点 Top 10\n")
        for t in topics:
            name = t.get("topic", "")
            freq = t.get("frequency", 1)
            parts.append(f"### {name} <sub>×{freq}</sub>\n")
            for q in t.get("sample_questions") or []:
                parts.append(f"> {q}\n")
            parts.append("")

    # ── 重点考察方向 ──
    areas = data.get("focus_areas") or []
    if areas:
        parts.append("## 重点考察方向\n")
        for a in areas:
            parts.append(f"- {a}")
        parts.append("")

    # ── 易忽略的偏门题 ──
    edges = data.get("edge_cases") or []
    if isinstance(edges, dict):
        edges = [edges]  # LLM may return a single object instead of array
    if edges:
        parts.append("## 易忽略的偏门题\n")
        for e in edges:
            if not isinstance(e, dict):
                continue
            name = e.get("topic", "")
            parts.append(f"### {name}\n")
            for q in e.get("questions") or []:
                parts.append(f"> {q}\n")
            parts.append("")

    # ── 备考建议 ──
    advice = data.get("prep_advice") or []
    if advice:
        parts.append("## 备考建议\n")
        for i, a in enumerate(advice, 1):
            parts.append(f"{i}. {a}")
        parts.append("")

    return "\n".join(parts)


def build_aggregator_messages(
    *,
    company: str,
    position: str,
    period: str,
    questions: list[dict],
) -> list[dict]:
    """Compose Aggregator messages — now requests JSON output.

    questions: list of {content, category, freq, quality_score, source_url}
    sorted by freq desc.
    """
    lines = []
    for i, q in enumerate(questions, 1):
        cat = q.get("category") or ""
        freq = q.get("freq") or 1
        prefix = f"{i:3}. [{cat}]" if cat else f"{i:3}."
        lines.append(f"{prefix} (freq={freq}) {q['content']}")
    questions_block = "\n".join(lines) or "(无题目)"

    user = (
        f"公司：{company}\n"
        f"岗位：{position}\n"
        f"周期：{period}\n"
        f"题目数：{len(questions)}\n\n"
        f"题目列表（按频次排序）：\n{questions_block}\n\n"
        "请输出 JSON，字段说明：\n"
        "- high_frequency_topics: 高频考点 Top 10，按频次降序\n"
        "- focus_areas: 重点考察方向，3-5 个字符串\n"
        "- edge_cases: 偏门题，每个含 topic + questions 数组\n"
        "- prep_advice: 针对性备考建议，3-5 条字符串\n\n"
        "只输出 JSON，不要任何其他内容。"
    )
    return [
        {"role": "system", "content": AGGREGATOR_SYSTEM},
        {"role": "user", "content": user},
    ]


# ----------------------------------------------------------------- Answerer

ANSWERER_SYSTEM = """你是资深技术面试官，为面经题目撰写参考答案，帮助求职者备考。

铁律：
1. 难度自适应：简单概念题用 2-3 句直接讲透，不堆字凑长度；复杂题再展开，
   可分点、用代码块或对比，但每一点都要有信息量，不灌水。
2. 输出纯 Markdown（可用标题、列表、代码块、**强调**），不要包在代码围栏里。
3. 讲清原理与考察点，面向面试场景；不要「多刷题」「夯实基础」这类空话。
4. 题目信息不足或超出常规知识范围无法作答时，直说「题目信息不足」，绝不可编造。"""


def build_answerer_messages(*, content: str, category: str | None) -> list[dict]:
    """Compose chat messages for the Answerer (one question per call)."""
    cat_hint = f"（分类：{category}）" if category else ""
    user = f"请为下面这道面试题写参考答案{cat_hint}：\n\n{content}"
    return [
        {"role": "system", "content": ANSWERER_SYSTEM},
        {"role": "user", "content": user},
    ]
