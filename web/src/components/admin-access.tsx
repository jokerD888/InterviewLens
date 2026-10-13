"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { HttpError } from "@/lib/api";

const TOKEN_KEY = "il-admin-token";
type Phase = "checking" | "signed-out" | "signed-in";

function validationMessage(status: number) {
  if (status === 401 || status === 403) return "管理员凭据无效，请重新输入。";
  if (status === 503) return "后台尚未配置或暂时不可用，请稍后重试。";
  return "服务暂时不可用，请稍后重试。";
}

async function validateToken(token: string, signal: AbortSignal) {
  return fetch("/api/admin/health", {
    headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal,
  });
}

/** Only mounted at /admin; privileged children wait for backend validation. */
export function AdminGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    let active = true;
    async function restore() {
      try {
        const stored = sessionStorage.getItem(TOKEN_KEY);
        if (!stored) {
          if (active) setPhase("signed-out");
          return;
        }
        const response = await validateToken(stored, controller.signal);
        if (!active) return;
        if (response.ok) {
          setPhase("signed-in");
        } else {
          if (response.status === 401 || response.status === 403) sessionStorage.removeItem(TOKEN_KEY);
          setMessage(validationMessage(response.status));
          setPhase("signed-out");
        }
      } catch {
        if (active) {
          setMessage("无法验证管理登录，请检查服务后重试。");
          setPhase("signed-out");
        }
      } finally { clearTimeout(timeout); }
    }
    void restore();
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  function logout(reason = "") {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setMessage(reason);
    setPhase("signed-out");
  }

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const credential = token.trim();
    if (!credential || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await validateToken(credential, AbortSignal.timeout(10_000));
      if (!response.ok) { setMessage(validationMessage(response.status)); return; }
      sessionStorage.setItem(TOKEN_KEY, credential);
      setToken("");
      setPhase("signed-in");
    } catch { setMessage("服务暂时不可用，请稍后重试。"); }
    finally { setBusy(false); }
  }

  if (phase === "checking") {
    return <p role="status" className="mx-auto max-w-screen-xl px-6 py-12 text-muted">正在验证管理登录…</p>;
  }
  if (phase === "signed-out") {
    return (
      <section className="mx-auto max-w-md px-6 py-12">
        <h1 className="font-display text-2xl font-black text-ink">后台管理登录</h1>
        <p className="mt-3 text-sm text-muted">请输入管理员凭据以进入管理后台。</p>
        <form onSubmit={(event) => void login(event)} className="mt-6 space-y-4">
          <label htmlFor="admin-credential" className="block text-sm text-ink">管理员凭据</label>
          <input id="admin-credential" type="password" autoComplete="off" required disabled={busy}
            value={token} onChange={(event) => setToken(event.target.value)}
            className="w-full border border-border bg-panel p-3 text-ink" />
          {message && <p role="alert" className="text-sm text-bad">{message}</p>}
          <button type="submit" disabled={busy}
            className="border border-border px-4 py-2 text-sm text-ink disabled:opacity-50">
            {busy ? "正在验证…" : "登录"}
          </button>
        </form>
      </section>
    );
  }

  return (
    <SWRConfig value={{
      // A separate cache is discarded on logout, including privileged data.
      provider: () => new Map(),
      shouldRetryOnError: false,
      onError: (error: unknown) => {
        if (error instanceof HttpError && (error.status === 401 || error.status === 403)) {
          logout("管理登录已失效，请重新登录。");
        }
      },
    }}>
      <div className="mx-auto flex max-w-screen-xl justify-end px-6 pt-4">
        <button type="button" onClick={() => logout()}
          className="border border-border px-3 py-1 text-sm text-muted hover:text-ink">退出登录</button>
      </div>
      {children}
    </SWRConfig>
  );
}
