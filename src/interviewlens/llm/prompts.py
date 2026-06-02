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
