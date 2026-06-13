"""Demo seed: insert deterministic mock data so the UI is demoable without
running the full crawler. Idempotent — safe to re-run.

Use case: simply give a recruiter or interviewer a runnable demo that doesn't
depend on having a working Nowcoder cookie.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from .db import (
    AliasDict,
    Company,
    Position,
    Post,
    PostCompanyPosition,
    Question,
    Summary,
    session_scope,
)
from .logging import log

NOW = datetime.now(timezone.utc).replace(tzinfo=None)

DEMO_COMPANIES = [
    ("字节跳动", "互联网"),
    ("腾讯", "互联网"),
    ("阿里巴巴", "互联网"),
    ("美团", "互联网"),
    ("百度", "互联网"),
]

DEMO_POSITIONS = [
    ("后端开发", "后端"),
    ("前端开发", "前端"),
    ("算法工程师", "算法"),
    ("大模型算法", "算法"),
]

# (company, position, [(round_no, round_type, [(content, category, answer?)])])
DEMO_POSTS = [
    (
        "字节跳动",
        "后端开发",
        "字节后端一面",
        [
            (1, "技术一面", [
                ("Redis 分布式锁如何实现，Redisson 是怎么做的？", "数据库", "SETNX + 看门狗续期"),
                ("讲讲项目里最难的一个技术点", "项目", None),
                ("MySQL 索引下推是什么", "数据库", "ICP，把 WHERE 推到引擎层减少回表"),
                ("讲讲 TCP 三次握手", "网络", None),
            ]),
            (2, "技术二面", [
                ("Go 调度器 GMP 模型", "语言基础", None),
                ("一致性哈希原理", "系统设计", "虚拟节点解决数据倾斜"),
                ("LSM Tree 与 B+ Tree 的差异", "数据库", None),
            ]),
        ],
    ),
    (
        "字节跳动",
        "后端开发",
        "字节后端二面",
        [
            (1, "技术一面", [
                ("Redis 分布式锁的实现方案有哪些", "数据库", None),
                ("MySQL InnoDB 的隔离级别", "数据库", "RR + MVCC + Gap Lock"),
                ("讲一下 Java 老年代 GC", "语言基础", None),
            ]),
        ],
    ),
    (
        "腾讯",
        "后端开发",
        "腾讯 WXG 后端面经",
        [
            (1, "技术一面", [
                ("讲讲 HTTP/2 多路复用", "网络", None),
                ("Redis 持久化机制 RDB vs AOF", "数据库", None),
                ("Linux IO 模型 select / poll / epoll", "操作系统", "epoll 红黑树 + 就绪链表"),
            ]),
            (2, "技术二面", [
                ("分布式事务怎么实现", "系统设计", None),
                ("项目里高并发场景的处理", "项目", None),
            ]),
        ],
    ),
    (
        "阿里巴巴",
        "算法工程师",
        "阿里推荐算法面经",
        [
            (1, "技术一面", [
                ("Transformer 的 attention 计算复杂度", "算法", "O(n^2 d)"),
                ("BERT 和 GPT 在结构上的差异", "算法", None),
                ("项目里 AUC 怎么提升的", "项目", None),
            ]),
        ],
    ),
    (
        "美团",
        "前端开发",
        "美团前端实习面经",
        [
            (1, "技术一面", [
                ("Promise 链式调用原理", "语言基础", None),
                ("React diff 算法", "项目", "key 配合复用"),
                ("浏览器从输入 URL 到页面呈现", "网络", None),
            ]),
        ],
    ),
]


def _mk_summary(company: str, position: str, sample: int) -> str:
    return f"""## 高频考点 Top 10

1. **Redis 分布式锁** — 出现 {max(2, sample // 3)} 次
   > Redis 分布式锁如何实现，Redisson 是怎么做的？
   > Redis 分布式锁的实现方案有哪些

2. **MySQL InnoDB 内部机制** — 出现 {max(2, sample // 4)} 次
   > MySQL InnoDB 的隔离级别
   > MySQL 索引下推是什么

3. **网络协议栈基础** — 出现 {max(1, sample // 5)} 次
   > 讲讲 TCP 三次握手
   > 讲讲 HTTP/2 多路复用

## 重点考察方向

- **分布式系统**：分布式锁、分布式事务、一致性哈希
- **数据库内核**：索引、隔离级别、MVCC
- **JVM/Go 运行时**：GC 策略、调度器
- **网络协议**：TCP、HTTP/2、IO 模型

## 易忽略的偏门题

> Linux IO 模型 select / poll / epoll
> LSM Tree 与 B+ Tree 的差异

## 备考建议

- **重点突击 Redis 分布式锁** — 几乎每场必考；准备 SETNX/Redisson/Redlock 三种方案的差异
- **MySQL 索引下推 (ICP) 与 MVCC** — {company} 后端面试高频；要能手画 Gap Lock 的范围
- **Linux epoll 事件机制** — 比 select/poll 出现频次更高；准备红黑树 + 就绪链表的细节
- **手写一致性哈希** — 至少能讲清楚虚拟节点解决数据倾斜的逻辑
- **项目最难点要背熟** — {company} 面试官非常抠项目细节，准备 STAR 法则的三个版本
"""


async def seed_demo() -> dict:
    """Insert demo companies, positions, posts, questions, summaries.

    Idempotent: skips entities that already exist.
    """
    counts = {"companies": 0, "positions": 0, "posts": 0, "questions": 0, "summaries": 0}

    async with session_scope() as session:
        # --- companies ---
        company_ids: dict[str, int] = {}
        for name, industry in DEMO_COMPANIES:
            row = (
                await session.execute(select(Company).where(Company.canonical == name))
            ).scalar_one_or_none()
            if row is None:
                row = Company(canonical=name, industry=industry)
                session.add(row)
                await session.flush()
                counts["companies"] += 1
            company_ids[name] = row.id  # type: ignore

        # --- positions ---
        position_ids: dict[str, int] = {}
        for name, category in DEMO_POSITIONS:
            row = (
                await session.execute(select(Position).where(Position.canonical == name))
            ).scalar_one_or_none()
            if row is None:
                row = Position(canonical=name, category=category)
                session.add(row)
                await session.flush()
                counts["positions"] += 1
            position_ids[name] = row.id  # type: ignore

        # --- posts ---
        for i, (cname, pname, title, rounds) in enumerate(DEMO_POSTS):
            url = f"https://www.nowcoder.com/discuss/demo-{i+1:03d}"
            existing = (
                await session.execute(select(Post).where(Post.source_url == url))
            ).scalar_one_or_none()
            if existing is not None:
                continue
            posted_at = NOW - timedelta(days=random.randint(15, 120))
            quality_score = 50 + random.randint(10, 40)
            post = Post(
                source_url=url,
                title=title,
                cleaned_text="(demo seed; original cleaned text omitted)",
                posted_at=posted_at,
                fetched_at=NOW,
                extract_status="done",
                extract_version=1,
                quality_score=quality_score,
            )
            session.add(post)
            await session.flush()
            counts["posts"] += 1

            # link
            session.add(
                PostCompanyPosition(
                    post_id=post.id, company_id=company_ids[cname], position_id=position_ids[pname]
                )
            )

            for round_no, round_type, qs in rounds:
                for content, category, ans in qs:
                    session.add(
                        Question(
                            post_id=post.id,
                            round_no=round_no,
                            round_type=round_type,
                            content=content,
                            category=category,
                            answer_brief=ans,
                        )
                    )
                    counts["questions"] += 1

        # --- summaries ---
        # one for 字节后端 / all, one for 腾讯后端 / all
        for cname, pname, sample in [
            ("字节跳动", "后端开发", 7),
            ("腾讯", "后端开发", 5),
        ]:
            stmt = pg_insert(Summary).values(
                company_id=company_ids[cname],
                position_id=position_ids[pname],
                period="all",
                content_md=_mk_summary(cname, pname, sample),
                sample_count=sample,
                updated_at=NOW,
            ).on_conflict_do_update(
                index_elements=["company_id", "position_id", "period"],
                set_={
                    "content_md": _mk_summary(cname, pname, sample),
                    "sample_count": sample,
                    "updated_at": NOW,
                },
            )
            await session.execute(stmt)
            counts["summaries"] += 1

    log.info("seed_demo.done", **counts)
    return counts


def main() -> None:
    asyncio.run(seed_demo())


if __name__ == "__main__":
    main()
