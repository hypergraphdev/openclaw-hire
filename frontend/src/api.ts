import type { AdminUserInstances, AuthToken, ChatInfo, ChatMessagesResponse, ChatPeer, ChatSendResponse, ChatWsTicketResponse, DashboardData, HxaOrg, HxaOrgAgent, HxaOrgDetail, Instance, InstanceDetail, InstanceLogs, MyOrgData, OrgThread, ProductCatalog, TelegramConfigResponse, ThreadMessage, User } from "./types";

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

  renameAgent: (id: string, agentName: string) =>
    request<{ ok: boolean; agent_name: string }>(`/api/instances/${id}/agent-name`, {
      method: "PUT",
      body: JSON.stringify({ agent_name: agentName }),
    }),

  instanceLogs: (id: string, lines = 200) =>
    request<InstanceLogs>(`/api/instances/${id}/logs?lines=${lines}`),

  configureInstance: (id: string, botToken: string) =>
    request<TelegramConfigResponse>(`/api/instances/${id}/configure`, {
      method: "POST",
      body: JSON.stringify({ telegram_bot_token: botToken }),
    }),

  configureTelegram: (id: string, botToken: string) =>
    request<{ ok: boolean; message: string }>(`/api/instances/${id}/configure-telegram`, {
      method: "POST",
      body: JSON.stringify({ telegram_bot_token: botToken }),
    }),

  configureHxa: (id: string) =>
    request<{ ok: boolean; message: string }>(`/api/instances/${id}/configure-hxa`, {
      method: "POST",
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

  platformStats: () => request<{ total_users: number; total_bots: number; running_bots: number; org_bots: number }>("/api/admin/stats"),

  adminUsers: () => request<User[]>("/api/admin/users"),

  adminUserInstances: (userId: string) =>
    request<AdminUserInstances>(`/api/admin/users/${userId}/instances`),

  // Chat proxy
  chatInfo: (id: string) =>
    request<ChatInfo>(`/api/instances/${id}/chat/info`),

  chatPeers: (id: string) =>
    request<ChatPeer[]>(`/api/instances/${id}/chat/peers`),

  chatSend: (id: string, content: string, imageUrl?: string) =>
    request<ChatSendResponse>(`/api/instances/${id}/chat/send`, {
      method: "POST",
      body: JSON.stringify({ content, image_url: imageUrl || null }),
    }),

  chatUpload: async (id: string, file: File): Promise<{ url: string; filename: string }> => {
    const token = getStoredToken();
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/instances/${id}/chat/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "上传失败" }));
      throw new Error(err.detail || "上传失败");
    }
    return res.json();
  },

  chatMessages: (id: string, channelId: string, before?: string) => {
    const params = new URLSearchParams({ channel_id: channelId, limit: "50" });
    if (before) params.set("before", before);
    return request<ChatMessagesResponse>(`/api/instances/${id}/chat/messages?${params}`);
  },

  chatWsTicket: (id: string) =>
    request<ChatWsTicketResponse>(`/api/instances/${id}/chat/ws-ticket`, { method: "POST" }),

  // My Organization
  myOrg: () => request<MyOrgData>("/api/my-org"),
  myOrgChatInfo: (target: string) => request<ChatInfo>(`/api/my-org/chat/info?target=${encodeURIComponent(target)}`),
  myOrgChatSend: (target: string, content: string, imageUrl?: string) =>
    request<ChatSendResponse>("/api/my-org/chat/send", {
      method: "POST", body: JSON.stringify({ target_bot_name: target, content, image_url: imageUrl || null }),
    }),
  myOrgChatMessages: (channelId: string, target: string, before?: string) => {
    const params = new URLSearchParams({ channel_id: channelId, target, limit: "50" });
    if (before) params.set("before", before);
    return request<ChatMessagesResponse>(`/api/my-org/chat/messages?${params}`);
  },
  myOrgChatWsTicket: (target: string) =>
    request<ChatWsTicketResponse>(`/api/my-org/chat/ws-ticket?target=${encodeURIComponent(target)}`, { method: "POST" }),

  // Threads (group chat)
  myOrgThreads: () => request<{ threads: OrgThread[] }>("/api/my-org/threads"),
  myOrgCreateThread: (topic: string, participantNames: string[]) =>
    request<OrgThread>("/api/my-org/threads", {
      method: "POST", body: JSON.stringify({ topic, participant_names: participantNames }),
    }),
  myOrgThreadMessages: (threadId: string, before?: string) => {
    const params = new URLSearchParams({ limit: "50" });
    if (before) params.set("before", before);
    return request<{ messages: ThreadMessage[]; has_more: boolean }>(`/api/my-org/threads/${threadId}/messages?${params}`);
  },
  myOrgThreadSend: (threadId: string, content: string, imageUrl?: string) =>
    request<ThreadMessage>(`/api/my-org/threads/${threadId}/messages`, {
      method: "POST", body: JSON.stringify({ content, image_url: imageUrl || null }),
    }),

  myOrgChatUpload: async (file: File): Promise<{ url: string; filename: string }> => {
    const token = getStoredToken();
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/my-org/chat/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Upload failed" }));
      throw new Error(err.detail || "Upload failed");
    }
    return res.json();
  },

  // HXA Organization management
  hxaOrgs: () => request<{ orgs: HxaOrg[] }>("/api/admin/hxa/orgs"),

  hxaCreateOrg: (name: string) =>
    request<HxaOrgDetail>("/api/admin/hxa/orgs", { method: "POST", body: JSON.stringify({ name }) }),

  hxaUpdateOrg: (orgId: string, name: string) =>
    request<{ id: string; name: string; status: string }>(`/api/admin/hxa/orgs/${orgId}`, {
      method: "PATCH", body: JSON.stringify({ name }),
    }),

  hxaDeleteOrg: (orgId: string) =>
    request<{ ok: boolean }>(`/api/admin/hxa/orgs/${orgId}`, { method: "DELETE" }),

  hxaRotateSecret: (orgId: string) =>
    request<{ org_secret: string }>(`/api/admin/hxa/orgs/${orgId}/rotate-secret`, { method: "POST" }),

  hxaSetDefaultOrg: (orgId: string) =>
    request<{ ok: boolean }>(`/api/admin/hxa/orgs/${orgId}/set-default`, { method: "POST" }),

  hxaOrgAgents: (orgId: string) =>
    request<{ agents: HxaOrgAgent[]; org_name: string }>(`/api/admin/hxa/orgs/${orgId}/agents`),

  hxaTransferBot: (instanceId: string, targetOrgId: string) =>
    request<{ ok: boolean; new_org_id: string; agent_name: string }>(`/api/admin/hxa/bots/${instanceId}/transfer`, {
      method: "POST", body: JSON.stringify({ target_org_id: targetOrgId }),
    }),

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
