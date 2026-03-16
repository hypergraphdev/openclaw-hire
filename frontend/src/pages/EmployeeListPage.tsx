import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import type { Employee, User } from "../types";

export function EmployeeListPage() {
  const [owner, setOwner] = useState<User | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const storedOwner = localStorage.getItem("openclaw_owner");
    if (!storedOwner) {
      return;
    }
    const parsedOwner = JSON.parse(storedOwner) as User;
    setOwner(parsedOwner);
    api.listEmployees(parsedOwner.id).then(setEmployees).catch((requestError) => {
      setError(requestError instanceof Error ? requestError.message : "Could not load employees.");
    });
  }, []);

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Employee list"
        subtitle="Lists every employee job under the current owner account."
        aside={<span className="rounded-full bg-moss/10 px-3 py-1 text-xs font-semibold text-moss">Step 3</span>}
      >
        <p className="mb-4 text-sm text-ink/70">Owner: {owner ? `${owner.name} (${owner.id})` : "not set"}</p>
        {error ? <p className="mb-4 text-sm text-ember">{error}</p> : null}
        <div className="grid gap-4">
          {employees.length > 0 ? (
            employees.map((employee) => (
              <Link
                key={employee.id}
                className="rounded-[24px] border border-ink/10 bg-sand px-4 py-4 transition hover:-translate-y-0.5 hover:shadow-sm"
                to={`/employees/${employee.id}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold text-ink">{employee.name}</p>
                    <p className="text-sm text-ink/70">{employee.role}</p>
                  </div>
                  <div className="text-right text-sm">
                    <p className="rounded-full bg-white px-3 py-1 text-ink">{employee.current_state}</p>
                    <p className="mt-2 text-ink/60">{employee.model_config}</p>
                  </div>
                </div>
              </Link>
            ))
          ) : (
            <p className="text-sm text-ink/70">No employees yet. Register and create one first.</p>
          )}
        </div>
      </SectionCard>
    </div>
  );
}
