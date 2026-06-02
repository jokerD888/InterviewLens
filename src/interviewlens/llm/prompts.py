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
