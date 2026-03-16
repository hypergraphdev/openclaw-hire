import type { Employee, EmployeeDetail, User } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8010";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed." }));
    throw new Error(payload.detail ?? "Request failed.");
  }

  return response.json() as Promise<T>;
}

export const api = {
  registerUser: (payload: { name: string; email: string; company_name?: string }) =>
    request<User>("/api/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createEmployee: (payload: {
    owner_id: string;
    name: string;
    role: string;
    brief?: string;
    telegram_handle?: string;
  }) =>
    request<Employee>("/api/employees", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listEmployees: (ownerId: string) => request<Employee[]>(`/api/owners/${ownerId}/employees`),
  getEmployeeStatus: (employeeId: string) => request<EmployeeDetail>(`/api/employees/${employeeId}/status`),
  saveBotToken: (employeeId: string, telegram_bot_token_placeholder: string) =>
    request<EmployeeDetail>(`/api/employees/${employeeId}/bot-token`, {
      method: "POST",
      body: JSON.stringify({ telegram_bot_token_placeholder }),
    }),
};
