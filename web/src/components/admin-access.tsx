"use client";
import { useState } from "react";
import { useSWRConfig } from "swr";

export function AdminAccess() {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const { mutate } = useSWRConfig();
  async function login(event: React.FormEvent) {
    event.preventDefault();
    try {
      const response = await fetch("/api/admin/health", { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) { setMessage("管理员凭据无效或服务不可用。"); return; }
      sessionStorage.setItem("il-admin-token", token);
      setToken(""); setOpen(false); setMessage("");
      await mutate(() => true);
    } catch { setMessage("服务暂时不可用，请稍后重试。"); }
  }
  return <div className="relative">
    <button className="px-2 py-1 text-muted hover:text-ink" onClick={() => setOpen(!open)}>管理登录</button>
    {open && <form onSubmit={(e) => void login(e)} className="absolute right-0 z-50 mt-2 w-72 space-y-3 border border-rule bg-bg p-4 text-sm normal-case tracking-normal">
      <label>管理员凭据<input type="password" autoComplete="off" required value={token} onChange={(e) => setToken(e.target.value)} className="mt-1 w-full border border-rule bg-transparent p-2" /></label>
      {message && <p role="alert">{message}</p>}
      <button type="submit" className="border border-rule px-3 py-1">登录</button>
      <button type="button" className="ml-3" onClick={() => { sessionStorage.removeItem("il-admin-token"); setOpen(false); void mutate(() => true); }}>退出</button>
    </form>}
  </div>;
}
