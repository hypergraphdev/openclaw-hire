import { FormEvent, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import { StatusPill } from "../components/StatusPill";
import type { AppShellContext } from "../App";
import type { Employee, TemplateConfig } from "../types";

export function CreateAgentPage() {
  const { owner, refreshEmployees } = useOutletContext<AppShellContext>();
  const [templates, setTemplates] = useState<TemplateConfig[]>([]);
  const [agent, setAgent] = useState<Employee | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    api
      .listTemplates()
      .then(setTemplates)
      .catch(() => {
        setTemplates([]);
      });
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!owner) {
      setError("请先在 Settings 注册账户。");
      return;
    }

    const formData = new FormData(event.currentTarget);
    setIsLoading(true);

    try {
      const templateId = String(formData.get("template_id") ?? "audit-codex-base");
      const stack = String(formData.get("stack") ?? "openclaw") === "zylos" ? "zylos" : "openclaw";
      const next = await api.createEmployee({
        owner_id: owner.id,
        name: String(formData.get("name") ?? "").trim(),
        role: String(formData.get("role") ?? "").trim(),
        template_id: templateId,
        stack,
        brief: String(formData.get("brief") ?? "").trim(),
        telegram_handle: String(formData.get("telegram_handle") ?? "").trim(),
      });
      setAgent(next);
      await refreshEmployees();
      event.currentTarget.reset();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Provision failed.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Create Agent"
        subtitle="多人雇佣、模板复用。默认会复制 audit 的 Codex 配置作为运行基线，并进入后台异步初始化流程。"
      >
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_360px]">
          <form className="grid gap-4" onSubmit={onSubmit}>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm text-slate-300">
                Agent 名称
                <input
                  className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                  name="name"
                  required
                  placeholder="Scout"
                />
              </label>
              <label className="grid gap-2 text-sm text-slate-300">
                角色目标
                <input
                  className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                  name="role"
                  required
                  placeholder="Research & Coordination"
                />
              </label>
            </div>

            <label className="grid gap-2 text-sm text-slate-300">
              选择模板
              <select
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="template_id"
                defaultValue={templates[0]?.id ?? "audit-codex-base"}
                required
              >
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="grid gap-2 text-sm text-slate-300">
              安装栈
              <select
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="stack"
                defaultValue="openclaw"
                required
              >
                <option value="openclaw">OpenClaw · github.com/openclaw/openclaw（Docker）</option>
                <option value="zylos">Zylos · github.com/zylos-ai/zylos-core（Docker）</option>
              </select>
            </label>

            <label className="grid gap-2 text-sm text-slate-300">
              任务描述
              <textarea
                className="min-h-28 rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="brief"
                placeholder="负责监控指标、总结进度并生成日报。"
              />
            </label>

            <label className="grid gap-2 text-sm text-slate-300">
              Telegram 预留 handle
              <input
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="telegram_handle"
                placeholder="@agent_owner"
              />
            </label>

            <button
              className="rounded-full bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-70"
              disabled={isLoading}
              type="submit"
            >
              {isLoading ? "正在创建..." : "发起雇佣/初始化"}
            </button>
            {error ? <p className="text-sm text-rose-300">{error}</p> : null}
          </form>

          <div className="grid gap-4">
            <div className="rounded-[24px] border border-white/10 bg-slate-950/45 p-5">
              <p className="text-xs uppercase tracking-[0.28em] text-slate-500">当前提交</p>
              <p className="mt-3 text-lg font-semibold text-white">{agent?.name || "未提交"}</p>
              <p className="mt-2 text-sm text-slate-400">
                {agent ? `模板: ${agent.template_id} · 安装栈: ${agent.stack}` : "填写信息后提交"}
              </p>
              {agent ? <StatusPill state={agent.current_state} /> : null}
            </div>

            {agent ? (
              <Link
                className="rounded-[24px] border border-cyan-400/30 bg-cyan-400/10 p-4 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-400/20"
                to={`/agents/${agent.id}`}
              >
                查看该 Agent 详情
              </Link>
            ) : null}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
