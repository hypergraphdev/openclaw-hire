import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { AppShellContext } from "../App";
import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import { useOutletContext } from "react-router-dom";

export function SettingsPage() {
  const navigate = useNavigate();
  const { owner, setOwner } = useOutletContext<AppShellContext>();
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSaving(true);
    const formData = new FormData(event.currentTarget);

    try {
      const createdUser = await api.registerUser({
        name: String(formData.get("name") ?? "").trim(),
        email: String(formData.get("email") ?? "").trim(),
        company_name: String(formData.get("workspace_label") ?? "").trim() || undefined,
      });
      setOwner(createdUser);
      navigate("/dashboard");
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Account setup failed.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Settings / Profile"
        subtitle="个人账户是雇佣流程的入口。创建账户后可发起多人雇佣，并持续追踪每个 AI Agent 的初始化状态。"
      >
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <form className="grid gap-4 rounded-[24px] border border-white/10 bg-slate-950/45 p-5" onSubmit={onSubmit}>
            <label className="grid gap-2 text-sm text-slate-300">
              你的昵称
              <input
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="name"
                required
                placeholder="Alex"
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-300">
              邮箱
              <input
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                type="email"
                name="email"
                required
                placeholder="alex@example.com"
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-300">
              工作区名称（可选）
              <input
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="workspace_label"
                placeholder="OpenClaw Personal Hub"
              />
            </label>
            <button
              className="rounded-full bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-70"
              disabled={isSaving}
              type="submit"
            >
              {isSaving ? "保存并进入" : "创建 / 更新账户"}
            </button>
            {error ? <p className="text-sm text-rose-300">{error}</p> : null}
          </form>

          <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-slate-500">当前会话</p>
            {owner ? (
              <div className="mt-4 grid gap-3 text-sm text-slate-300">
                <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-4">
                  <p className="font-medium text-white">{owner.name}</p>
                  <p className="mt-1 text-slate-400">{owner.email}</p>
                  <p className="mt-3 text-xs text-slate-500">{owner.id}</p>
                </div>
                <button
                  className="rounded-xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100 transition hover:bg-rose-400/20"
                  onClick={() => setOwner(null)}
                  type="button"
                >
                  退出账户（本地清除）
                </button>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-white/10 bg-slate-950/45 p-5 text-sm text-slate-400">
                暂未绑定账户，先创建账户，再去「Create Agent」。
              </div>
            )}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
