import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, Outlet, Navigate, Route, Routes } from "react-router-dom";

import { api } from "./api";
import { PhoneFrame } from "./components/PhoneFrame";
import { DashboardPage } from "./pages/DashboardPage";
import { SettingsPage } from "./pages/SettingsPage";
import { CreateAgentPage } from "./pages/CreateAgentPage";
import { AgentFleetPage } from "./pages/AgentFleetPage";
import { AgentDetailPage } from "./pages/AgentDetailPage";
import { TemplatesPage } from "./pages/TemplatesPage";
import type { Employee, User } from "./types";

const OWNER_STORAGE_KEY = "openclaw_owner";

export type AppShellContext = {
  employees: Employee[];
  owner: User | null;
  refreshEmployees: () => Promise<void>;
  setOwner: (owner: User | null) => void;
};

function normalizeBasename(baseUrl: string) {
  const trimmed = baseUrl.replace(/\/+$/, "");
  return trimmed === "" ? "/" : trimmed;
}

function AppShell() {
  const [owner, setOwnerState] = useState<User | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);

  const setOwner = useCallback((nextOwner: User | null) => {
    setOwnerState(nextOwner);
    if (nextOwner) {
      localStorage.setItem(OWNER_STORAGE_KEY, JSON.stringify(nextOwner));
      return;
    }
    localStorage.removeItem(OWNER_STORAGE_KEY);
    setEmployees([]);
  }, []);

  const refreshEmployees = useCallback(async () => {
    if (!owner) {
      setEmployees([]);
      return;
    }

    const nextEmployees = await api.listEmployees(owner.id);
    setEmployees(nextEmployees);
  }, [owner]);

  useEffect(() => {
    const storedOwner = localStorage.getItem(OWNER_STORAGE_KEY);
    if (!storedOwner) {
      return;
    }
    setOwnerState(JSON.parse(storedOwner) as User);
  }, []);

  useEffect(() => {
    refreshEmployees().catch(() => {
      setEmployees([]);
    });
  }, [refreshEmployees]);

  return (
    <PhoneFrame employees={employees} owner={owner}>
      <Outlet context={{ employees, owner, refreshEmployees, setOwner }} />
    </PhoneFrame>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={normalizeBasename(import.meta.env.BASE_URL)}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate replace to="/dashboard" />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/agents/new" element={<CreateAgentPage />} />
          <Route path="/agents" element={<AgentFleetPage />} />
          <Route path="/agents/:employeeId" element={<AgentDetailPage />} />
          <Route path="/templates" element={<TemplatesPage />} />
          <Route path="*" element={<Navigate replace to="/dashboard" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
