import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import { StatusPill } from "../components/StatusPill";
import { formatDateTime, formatStateLabel } from "../lib/formatters";
import type { EmployeeDetail } from "../types";

const stateOrder = [
  "queued",
  "preparing_workspace",
  "writing_config",
  "creating_service",
  "waiting_bot_token",
  "ready",
  "failed",
];

export function AgentDetailPage() {
  const { employeeId = "" } = useParams();
  const [detail, setDetail] = useState<EmployeeDetail | null>(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!employeeId) {
      return;
    }

    let alive = true;
    const loadDetail = () => {
      api.getEmployeeStatus(employeeId).then((next) => {
        if (!alive) {
          return;
        }
        setDetail(next);
      });
    };

    loadDetail();
    const timer = window.setInterval(loadDetail, 8000);

    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [employeeId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!employeeId) {
      return;
    }
    setIsSaving(true);
    setError("");

    const formData = new FormData(event.currentTarget);

    try {
      const nextDetail = await api.saveBotToken(employeeId, String(formData.get("telegram_bot_token_placeholder") ?? "").trim());
      setDetail(nextDetail);
      event.currentTarget.reset();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Could not save token placeholder.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title={detail ? detail.employee.name : "Agent Resource"}
        subtitle="运行中的 Agent 详情页：可查看状态时间线，并在 Token 阶段提交 Telegram Bot Token。"
        aside={detail ? <StatusPill state={detail.employee.current_state} /> : null}
      >
        {detail ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_360px]">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">模板</p>
                <p className="mt-3 text-lg font-semibold text-white">{detail.employee.role}</p>
                <p className="mt-2 text-sm text-slate-400">Template ID: {detail.employee.template_id}</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">运行时</p>
                <p className="mt-3 text-lg font-semibold text-white">{detail.employee.model_config}</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Telegram</p>
                <p className="mt-3 text-lg font-semibold text-white">{detail.employee.telegram_handle || "未提供"}</p>
                <p className="mt-2 text-sm text-slate-400">占位 token: {detail.employee.telegram_bot_token_placeholder ?? "未提交"}</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">资源元数据</p>
                <p className="mt-3 text-sm text-slate-300">创建于 {formatDateTime(detail.employee.created_at)}</p>
                <p className="mt-2 break-all text-xs text-slate-500">{detail.employee.id}</p>
              </div>
            </div>

            <div className="grid gap-4">
              <div className="rounded-[24px] border border-white/10 bg-slate-950/50 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">生命周期</p>
                <p className="mt-3 text-lg font-semibold text-white">{formatStateLabel(detail.employee.current_state)}</p>
                <p className="mt-2 text-sm text-slate-400">
                  {detail.employee.current_state === "waiting_bot_token"
                    ? "当前等待你提交 Telegram Bot Token placeholder。"
                    : "如需人工介入，仅在 waiting_bot_token 阶段提交 token。"}
                </p>
              </div>

              <Link
                className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4 text-sm font-medium text-cyan-300 transition hover:bg-white/10 hover:text-cyan-200"
                to="/agents"
              >
                回到 Fleet
              </Link>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-400">加载 Agent 详情中...</p>
        )}
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_380px]">
        <SectionCard title="Provisioning timeline" subtitle="后台脚本状态上报">
          <div className="grid gap-3">
            {stateOrder.map((state) => {
              const event = detail?.timeline.find((entry) => entry.state === state);
              const isCurrent = detail?.employee.current_state === state;
              return (
                <div
                  key={state}
                  className={`rounded-[24px] border px-4 py-4 ${
                    event ? "border-cyan-400/20 bg-cyan-400/10" : "border-white/10 bg-white/5"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-white">{formatStateLabel(state)}</p>
                    {isCurrent ? <StatusPill state={state} /> : null}
                  </div>
                  <p className="mt-2 text-sm text-slate-300">{event ? event.message : "Not reached yet."}</p>
                  {event ? <p className="mt-2 text-xs uppercase tracking-[0.2em] text-slate-500">{formatDateTime(event.created_at)}</p> : null}
                </div>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard title="Telegram completion" subtitle="填写 Telegram Bot Token 占位后，系统会继续初始化并进入 ready。">
          <form className="grid gap-4" onSubmit={onSubmit}>
            <label className="grid gap-2 text-sm text-slate-300">
              Telegram bot token placeholder
              <input
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="telegram_bot_token_placeholder"
                placeholder="tg-placeholder-123456"
                required
              />
            </label>
            <div className="rounded-[24px] border border-amber-400/20 bg-amber-400/10 p-4 text-sm text-amber-50/90">
              若该 Agent 当前状态为 waiting_bot_token，可提交 token 占位（首位聊天人必须是 Owner）。
            </div>
            <button
              className="rounded-full bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-70"
              disabled={isSaving}
              type="submit"
            >
              {isSaving ? "Saving..." : "提交 Token placeholder"}
            </button>
          </form>
          {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
        </SectionCard>
      </div>
    </div>
  );
}
