"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, paths, type PositionFacets, type PostFeedItem } from "@/lib/api";
import { FeedCard } from "@/components/feed-card";
import { EMPTY_FACETS, PositionFacetFilter } from "@/components/position-facets";

export function PositionBrowser({ company }: { company: string | null }) {
  const [facets, setFacets] = useState<PositionFacets>({ ...EMPTY_FACETS });
  const [limit, setLimit] = useState(20);
  const { data, error, isLoading } = useSWR<PostFeedItem[]>(paths.posts({ company, ...facets, limit }), fetcher);
  return (
    <div className="space-y-4">
      <PositionFacetFilter value={facets} onChange={(next) => { setFacets(next); setLimit(20); }} />
      <div className="text-sm text-muted">{company ?? "全部公司"} · 面经帖子</div>
      {isLoading && <p>加载面经…</p>}
      {error && <p role="alert">面经加载失败，请稍后重试。</p>}
      {!isLoading && !error && data?.length === 0 && <p>暂无匹配面经。</p>}
      {data?.map((post) => <FeedCard key={post.id} post={post} />)}
      {data?.length === limit && limit < 100 && <button className="text-sm underline" onClick={() => setLimit(limit + 20)}>加载更多</button>}
      {limit === 100 && data?.length === 100 && <p className="text-xs text-muted">已显示前100篇；更多面经可在“最新面经”中浏览。</p>}
    </div>
  );
}
