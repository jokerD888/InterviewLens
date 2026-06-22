"use client";

import { useState, useEffect, useRef } from "react";
import useSWRInfinite from "swr/infinite";
import { Loader2 } from "lucide-react";
import { fetcher, paths, type PostFeedItem } from "@/lib/api";
import { FeedCard } from "@/components/feed-card";
import { FeedFilterBar } from "@/components/feed-filter-bar";

export default function FeedPage() {
  const [company, setCompany] = useState<string | null>(null);
  const [position, setPosition] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);

  const PAGE_SIZE = 20;

  const getKey = (pageIndex: number, previousPageData: PostFeedItem[] | null) => {
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
    return paths.posts({
      company,
      position,
      category,
      limit: PAGE_SIZE,
      offset: pageIndex * PAGE_SIZE,
    });
  };

  const { data, size, setSize, isLoading, isValidating, error } = useSWRInfinite<
    PostFeedItem[]
  >(getKey, fetcher, { revalidateFirstPage: false });

  const posts = data ? data.flat() : [];
  const isReachingEnd = data && data.length > 0
    ? data[data.length - 1].length < PAGE_SIZE
    : false;
  const loadingMore = isValidating && data != null;

  // Reset size when filters change
  useEffect(() => {
    setSize(1);
  }, [company, position, category, setSize]);

  // Infinite scroll sentinel
  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isReachingEnd && !isValidating) {
          setSize((s) => s + 1);
        }
      },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [isReachingEnd, isValidating, setSize]);

  return (
    <div className="mx-auto max-w-screen-xl space-y-5 px-6 py-6">
      <div className="rise rise-1">
        <p className="font-mono text-[10px] uppercase tracking-[0.3em] text-accent">
          最新面经
        </p>
        <h1 className="mt-1 font-display text-2xl font-black tracking-tight text-ink">
          按时间浏览面试帖子
        </h1>
      </div>

      <FeedFilterBar
        company={company}
        position={position}
        category={category}
        onCompanyChange={setCompany}
        onPositionChange={setPosition}
        onCategoryChange={setCategory}
      />

      {error && (
        <p className="font-mono text-[11px] text-warn">
          加载失败，请稍后重试
        </p>
      )}

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-28 animate-pulse rounded-md bg-sunk/50"
            />
          ))}
        </div>
      )}

      {!isLoading && posts.length === 0 && (
        <p className="py-12 text-center font-serif text-lg text-muted">
          暂无匹配帖子
        </p>
      )}

      <div className="space-y-0">
        {posts.map((post) => (
          <FeedCard key={post.id} post={post} />
        ))}
      </div>

      {/* Sentinel for infinite scroll */}
      {!isReachingEnd && (
        <div ref={sentinelRef} className="flex items-center justify-center py-6">
          {loadingMore && (
            <Loader2 className="h-4 w-4 animate-spin text-muted" />
          )}
        </div>
      )}

      {isReachingEnd && posts.length > 0 && (
        <p className="py-6 text-center font-mono text-[10px] uppercase tracking-widest text-muted/60">
          — 已加载全部 —
        </p>
      )}
    </div>
  );
}
