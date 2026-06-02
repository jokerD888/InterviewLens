"""HTML → cleaned text via trafilatura, with a BeautifulSoup fallback."""
from __future__ import annotations

from dataclasses import dataclass

import trafilatura
from bs4 import BeautifulSoup

from ..logging import log


@dataclass(slots=True)
class CleanedDoc:
    title: str | None
    text: str
    char_count: int


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
    return CleanedDoc(title=title, text=text, char_count=len(text))
