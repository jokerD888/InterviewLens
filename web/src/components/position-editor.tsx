"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { fetcher, mutate as apiMutate, paths, type PositionEditorState, type PositionProfile, type PositionTaxonomy } from "@/lib/api";

type Edit = Pick<PositionProfile, "category" | "specializations" | "domains" | "skills">;
const empty = (): Edit => ({ category: null, specializations: [], domains: [], skills: [] });

export function PositionEditor() {
  const { data: taxonomy } = useSWR<PositionTaxonomy>(paths.positionTaxonomy(), fetcher);
  const { mutate } = useSWRConfig();
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const { data: posts, error: listError } = useSWR<{ id: number; title: string | null }[]>(paths.positionPosts(submitted), fetcher);
  const [loaded, setLoaded] = useState<PositionEditorState | null>(null);
  const [edits, setEdits] = useState<Edit[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load(id: number) {
    setBusy(true); setMessage(""); setLoaded(null);
    try {
      const state = await fetcher<PositionEditorState>(paths.positionEditor(id));
      setLoaded(state);
      setEdits(state.profiles.length ? state.profiles.map(({ category, specializations, domains, skills }) => ({ category, specializations, domains, skills })) : [empty()]);
    } catch { setMessage("加载失败，请重试。"); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!loaded) return;
    setBusy(true); setMessage("");
    try {
      const state = await apiMutate.positionProfiles(loaded.post_id, { revision: loaded.revision, profiles: edits });
      setLoaded(state);
      await mutate((key) => typeof key === "string" && (key.includes("/posts") || key === paths.positionTaxonomy()), undefined, { revalidate: true });
      setMessage("分类已保存。");
    } catch (error) {
      setMessage((error as Error).message.includes("409") ? "分类或原文已变化，请重新加载后修改。" : "保存失败，请重试。");
    } finally { setBusy(false); }
  }
  function change(index: number, next: Edit) { setEdits(edits.map((item, i) => i === index ? next : item)); }
  return <div className="space-y-4">
    <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); setSubmitted(query.trim()); }}>
      <input aria-label="查找面经" placeholder="帖子标题或编号" value={query} onChange={(event) => setQuery(event.target.value)} className="min-w-0 flex-1 border border-rule bg-transparent px-2 py-1" />
      <button type="submit" className="border border-rule px-3">查找</button>
    </form>
    {listError && <p role="alert">面经列表加载失败，请刷新重试。</p>}
    <div className="max-h-48 overflow-y-auto space-y-1">
      {posts?.map((post) => <button disabled={busy} key={post.id} onClick={() => void load(post.id)} className="block w-full text-left text-sm hover:text-accent">#{post.id} · {post.title ?? "无标题"}</button>)}
      {posts?.length === 0 && <p>没有找到面经。</p>}
    </div>
    {loaded && taxonomy && <div className="space-y-3">
      <p className="text-sm">正在修改：#{loaded.post_id} · {loaded.title}</p>
      {edits.map((edit, index) => <fieldset disabled={busy} key={index} className="space-y-3 border border-rule p-3">
        <legend>岗位 {index + 1}</legend>
        <label>一级岗位 <select aria-label={`岗位 ${index + 1} 一级岗位`} value={edit.category ?? ""} onChange={(event) => change(index, { ...edit, category: event.target.value || null })} className="bg-panel px-2 py-1">
          <option value="">未明确</option>{taxonomy.categories.map((item) => <option key={item}>{item}</option>)}
        </select></label>
        {([["specializations", "技术方向"], ["domains", "业务领域"], ["skills", "技术栈"]] as const).map(([field, label]) => <details key={field}>
          <summary className="cursor-pointer">{label}：{edit[field].join(" / ") || "未设置"}</summary>
          <div className="mt-2 flex max-h-48 flex-wrap gap-3 overflow-y-auto">{taxonomy[field].map((item) => <label key={item} className="text-xs">
            <input type="checkbox" checked={edit[field].includes(item)} onChange={(event) => change(index, { ...edit, [field]: event.target.checked ? [...edit[field], item] : edit[field].filter((value) => value !== item) })} /> {item}
          </label>)}</div>
        </details>)}
        {edits.length > 1 && <button onClick={() => setEdits(edits.filter((_, i) => i !== index))} type="button" className="text-xs underline">移除此岗位</button>}
      </fieldset>)}
      <div className="flex gap-4 text-sm">
        <button disabled={busy || edits.length >= 20} onClick={() => setEdits([...edits, empty()])}>添加岗位</button>
        <button disabled={busy} onClick={() => void load(loaded.post_id)}>重新加载</button>
        <button disabled={busy} onClick={() => void save()} className="bg-accent px-3 py-1 text-bg">{busy ? "处理中…" : "保存分类"}</button>
      </div>
    </div>}
    {message && <p role="status">{message}</p>}
  </div>;
}
