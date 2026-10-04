"""Unit tests for HTML cleaner."""
from __future__ import annotations

from interviewlens.crawler.cleaner import clean_html

SAMPLE = """
<!doctype html>
<html lang="zh-CN">
<head><title>字节后端一面</title>
<style>.x{color:red}</style>
</head>
<body>
<header><nav>topbar links</nav></header>
<main>
  <article>
    <h1>字节跳动 后端开发 一面面经</h1>
    <p>2025-10 字节后端一面，问了以下问题：</p>
    <ol>
      <li>讲讲你做的项目里最难的部分</li>
      <li>分布式锁怎么实现，Redis 和 ZK 的差异</li>
      <li>MySQL 索引下推</li>
    </ol>
    <p>面试官人不错，整体一小时。</p>
  </article>
</main>
<footer>copyright</footer>
<script>console.log('hi')</script>
</body>
</html>
"""


def test_clean_extracts_main_text() -> None:
    doc = clean_html(SAMPLE, url="https://example.com/x")
    assert doc.title is not None and "字节" in doc.title
    assert "分布式锁" in doc.text
    assert "MySQL 索引下推" in doc.text
    assert "topbar links" not in doc.text
    assert "copyright" not in doc.text
    assert "console.log" not in doc.text
    assert doc.char_count > 50


def test_clean_handles_minimal() -> None:
    doc = clean_html("<html><body><p>abc</p></body></html>")
    assert doc.text == "abc"


def test_strip_nowcoder_noise_preserves_system_design_questions() -> None:
    from interviewlens.crawler.cleaner import strip_nowcoder_noise

    raw = """
1. 自我介绍
2. MySQL 索引失效场景
3. 请设计一个高并发点赞和收藏系统
4. 点赞收藏功能的数据一致性如何保证？
5. 反问环节
点赞 24 收藏 18 分享
全部评论 (12)
    """.strip()

    cleaned = strip_nowcoder_noise(raw)
    assert "请设计一个高并发点赞和收藏系统" in cleaned
    assert "点赞收藏功能的数据一致性如何保证？" in cleaned
    assert "反问环节" in cleaned
    assert "全部评论" not in cleaned
    assert "点赞 24 收藏 18 分享" not in cleaned
