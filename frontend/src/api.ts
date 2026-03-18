import type { AdminUserInstances, AuthToken, DashboardData, Instance, InstanceDetail, InstanceLogs, ProductCatalog, TelegramConfigResponse, User } from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://127.0.0.1:8010" : "/openclaw");

const TOKEN_KEY = "openclaw_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> ?? {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed." }));
    const err = new Error(payload.detail ?? "Request failed.") as Error & { status: number };
    err.status = response.status;
    throw err;
  }

  return response.json() as Promise<T>;
}

export const api = {
  // Auth
  register: (payload: { name: string; email: string; password: string; company_name?: string }) =>
    request<AuthToken>("/api/auth/register", { method: "POST", body: JSON.stringify(payload) }),

  login: (payload: { email: string; password: string }) =>
    request<AuthToken>("/api/auth/login", { method: "POST", body: JSON.stringify(payload) }),

  me: () => request<User>("/api/auth/me"),

  // Catalog
  catalog: () => request<ProductCatalog[]>("/api/catalog"),

  // Instances
  createInstance: (payload: { name: string; product: string }) =>
    request<Instance>("/api/instances", { method: "POST", body: JSON.stringify(payload) }),

  listInstances: () => request<Instance[]>("/api/instances"),

  getInstance: (id: string) => request<InstanceDetail>(`/api/instances/${id}`),

  startInstall: (id: string) =>
    request<Instance>(`/api/instances/${id}/install`, { method: "POST" }),

  stopInstance: (id: string) =>
    request<Instance>(`/api/instances/${id}/stop`, { method: "POST" }),

  restartInstance: (id: string) =>
    request<Instance>(`/api/instances/${id}/restart`, { method: "POST" }),

  uninstallInstance: (id: string) =>
    request<Instance>(`/api/instances/${id}/uninstall`, { method: "POST" }),

  deleteInstance: (id: string) =>
    request<{ status: string; instance_id: string }>(`/api/instances/${id}`, { method: "DELETE" }),

  instanceLogs: (id: string, lines = 200) =>
    request<InstanceLogs>(`/api/instances/${id}/logs?lines=${lines}`),

  configureInstance: (id: string, botToken: string) =>
    request<TelegramConfigResponse>(`/api/instances/${id}/configure`, {
      method: "POST",
      body: JSON.stringify({ telegram_bot_token: botToken }),
    }),

  // Dashboard (derived from instances)
  dashboard: () => request<User>("/api/auth/me").then(async (user) => {
    const instances = await request<Instance[]>("/api/instances");
    const summary = {
      total: instances.length,
      running: instances.filter((i) => i.install_state === "running").length,
      idle: instances.filter((i) => i.install_state === "idle").length,
      installing: instances.filter((i) =>
        ["pulling", "configuring", "starting"].includes(i.install_state)
      ).length,
      failed: instances.filter((i) => i.install_state === "failed" || i.status === "failed").length,
    };
    return { user, summary } as DashboardData;
  }),

  adminUsers: () => request<User[]>("/api/admin/users"),

  adminUserInstances: (userId: string) =>
    request<AdminUserInstances>(`/api/admin/users/${userId}/instances`),

  // Raw fetch helpers (return Response)
  get: (path: string) => {
    const token = getStoredToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`${API_BASE}${path}`, { headers });
  },

  put: (path: string, body: unknown) => {
    const token = getStoredToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`${API_BASE}${path}`, { method: "PUT", headers, body: JSON.stringify(body) });
  },
};
