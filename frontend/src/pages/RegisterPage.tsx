import { FormEvent, useEffect, useState } from "react";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import type { User } from "../types";

export function RegisterPage() {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    const storedUser = localStorage.getItem("openclaw_owner");
    if (storedUser) {
      setUser(JSON.parse(storedUser) as User);
    }
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSaving(true);
    const formData = new FormData(event.currentTarget);
    try {
      const createdUser = await api.registerUser({
        name: String(formData.get("name") ?? ""),
        email: String(formData.get("email") ?? ""),
        company_name: String(formData.get("company_name") ?? ""),
      });
      setUser(createdUser);
      localStorage.setItem("openclaw_owner", JSON.stringify(createdUser));
      event.currentTarget.reset();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Registration failed.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Registration"
        subtitle="Create the owner account that will hold hired OpenClaw employees."
        aside={<span className="rounded-full bg-sea/10 px-3 py-1 text-xs font-semibold text-sea">Step 1</span>}
      >
        <form className="grid gap-4 md:grid-cols-2" onSubmit={onSubmit}>
          <label className="grid gap-2 text-sm">
            Name
            <input className="rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none" name="name" required />
          </label>
          <label className="grid gap-2 text-sm">
            Email
            <input className="rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none" name="email" type="email" required />
          </label>
          <label className="grid gap-2 text-sm md:col-span-2">
            Company
            <input className="rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none" name="company_name" />
          </label>
          <button className="rounded-full bg-ink px-5 py-3 text-sm font-semibold text-sand" disabled={isSaving} type="submit">
            {isSaving ? "Registering..." : "Create owner"}
          </button>
        </form>
        {error ? <p className="mt-4 text-sm text-ember">{error}</p> : null}
      </SectionCard>

      <SectionCard
        title="Current owner"
        subtitle="The frontend stores the most recent registered owner in local storage for quick testing."
      >
        {user ? (
          <div className="grid gap-2 text-sm">
            <p>
              <strong>ID:</strong> {user.id}
            </p>
            <p>
              <strong>Name:</strong> {user.name}
            </p>
            <p>
              <strong>Email:</strong> {user.email}
            </p>
          </div>
        ) : (
          <p className="text-sm text-ink/70">No owner stored yet. Register one to unlock employee actions.</p>
        )}
      </SectionCard>
    </div>
  );
}
