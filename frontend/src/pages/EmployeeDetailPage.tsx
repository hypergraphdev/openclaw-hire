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

export function EmployeeDetailPage() {
  const { employeeId = "" } = useParams();
  const [detail, setDetail] = useState<EmployeeDetail | null>(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!employeeId) {
      return;
    }
    api.getEmployeeStatus(employeeId).then(setDetail).catch((requestError) => {
      setError(requestError instanceof Error ? requestError.message : "Could not load resource detail.");
    });
  }, [employeeId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    const formData = new FormData(event.currentTarget);

    try {
      const nextDetail = await api.saveBotToken(employeeId, String(formData.get("telegram_bot_token_placeholder") ?? "").trim());
      setDetail(nextDetail);
      setError("");
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
        title={detail ? detail.employee.name : "Agent resource"}
        subtitle="Resource-level view of one personal hire, including lifecycle events, model runtime, and Telegram completion steps."
        aside={detail ? <StatusPill state={detail.employee.current_state} /> : null}
      >
        {detail ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_360px]">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Template</p>
                <p className="mt-3 text-lg font-semibold text-white">{detail.employee.role}</p>
                <p className="mt-2 text-sm text-slate-400">{detail.employee.brief || "No personal mission brief supplied."}</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Runtime</p>
                <p className="mt-3 text-lg font-semibold text-white">{detail.employee.model_config}</p>
                <p className="mt-2 text-sm text-slate-400">Current backend default assigned at create time.</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Telegram</p>
                <p className="mt-3 text-lg font-semibold text-white">{detail.employee.telegram_handle || "Not provided"}</p>
                <p className="mt-2 text-sm text-slate-400">Bot token handoff is tracked separately below.</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Resource metadata</p>
                <p className="mt-3 text-sm text-slate-300">Created {formatDateTime(detail.employee.created_at)}</p>
                <p className="mt-2 break-all text-xs text-slate-500">{detail.employee.id}</p>
              </div>
            </div>

            <div className="grid gap-4">
              <div className="rounded-[24px] border border-white/10 bg-slate-950/50 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Lifecycle checkpoint</p>
                <p className="mt-3 text-lg font-semibold text-white">{formatStateLabel(detail.employee.current_state)}</p>
                <p className="mt-2 text-sm text-slate-400">
                  {detail.employee.current_state === "waiting_bot_token"
                    ? "Action required: add the Telegram token placeholder to finish the current scaffold."
                    : "No manual action is currently required unless the backend reports otherwise."}
                </p>
              </div>
              <Link className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4 text-sm font-medium text-cyan-300 transition hover:bg-white/10 hover:text-cyan-200" to="/employees">
                Back to fleet overview
              </Link>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-400">Loading resource detail...</p>
        )}
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_380px]">
        <SectionCard title="Provisioning timeline" subtitle="State-by-state lifecycle log for this agent resource.">
          <div className="grid gap-3">
            {stateOrder.map((state) => {
              const event = detail?.timeline.find((entry) => entry.state === state);
              const isCurrent = detail?.employee.current_state === state;
              return (
                <div
                  key={state}
                  className={`rounded-[24px] border px-4 py-4 ${
                    event
                      ? "border-cyan-400/20 bg-cyan-400/10"
                      : "border-white/10 bg-white/5"
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

        <SectionCard title="Telegram completion" subtitle="Submit the placeholder token when the resource enters the waiting state.">
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
              Save this only when the resource is waiting for Telegram token input. The backend should then advance the resource state.
            </div>
            <button
              className="rounded-full bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-70"
              disabled={isSaving}
              type="submit"
            >
              {isSaving ? "Saving..." : "Submit placeholder"}
            </button>
          </form>
          {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
        </SectionCard>
      </div>
    </div>
  );
}
