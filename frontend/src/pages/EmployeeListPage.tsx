import { Link, useOutletContext } from "react-router-dom";

import type { AppShellContext } from "../App";
import { SectionCard } from "../components/SectionCard";
import { StatusPill } from "../components/StatusPill";
import { formatDateTime } from "../lib/formatters";

export function EmployeeListPage() {
  const { employees, owner } = useOutletContext<AppShellContext>();

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Agent fleet"
        subtitle="Each hire is presented like a managed cloud resource with lifecycle state, model runtime, and owner assignment visible at a glance."
        aside={<span className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-100">Fleet</span>}
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="overflow-hidden rounded-[24px] border border-white/10">
            <div className="hidden grid-cols-[1.4fr_1fr_1fr_1fr] gap-4 border-b border-white/10 bg-white/5 px-5 py-4 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 md:grid">
              <p>Resource</p>
              <p>Status</p>
              <p>Runtime</p>
              <p>Updated</p>
            </div>
            <div className="grid">
              {employees.length > 0 ? (
                employees.map((employee) => (
                  <Link
                    key={employee.id}
                    className="grid gap-4 border-b border-white/10 bg-slate-950/30 px-5 py-4 transition hover:bg-white/5 md:grid-cols-[1.4fr_1fr_1fr_1fr]"
                    to={`/employees/${employee.id}`}
                  >
                    <div>
                      <p className="text-base font-semibold text-white">{employee.name}</p>
                      <p className="mt-1 text-sm text-slate-400">{employee.role}</p>
                      <p className="mt-2 text-xs text-slate-500">{employee.id}</p>
                    </div>
                    <div className="flex items-start md:items-center">
                      <StatusPill state={employee.current_state} />
                    </div>
                    <div className="text-sm text-slate-300">
                      <p>{employee.model_config}</p>
                      <p className="mt-1 text-xs text-slate-500">{employee.telegram_handle || "No Telegram handle supplied"}</p>
                    </div>
                    <div className="text-sm text-slate-400">{formatDateTime(employee.updated_at)}</div>
                  </Link>
                ))
              ) : (
                <div className="px-5 py-10 text-sm text-slate-400">
                  No agents exist for this account yet. Create your first personal agent from the provisioning page.
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-4">
            <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Account scope</p>
              <p className="mt-3 text-lg font-semibold text-white">{owner ? owner.name : "No account connected"}</p>
              <p className="mt-1 text-sm text-slate-400">{owner ? owner.email : "Return to Account to create your session."}</p>
            </div>

            <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Fleet health</p>
              <div className="mt-4 grid gap-3">
                <div className="rounded-2xl border border-white/10 bg-slate-950/50 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Ready</p>
                  <p className="mt-2 text-2xl font-semibold text-emerald-300">
                    {employees.filter((employee) => employee.current_state === "ready").length}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-slate-950/50 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Waiting token</p>
                  <p className="mt-2 text-2xl font-semibold text-amber-200">
                    {employees.filter((employee) => employee.current_state === "waiting_bot_token").length}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-slate-950/50 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Provisioning</p>
                  <p className="mt-2 text-2xl font-semibold text-cyan-200">
                    {
                      employees.filter((employee) => !["ready", "failed", "waiting_bot_token"].includes(employee.current_state))
                        .length
                    }
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
