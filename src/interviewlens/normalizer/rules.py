"""Negative rules and lexical gating for entity resolution.

Prevents false-positive entity mergers between semantically close but
mutually exclusive concepts (e.g. '前端开发' vs '后端开发', 'Java' vs 'Go',
'Android' vs 'iOS', or distinct companies).
"""
from __future__ import annotations

import re

# ----------------------------------------------------------------------
# Position Incompatibility Rules
# ----------------------------------------------------------------------

# Language/Tech stack exclusivity: two positions mentioning different specific
# stacks cannot be canonicalized to each other.
PROGRAMMING_LANGUAGES = {
    "java": ["java"],
    "golang": ["go", "golang"],
    "cpp": ["c++", "cpp"],
    "python": ["python"],
    "rust": ["rust"],
    "csharp": ["c#", "csharp", ".net"],
    "php": ["php"],
}

# Domain / Role exclusivity
ROLE_DOMAINS = {
    "frontend": ["前端", "frontend", "web前端", "h5", "html"],
    "backend": ["后端", "服务端", "后台", "backend", "server"],
    "client": ["客户端", "移动端", "移动开发", "client", "mobile"],
    "ios": ["ios", "iphone", "swift", "objective-c"],
    "android": ["android", "安卓"],
    "qa": ["测试", "测开", "qa", "质量保障", "测试开发", "test"],
    "algo": ["算法", "algorithm", "机器学习", "深度学习", "ai", "nlp", "cv", "大模型"],
    "pm": ["产品经理", "产品策划", "pm", "product manager"],
    "sre": ["运维", "sre", "devops", "系统工程"],
    "dba": ["dba", "数据库管理员"],
    "data_analysis": ["数据分析", "商业分析", "bi"],
    "ui_ux": ["ui", "ux", "交互设计", "视觉设计"],
}

# Incompatible domain pairs (symmetric)
INCOMPATIBLE_ROLE_PAIRS = [
    ("frontend", "backend"),
    ("frontend", "ui_ux"),
    ("frontend", "pm"),
    ("backend", "qa"),
    ("backend", "pm"),
    ("backend", "ui_ux"),
    ("ios", "android"),
    ("client", "backend"),
    ("qa", "pm"),
    ("algo", "pm"),
    ("algo", "qa"),
    ("dba", "frontend"),
]


def _extract_matched_tags(text: str, tag_dict: dict[str, list[str]]) -> set[str]:
    lowered = text.lower()
    matches = set()
    for tag_key, keywords in tag_dict.items():
        for kw in keywords:
            # Word boundary check for ascii keywords like 'go', 'c++', 'pm'
            if re.match(r"^[a-zA-Z0-9\+\#\.]+$", kw):
                pattern = rf"(?<![a-zA-Z0-9]){re.escape(kw)}(?![a-zA-Z0-9])"
                if re.search(pattern, lowered):
                    matches.add(tag_key)
                    break
            else:
                if kw in lowered:
                    matches.add(tag_key)
                    break
    return matches


def are_positions_incompatible(pos_a: str, pos_b: str) -> tuple[bool, str]:
    """Return True if two position names are known to be mutually exclusive."""
    # 1. Tech stack language conflict
    langs_a = _extract_matched_tags(pos_a, PROGRAMMING_LANGUAGES)
    langs_b = _extract_matched_tags(pos_b, PROGRAMMING_LANGUAGES)
    if langs_a and langs_b and langs_a.isdisjoint(langs_b):
        return True, f"language_conflict: {list(langs_a)} vs {list(langs_b)}"

    # 2. Role / domain conflict
    domains_a = _extract_matched_tags(pos_a, ROLE_DOMAINS)
    domains_b = _extract_matched_tags(pos_b, ROLE_DOMAINS)
    for d_a in domains_a:
        for d_b in domains_b:
            for pair in INCOMPATIBLE_ROLE_PAIRS:
                if (d_a == pair[0] and d_b == pair[1]) or (d_a == pair[1] and d_b == pair[0]):
                    return True, f"role_domain_conflict: {d_a} vs {d_b}"

    return False, ""


# ----------------------------------------------------------------------
# Company Incompatibility Rules
# ----------------------------------------------------------------------

# Well-known distinct tech giants that should never be merged
KNOWN_COMPANIES = [
    {"byte", "字节", "字节跳动", "bytedance", "toutiao", "今日头条"},
    {"ali", "阿里", "阿里巴巴", "alibaba", "taobao", "淘宝", "ant", "蚂蚁"},
    {"tencent", "腾讯", "腾讯科技", "wechat", "微信"},
    {"meituan", "美团", "美团点评"},
    {"kuaishou", "快手", "快手科技"},
    {"pdd", "拼多多", "pinduoduo"},
    {"xiaohongshu", "小红书", "red"},
    {"baidu", "百度", "baidu online"},
    {"jd", "京东", "jd.com"},
    {"net_ease", "网易", "netease"},
    {"bilibili", "b站", "哔哩哔哩"},
    {"google", "谷歌", "google"},
    {"microsoft", "微软", "microsoft"},
    {"apple", "苹果", "apple"},
    {"huawei", "华为"},
    {"xiaomi", "小米"},
]


def are_companies_incompatible(comp_a: str, comp_b: str) -> tuple[bool, str]:
    """Return True if two company names belong to demonstrably different enterprises."""
    low_a = comp_a.strip().lower()
    low_b = comp_b.strip().lower()
    
    idx_a: int | None = None
    idx_b: int | None = None

    for idx, cluster in enumerate(KNOWN_COMPANIES):
        if any(c in low_a for c in cluster):
            idx_a = idx
        if any(c in low_b for c in cluster):
            idx_b = idx

    if idx_a is not None and idx_b is not None and idx_a != idx_b:
        return True, f"distinct_enterprises: cluster_{idx_a} vs cluster_{idx_b}"

    return False, ""


def is_entity_incompatible(entity_type: str, name_a: str, name_b: str) -> tuple[bool, str]:
    """Public facade for entity incompatibility check."""
    if entity_type == "position":
        return are_positions_incompatible(name_a, name_b)
    if entity_type == "company":
        return are_companies_incompatible(name_a, name_b)
    return False, ""


# ----------------------------------------------------------------------
# Lexical Gating Shield
# ----------------------------------------------------------------------

COMMON_POSITION_SUFFIXES = ["工程师", "开发", "研发", "专家", "研究员", "设计师", "师", "人员", "岗位", "岗"]
COMMON_COMPANY_SUFFIXES = ["集团", "科技", "网络", "在线", "互动", "信息", "软件", "技术", "有限责任公司", "有限公司", "中国", "corp", "inc", "ltd"]


def _strip_suffixes(text: str, suffixes: list[str]) -> str:
    cleaned = text
    changed = True
    while changed:
        changed = False
        for s in suffixes:
            if cleaned.endswith(s) and len(cleaned) > len(s):
                cleaned = cleaned[: -len(s)]
                changed = True
                break
    return cleaned


def _longest_common_substring_len(s1: str, s2: str) -> int:
    m = len(s1)
    n = len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    max_len = 0
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                if dp[i][j] > max_len:
                    max_len = dp[i][j]
            else:
                dp[i][j] = 0
    return max_len


def has_lexical_anchor(name_a: str, name_b: str) -> bool:
    """Check whether name_a and name_b share meaningful lexical tokens or overlap.
    
    Prevents pure-embedding false positives between completely different strings
    that lack character/token correlation.
    """
    clean_a = re.sub(r"[\s\-_/\\（）\(\)]", "", name_a).lower()
    clean_b = re.sub(r"[\s\-_/\\（）\(\)]", "", name_b).lower()

    if not clean_a or not clean_b:
        return False

    # 1. Exact or Substring containment
    if clean_a in clean_b or clean_b in clean_a:
        return True

    # 2. Stem match after stripping standard business/job suffixes
    stem_pos_a = _strip_suffixes(clean_a, COMMON_POSITION_SUFFIXES)
    stem_pos_b = _strip_suffixes(clean_b, COMMON_POSITION_SUFFIXES)
    if stem_pos_a and stem_pos_a == stem_pos_b:
        return True

    stem_comp_a = _strip_suffixes(clean_a, COMMON_COMPANY_SUFFIXES)
    stem_comp_b = _strip_suffixes(clean_b, COMMON_COMPANY_SUFFIXES)
    if stem_comp_a and stem_comp_a == stem_comp_b:
        return True

    # 3. Longest common substring >= 2 characters
    if _longest_common_substring_len(clean_a, clean_b) >= 2:
        return True

    # 4. Character set Jaccard overlap >= 0.25
    set_a = set(clean_a)
    set_b = set(clean_b)
    overlap = len(set_a & set_b)
    union = len(set_a | set_b)
    if union > 0 and (overlap / union) >= 0.25:
        return True

    return False

