import { FormEvent, useEffect, useState } from "react";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import type { Employee, User } from "../types";

export function HireEmployeePage() {
  const [owner, setOwner] = useState<User | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const storedOwner = localStorage.getItem("openclaw_owner");
    if (storedOwner) {
      setOwner(JSON.parse(storedOwner) as User);
    }
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!owner) {
      setError("Register an owner account first.");
      return;
    }
    const formData = new FormData(event.currentTarget);
    try {
      const createdEmployee = await api.createEmployee({
        owner_id: owner.id,
        name: String(formData.get("name") ?? ""),
        role: String(formData.get("role") ?? ""),
        brief: String(formData.get("brief") ?? ""),
        telegram_handle: String(formData.get("telegram_handle") ?? ""),
      });
      setEmployee(createdEmployee);
      event.currentTarget.reset();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Employee creation failed.");
    }
  }

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Hire employee"
        subtitle="Creates the employee record and pushes initialization to the monitored waiting state."
        aside={<span className="rounded-full bg-ember/10 px-3 py-1 text-xs font-semibold text-ember">Step 2</span>}
      >
        <div className="mb-4 rounded-2xl bg-sand p-4 text-sm text-ink/80">
          Owner: {owner ? `${owner.name} (${owner.id})` : "not registered locally yet"}
        </div>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={onSubmit}>
          <label className="grid gap-2 text-sm">
            Employee name
            <input className="rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none" name="name" required />
          </label>
          <label className="grid gap-2 text-sm">
            Role
            <input className="rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none" name="role" required />
          </label>
          <label className="grid gap-2 text-sm md:col-span-2">
            Brief
            <textarea className="min-h-28 rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none" name="brief" />
          </label>
          <label className="grid gap-2 text-sm md:col-span-2">
            Telegram handle
            <input className="rounded-2xl border border-ink/10 bg-sand px-4 py-3 outline-none" name="telegram_handle" />
          </label>
          <button className="rounded-full bg-ink px-5 py-3 text-sm font-semibold text-sand" type="submit">
            Create employee job
          </button>
        </form>
        {error ? <p className="mt-4 text-sm text-ember">{error}</p> : null}
      </SectionCard>

      <SectionCard title="Most recent employee" subtitle="The generated employee starts with the default model config.">
        {employee ? (
          <div className="grid gap-2 text-sm">
            <p>
              <strong>ID:</strong> {employee.id}
            </p>
            <p>
              <strong>State:</strong> {employee.current_state}
            </p>
            <p>
              <strong>Model:</strong> {employee.model_config}
            </p>
          </div>
        ) : (
          <p className="text-sm text-ink/70">No employee created in this session yet.</p>
        )}
      </SectionCard>
    </div>
  );
}
