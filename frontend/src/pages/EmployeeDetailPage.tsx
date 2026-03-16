import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
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

  useEffect(() => {
    if (!employeeId) {
      return;
    }
    api.getEmployeeStatus(employeeId).then(setDetail).catch((requestError) => {
      setError(requestError instanceof Error ? requestError.message : "Could not load status.");
    });
  }, [employeeId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      const nextDetail = await api.saveBotToken(employeeId, String(formData.get("telegram_bot_token_placeholder") ?? ""));
      setDetail(nextDetail);
      setError("");
      event.currentTarget.reset();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Could not save token placeholder.");
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard title="Employee detail" subtitle="Initialization timeline and final token placeholder handoff.">
        {detail ? (
          <div className="grid gap-3 text-sm">
            <p>
              <strong>Name:</strong> {detail.employee.name}
            </p>
            <p>
              <strong>Role:</strong> {detail.employee.role}
            </p>
            <p>
              <strong>Current state:</strong> {detail.employee.current_state}
            </p>
            <p>
              <strong>Model:</strong> {detail.employee.model_config}
            </p>
          </div>
        ) : (
          <p className="text-sm text-ink/70">Loading employee state...</p>
        )}
      </SectionCard>

      <SectionCard title="Init status timeline" subtitle="Monitored states from queue to ready.">
        <div className="grid gap-3">
          {stateOrder.map((state) => {
            const event = detail?.timeline.find((entry) => entry.state === state);
            return (
              <div key={state} className={`rounded-[22px] border px-4 py-3 ${event ? "border-sea bg-sea/5" : "border-ink/10 bg-sand"}`}>
                <p className="font-semibold text-ink">{state}</p>
                <p className="mt-1 text-sm text-ink/70">{event ? event.message : "Not reached yet."}</p>
                {event ? <p className="mt-2 text-xs uppercase tracking-[0.2em] text-ink/45">{event.created_at}</p> : null}
              </div>
            );
          })}
        </div>
      </SectionCard>

      <SectionCard title="Telegram token placeholder" subtitle="Completes the current scaffold and moves state to ready.">
        <form className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto]" onSubmit={onSubmit}>
          <input
            className="rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none"
            name="telegram_bot_token_placeholder"
            placeholder="tg-placeholder-123456"
            required
          />
          <button className="rounded-full bg-ember px-5 py-3 text-sm font-semibold text-white" type="submit">
            Save placeholder
          </button>
        </form>
        {error ? <p className="mt-4 text-sm text-ember">{error}</p> : null}
      </SectionCard>
    </div>
  );
}
