import { FormEvent, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { AppShellContext } from "../App";
import { api } from "../api";
import { SectionCard } from "../components/SectionCard";

export function RegisterPage() {
  const { owner, setOwner } = useOutletContext<AppShellContext>();
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSaving(true);
    const formData = new FormData(event.currentTarget);

    try {
      const name = String(formData.get("name") ?? "").trim();
      const email = String(formData.get("email") ?? "").trim();
      const workspaceLabel = String(formData.get("workspace_label") ?? "").trim();
      const createdUser = await api.registerUser({
        name,
        email,
        company_name: workspaceLabel || undefined,
      });
      setOwner(createdUser);
      event.currentTarget.reset();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Account setup failed.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8 xl:grid-cols-[minmax(0,1.15fr)_400px]">
      <SectionCard
        title="Create your personal OpenClaw console"
        subtitle="This landing page behaves like a cloud sign-in screen: connect your personal account first, then provision agents into your own workspace."
        aside={<span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-100">Access</span>}
      >
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="grid gap-5">
            <div className="rounded-[26px] border border-white/10 bg-white/5 p-5">
              <p className="text-xs uppercase tracking-[0.28em] text-slate-500">Personal workflow</p>
              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <p className="text-sm font-semibold text-white">1. Create account</p>
                  <p className="mt-2 text-sm text-slate-400">Use your own name and email. No company profile is required.</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <p className="text-sm font-semibold text-white">2. Provision agent</p>
                  <p className="mt-2 text-sm text-slate-400">Choose a template, name the agent, and review the runtime defaults.</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <p className="text-sm font-semibold text-white">3. Monitor status</p>
                  <p className="mt-2 text-sm text-slate-400">Track setup events and complete Telegram handoff when requested.</p>
                </div>
              </div>
            </div>

            <form className="grid gap-4 rounded-[26px] border border-white/10 bg-slate-950/40 p-5" onSubmit={onSubmit}>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm text-slate-300">
                  Full name
                  <input
                    className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                    name="name"
                    placeholder="Alex Rivera"
                    required
                  />
                </label>
                <label className="grid gap-2 text-sm text-slate-300">
                  Email address
                  <input
                    className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                    name="email"
                    placeholder="alex@example.com"
                    type="email"
                    required
                  />
                </label>
              </div>

              <label className="grid gap-2 text-sm text-slate-300">
                Workspace label
                <input
                  className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-cyan-400/50"
                  name="workspace_label"
                  placeholder="Personal AI desk"
                />
              </label>

              <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-white">Local session persistence</p>
                  <p className="mt-1 text-xs text-slate-400">The current frontend stores your latest account locally for fast access between pages.</p>
                </div>
                <button
                  className="rounded-full bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-70"
                  disabled={isSaving}
                  type="submit"
                >
                  {isSaving ? "Creating account..." : "Enter console"}
                </button>
              </div>
              {error ? <p className="text-sm text-rose-300">{error}</p> : null}
            </form>
          </div>

          <div className="rounded-[26px] border border-white/10 bg-gradient-to-b from-slate-900 to-slate-950 p-5">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Current session</p>
            {owner ? (
              <div className="mt-4 grid gap-4">
                <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 p-4">
                  <p className="text-sm font-semibold text-emerald-100">Console connected</p>
                  <p className="mt-2 text-lg font-semibold text-white">{owner.name}</p>
                  <p className="mt-1 text-sm text-slate-300">{owner.email}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-300">
                  <p className="font-medium text-white">Owner ID</p>
                  <p className="mt-2 break-all text-xs text-slate-400">{owner.id}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-300">
                  <p className="font-medium text-white">Next recommended action</p>
                  <p className="mt-2 text-slate-400">Move to Provision Agent and create your first personal teammate.</p>
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-white/10 bg-white/5 p-5 text-sm text-slate-400">
                No personal account is stored yet. Create one to unlock provisioning and fleet management.
              </div>
            )}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
