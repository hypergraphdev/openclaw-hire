import { FormEvent, useMemo, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import type { AppShellContext } from "../App";
import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import { StatusPill } from "../components/StatusPill";
import { formatStateLabel } from "../lib/formatters";
import type { Employee } from "../types";

const roleTemplates = [
  {
    value: "Personal Research Analyst",
    description: "Tracks ideas, summarizes sources, and keeps long-running notes organized.",
  },
  {
    value: "Inbox & Scheduling Assistant",
    description: "Drafts replies, triages requests, and prepares a daily operating queue.",
  },
  {
    value: "Builder / Coding Partner",
    description: "Helps ship side projects, debug issues, and maintain task momentum.",
  },
  {
    value: "Life Ops Coordinator",
    description: "Keeps travel, errands, reminders, and household tasks aligned.",
  },
];

const provisioningSteps = [
  "Queue request",
  "Prepare workspace",
  "Write config",
  "Create service",
  "Wait for Telegram token",
  "Ready for use",
];

export function HireEmployeePage() {
  const { owner, refreshEmployees } = useOutletContext<AppShellContext>();
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const defaultTemplate = roleTemplates[0]?.value ?? "";
  const latestState = useMemo(() => employee?.current_state ?? "queued", [employee]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!owner) {
      setError("Create your personal account before provisioning an agent.");
      return;
    }

    const formData = new FormData(event.currentTarget);
    setIsSaving(true);

    try {
      const createdEmployee = await api.createEmployee({
        owner_id: owner.id,
        name: String(formData.get("name") ?? "").trim(),
        role: String(formData.get("role") ?? "").trim(),
        brief: String(formData.get("brief") ?? "").trim(),
        telegram_handle: String(formData.get("telegram_handle") ?? "").trim(),
      });
      setEmployee(createdEmployee);
      await refreshEmployees();
      event.currentTarget.reset();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Provisioning failed.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8 2xl:grid-cols-[minmax(0,1.3fr)_380px]">
      <SectionCard
        title="Provision a new personal agent"
        subtitle="The hiring flow now behaves like a resource creation wizard. Choose a template, name the instance, and review the runtime defaults before the backend starts provisioning."
        aside={<span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-100">Provisioning</span>}
      >
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <form className="grid gap-5" onSubmit={onSubmit}>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm text-slate-300">
                Agent template
                <select
                  className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                  defaultValue={defaultTemplate}
                  name="role"
                  required
                >
                  {roleTemplates.map((template) => (
                    <option key={template.value} value={template.value}>
                      {template.value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm text-slate-300">
                Agent name
                <input
                  className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                  name="name"
                  placeholder="Scout"
                  required
                />
              </label>
            </div>

            <label className="grid gap-2 text-sm text-slate-300">
              Personal mission brief
              <textarea
                className="min-h-32 rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="brief"
                placeholder="Help me monitor side-project priorities, summarize notes, and prep a daily plan."
              />
            </label>

            <label className="grid gap-2 text-sm text-slate-300">
              Telegram handle
              <input
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                name="telegram_handle"
                placeholder="@alexrivera"
              />
            </label>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Runtime defaults</p>
                <p className="mt-3 text-lg font-semibold text-white">openai-codex/gpt-5.3-codex-spark</p>
                <p className="mt-2 text-sm text-slate-400">This is the backend-provided default model config currently applied to new agents.</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Owner binding</p>
                <p className="mt-3 text-lg font-semibold text-white">{owner ? owner.name : "No account connected"}</p>
                <p className="mt-2 text-sm text-slate-400">
                  {owner ? owner.email : "Go back to Account and create your personal login first."}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[24px] border border-white/10 bg-slate-950/50 p-4">
              <div>
                <p className="text-sm font-semibold text-white">Launch provisioning workflow</p>
                <p className="mt-1 text-xs text-slate-400">The request creates the employee record, then the backend advances through its lifecycle states.</p>
              </div>
              <button
                className="rounded-full bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-70"
                disabled={isSaving}
                type="submit"
              >
                {isSaving ? "Provisioning..." : "Create agent instance"}
              </button>
            </div>
            {error ? <p className="text-sm text-rose-300">{error}</p> : null}
          </form>

          <div className="grid gap-4">
            <div className="rounded-[24px] border border-white/10 bg-slate-950/50 p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Current request</p>
                  <p className="mt-2 text-lg font-semibold text-white">{employee ? employee.name : "No agent provisioned yet"}</p>
                </div>
                <StatusPill state={latestState} />
              </div>
              <p className="mt-3 text-sm text-slate-400">
                {employee ? employee.role : "Submit the form to create a personal agent resource and populate this panel."}
              </p>
              {employee ? (
                <Link className="mt-4 inline-flex text-sm font-medium text-cyan-300 hover:text-cyan-200" to={`/employees/${employee.id}`}>
                  Open resource page
                </Link>
              ) : null}
            </div>

            <div className="rounded-[24px] border border-white/10 bg-slate-950/50 p-5">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Provisioning steps</p>
              <div className="mt-4 grid gap-3">
                {provisioningSteps.map((step, index) => {
                  const isActive = employee ? index <= 3 : index === 0;
                  return (
                    <div
                      key={step}
                      className={`rounded-2xl border px-4 py-3 text-sm ${
                        isActive ? "border-cyan-400/25 bg-cyan-400/10 text-cyan-50" : "border-white/10 bg-white/5 text-slate-400"
                      }`}
                    >
                      <p className="font-medium">{step}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="rounded-[24px] border border-amber-400/20 bg-amber-400/10 p-5">
              <p className="text-sm font-semibold text-amber-100">Lifecycle note</p>
              <p className="mt-2 text-sm text-amber-50/80">
                Agents move into <span className="font-medium">{formatStateLabel("waiting_bot_token")}</span> until you complete the Telegram token placeholder step on the detail page.
              </p>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
