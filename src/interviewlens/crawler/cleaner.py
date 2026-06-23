"""HTML → cleaned text via trafilatura, with a BeautifulSoup fallback."""
from __future__ import annotations

import re
from dataclasses import dataclass

import trafilatura
from bs4 import BeautifulSoup

from ..logging import log


@dataclass(slots=True)
class CleanedDoc:
    title: str | None
    text: str
    char_count: int


# -----------------------------------------------------------------
# Nowcoder UI noise stripping
#
# Tab-crawler falls back to document.body.innerText when CSS selectors
# miss, dragging in action bars, comment boxes, sidebar ads, etc.
# These patterns strip that noise line-by-line for both new and
# already-crawled data.
# -----------------------------------------------------------------

# Entire lines that are pure UI chrome (high-precision, zero false positives)
_NC_NOISE_LINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^评论\s*点赞\s*收藏.*分享.*浏览\s*\d*\s*$"),
    re.compile(r"^.*点赞\s*收藏.*真题解析.*$"),  # "2 点赞 收藏 真题解析"
    re.compile(r"^一键发评.*表情\s*$"),
    re.compile(r"^首次评论必得.*牛币.*$"),
    re.compile(r"^全部评论.*$"),
    re.compile(r"^暂无评论.*抢首评.*$"),
    re.compile(r"^校招信息汇总表.*$"),
    re.compile(r"^广告\s*$"),
    re.compile(r"^相关推荐\s*$"),
    re.compile(r"^更多真题[：:].*$"),
    re.compile(r"^查看\d+道真题.*$"),
    re.compile(r"^\d+\s+\d+\s+\d+\s*分享\s*点赞.*$"),  # "12 13 11 分享 点赞 2 收藏 分享"
    re.compile(r"^快捷表情\s*$"),
    re.compile(r"^图片\s*话题\s*表情\s*$"),
    re.compile(r"^回复TA\s*$"),
    re.compile(r"^\d+\s*点赞.*$"),  # "2 点赞 收藏"
    # Pure number lines (upvote counts, view counts): "93", "9 42 4", "2 12 1"
    re.compile(r"^\d+(\s+\d+)*\s*$"),
]

# Standalone short tokens that are pure UI (only removed if line is exactly this)
_NC_NOISE_TOKENS: set[str] = {
    "评论", "点赞", "收藏", "分享", "浏览", "真题解析",
    "一键发评", "快捷表情", "图片", "话题", "表情",
    "全部评论", "暂无评论", "广告", "相关推荐", "回复TA",
}

# Marker: once we see a line matching this, everything from that point onward
# is the comment section / engagement area — truncate the rest.
# Nowcoder action bar always contains "点赞" + "收藏" together.
_NC_COMMENT_MARKER = re.compile(r"点赞.*收藏|收藏.*点赞")


def strip_nowcoder_noise(text: str) -> str:
    """Remove Nowcoder page UI elements that leak into cleaned_text.

    Two-phase approach:
    1. **Truncate** at the comment-section marker — the Nowcoder action bar
       (contains "点赞" + "收藏") always appears after the post body and
       before the comment section.  Everything after it is noise.
    2. **Line-filter** residual UI patterns (pure numbers, UI tokens, etc.)
       that may appear before the marker.
    """
    if not text:
        return text

    lines = text.splitlines()

    # Phase 1: find the comment-section marker and truncate
    cutoff = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip very short lines — the marker is a specific action-bar pattern
        if len(stripped) < 4:
            continue
        if _NC_COMMENT_MARKER.search(stripped) and len(stripped) < 30:
            cutoff = i
            break
    lines = lines[:cutoff]

    # Phase 2: line-level filtering
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append(line)  # preserve blank lines for readability
            continue
        # Drop lines matching multi-word UI patterns
        if any(p.search(stripped) for p in _NC_NOISE_LINE_PATTERNS):
            continue
        # Drop lines that are exactly a UI token
        if stripped in _NC_NOISE_TOKENS:
            continue
        # Drop "查看N道真题和解析" style lines
        if re.match(r"^查看\d+道", stripped):
            continue
        kept.append(line)

    # Collapse 3+ consecutive blank lines to 2
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    return result.strip()


def clean_html(html: str, *, url: str | None = None) -> CleanedDoc:
    """Return main-content plain text suitable for LLM extraction.

    Strategy:
      1. Trafilatura with favor_recall=True (best for forum-style pages).
      2. Fallback: BeautifulSoup, drop nav/header/footer/script/style, take body text.
    """
    text = ""
    title: str | None = None

    try:
        text = trafilatura.extract(
            html,
            url=url,
            favor_recall=True,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        ) or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("clean.trafilatura_failed", err=str(exc))
        text = ""

    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    if len(text) < 100:
        log.info("clean.fallback_to_bs4", trafilatura_chars=len(text))
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
            tag.decompose()
        body = soup.body or soup
        text = body.get_text("\n", strip=True)

    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = strip_nowcoder_noise(text)
    return CleanedDoc(title=title, text=text, char_count=len(text))
