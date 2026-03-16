import type { PropsWithChildren } from "react";

import type { Employee, User } from "../types";
import { NavBar } from "./NavBar";
import { StatusPill } from "./StatusPill";

type Props = PropsWithChildren<{
  employees: Employee[];
  owner: User | null;
}>;

function metricValue(value: number) {
  return value.toString().padStart(2, "0");
}

export function PhoneFrame({ children, employees, owner }: Props) {
  const readyCount = employees.filter((employee) => employee.current_state === "ready").length;
  const actionRequiredCount = employees.filter((employee) => employee.current_state === "waiting_bot_token").length;
  const provisioningCount = employees.filter((employee) => !["ready", "failed"].includes(employee.current_state)).length;
  const newestEmployee = employees[0] ?? null;

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-4 text-slate-100 md:px-6 md:py-6">
      <div className="mx-auto grid min-h-[calc(100vh-2rem)] max-w-7xl gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="flex flex-col rounded-[30px] border border-white/10 bg-slate-900/85 p-6 shadow-2xl shadow-black/30 backdrop-blur">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-300/80">OpenClaw Hire</p>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-white">Personal AI agent control plane</h1>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Launch and monitor specialist agents the same way you would provision cloud resources.
            </p>
          </div>

          <div className="mt-8 rounded-[24px] border border-cyan-400/20 bg-cyan-400/10 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-cyan-200/70">Default runtime</p>
            <p className="mt-2 text-sm font-medium text-cyan-50">openai-codex/gpt-5.3-codex-spark</p>
            <p className="mt-2 text-xs text-cyan-100/70">Provisioned automatically for every new agent unless the backend default changes.</p>
          </div>

          <div className="mt-8">
            <NavBar />
          </div>

          <div className="mt-8 rounded-[24px] border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Personal account</p>
                <p className="mt-2 text-sm font-semibold text-white">{owner ? owner.name : "No account connected"}</p>
              </div>
              {owner ? <StatusPill state="ready" /> : <StatusPill state="queued" />}
            </div>
            <p className="mt-2 text-xs text-slate-400">{owner ? owner.email : "Create your account to unlock provisioning."}</p>
          </div>

          <div className="mt-auto grid gap-3 pt-8">
            <div className="rounded-[22px] border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Latest agent</p>
              <p className="mt-2 text-sm font-semibold text-white">{newestEmployee ? newestEmployee.name : "None yet"}</p>
              <p className="mt-1 text-xs text-slate-400">{newestEmployee ? newestEmployee.role : "Provision your first personal assistant."}</p>
            </div>
          </div>
        </aside>

        <main className="overflow-hidden rounded-[30px] border border-white/10 bg-slate-900/60 shadow-2xl shadow-black/20 backdrop-blur">
          <div className="border-b border-white/10 px-6 py-5 md:px-8">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Workspace summary</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">Personal fleet overview</h2>
                <p className="mt-2 text-sm text-slate-400">Track active hires, provisioning steps, and setup actions from one console.</p>
              </div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Account</p>
                  <p className="mt-2 text-2xl font-semibold text-white">{owner ? "01" : "00"}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Agents</p>
                  <p className="mt-2 text-2xl font-semibold text-white">{metricValue(employees.length)}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Ready</p>
                  <p className="mt-2 text-2xl font-semibold text-emerald-300">{metricValue(readyCount)}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Action needed</p>
                  <p className="mt-2 text-2xl font-semibold text-amber-200">{metricValue(actionRequiredCount + provisioningCount)}</p>
                </div>
              </div>
            </div>
          </div>
          <div className="h-full bg-[radial-gradient(circle_at_top,rgba(56,189,248,0.10),transparent_24%),linear-gradient(180deg,rgba(15,23,42,0.35),rgba(15,23,42,0.2))]">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
