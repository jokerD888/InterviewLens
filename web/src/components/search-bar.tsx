"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";

type Props = {
  initial?: string;
  placeholder?: string;
  onSubmit: (q: string) => void;
};

export function SearchBar({ initial = "", placeholder, onSubmit }: Props) {
  const [value, setValue] = useState(initial);

  useEffect(() => setValue(initial), [initial]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const q = value.trim();
        if (q) onSubmit(q);
      }}
      className="flex items-center gap-3 border-b-2 border-ink/70 bg-transparent px-1 py-2 transition focus-within:border-accent"
    >
      <Search className="h-5 w-5 shrink-0 text-accent" />
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder ?? "语义检索面试题 — 例如：分布式锁的实现方式"}
        className="flex-1 bg-transparent font-serif text-lg text-ink outline-none placeholder:text-muted/70"
      />
      <button
        type="submit"
        className="shrink-0 rounded-sm bg-ink px-4 py-1.5 font-mono text-[11px] uppercase tracking-widest text-bg transition hover:bg-accent"
      >
        检索
      </button>
    </form>
  );
}
