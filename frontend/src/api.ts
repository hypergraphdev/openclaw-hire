import type { AdminUserInstances, AgentActivityResponse, AlertsResponse, AuthToken, ChatInfo, ChatMessagesResponse, ChatPeer, ChatSendResponse, ChatWsTicketResponse, ConnectivityTestResponse, DashboardData, HxaOrg, HxaOrgAgent, HxaOrgDetail, Instance, InstanceDetail, InstanceLogs, MetricsResponse, MyOrgData, OrgThread, ProductCatalog, SearchResult, SessionClearResponse, SessionsResponse, SkillContentResponse, SkillsResponse, SparklineResponse, TelegramConfigResponse, ThreadMessage, User } from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://127.0.0.1:8010" : "");

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

  adminHxaStatus: () =>
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    request<Record<string, { online: boolean; org_id: string; agent_name: string }>>("/api/admin/instances/hxa-status"),

  adminInstanceDiagnostics: (instanceId: string) =>
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    request<any>(`/api/admin/instances/${instanceId}/diagnostics`),

  adminInstanceControl: (instanceId: string, action: string) =>
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    request<any>(`/api/admin/instances/${instanceId}/control`, {
      method: "POST", body: JSON.stringify({ action }),
    }),

  adminInstanceResources: (instanceId: string, memoryMb: number, cpus: number) =>
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    request<any>(`/api/admin/instances/${instanceId}/resources`, {
      method: "POST", body: JSON.stringify({ memory_mb: memoryMb, cpus }),
    }),

  adminDockerContainers: () =>
    request<{ groups: import("./types").DockerContainerGroup[] }>("/api/admin/docker-containers"),

  adminDockerCleanup: (project: string, removeRuntime: boolean = true) =>
    request<{ ok: boolean; details: string[] }>("/api/admin/docker-cleanup", {
      method: "POST", body: JSON.stringify({ project, remove_runtime: removeRuntime }),
    }),

  // Metrics & Monitoring
  instanceMetrics: (id: string, hours?: number) =>
    request<MetricsResponse>(`/api/instances/${id}/metrics?hours=${hours ?? 24}`),
  instanceSparkline: (id: string, field?: string) =>
    request<SparklineResponse>(`/api/instances/${id}/metrics/sparkline?field=${field ?? "cpu_percent"}`),
  instanceConnectivityTest: (id: string) =>
    request<ConnectivityTestResponse>(`/api/instances/${id}/connectivity-test`, { method: "POST" }),

  agentActivity: (id: string) =>
    request<AgentActivityResponse>(`/api/instances/${id}/agent-activity`),

  // Sessions
  instanceSessions: (id: string) =>
    request<SessionsResponse>(`/api/instances/${id}/sessions`),
  instanceSessionsClear: (id: string) =>
    request<SessionClearResponse>(`/api/instances/${id}/sessions/clear`, { method: "POST" }),

  // Skills / Plugins
  instanceSkills: (id: string) =>
    request<SkillsResponse>(`/api/instances/${id}/skills`),
  instanceSkillContent: (id: string, skillId: string) =>
    request<SkillContentResponse>(`/api/instances/${id}/skills/${encodeURIComponent(skillId)}/content`),

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
  myOrg: (orgId?: string) => request<MyOrgData>(`/api/my-org${orgId ? `?org=${orgId}` : ""}`),
  myOrgChatInfo: (target: string, orgId?: string) => {
    const p = new URLSearchParams({ target });
    if (orgId) p.set("org", orgId);
    return request<ChatInfo>(`/api/my-org/chat/info?${p}`);
  },
  myOrgChatSend: (target: string, content: string, orgId?: string, imageUrl?: string, senderBot?: string) =>
    request<ChatSendResponse>("/api/my-org/chat/send", {
      method: "POST", body: JSON.stringify({ target_bot_name: target, content, image_url: imageUrl || null, org_id: orgId || null, sender_bot: senderBot || null }),
    }),
  myOrgChatMessages: (channelId: string, target: string, before?: string, orgId?: string) => {
    const params = new URLSearchParams({ channel_id: channelId, target, limit: "50" });
    if (before) params.set("before", before);
    if (orgId) params.set("org", orgId);
    return request<ChatMessagesResponse>(`/api/my-org/chat/messages?${params}`);
  },
  myOrgChatWsTicket: (target: string, extraParams?: URLSearchParams, orgId?: string) => {
    const p = new URLSearchParams({ target });
    if (orgId) p.set("org", orgId);
    if (extraParams) extraParams.forEach((v, k) => p.set(k, v));
    return request<ChatWsTicketResponse>(`/api/my-org/chat/ws-ticket?${p}`, { method: "POST" });
  },

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
  myOrgThreadSend: (threadId: string, content: string, imageUrl?: string, botInstanceId?: string) =>
    request<ThreadMessage>(`/api/my-org/threads/${threadId}/messages`, {
      method: "POST", body: JSON.stringify({ content, image_url: imageUrl || null, bot_instance_id: botInstanceId || null }),
    }),
  myOrgThreadDetail: (threadId: string) =>
    request<{ id: string; topic: string; initiator_id: string; context: string | null; participant_count: number; participants: { bot_id: string; name?: string; online: boolean }[] }>(`/api/my-org/threads/${threadId}`),
  myOrgThreadUpdate: (threadId: string, body: { topic?: string; context?: Record<string, unknown> }) =>
    request<unknown>(`/api/my-org/threads/${threadId}`, { method: "PATCH", body: JSON.stringify(body) }),
  myOrgThreadLeave: (threadId: string) =>
    request<{ ok: boolean }>(`/api/my-org/threads/${threadId}/leave`, { method: "POST" }),
  myOrgThreadInvite: (threadId: string, name: string) =>
    request<unknown>(`/api/my-org/threads/${threadId}/invite`, { method: "POST", body: JSON.stringify({ name }) }),
  myOrgThreadKick: (threadId: string, botId: string) =>
    request<{ ok: boolean }>(`/api/my-org/threads/${threadId}/kick`, { method: "POST", body: JSON.stringify({ bot_id: botId }) }),

  // Search
  myOrgSearchSync: () => request<{ ok: boolean; new_messages: number }>("/api/my-org/search/sync", { method: "POST" }),
  myOrgSearch: (params: { q?: string; in?: string; from?: string; to?: string }) => {
    const p = new URLSearchParams();
    if (params.q) p.set("q", params.q);
    if (params.in) p.set("in", params.in);
    if (params.from) p.set("from", params.from);
    if (params.to) p.set("to", params.to);
    return request<{ results: SearchResult[]; total: number }>(`/api/my-org/search?${p}`);
  },

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
  myOrgFileUpload: async (file: File): Promise<{ url: string; filename: string; size_kb: number }> => {
    const token = getStoredToken();
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/my-org/file/upload`, {
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

  adminDeleteOrgBot: (orgId: string, botId: string) =>
    request<{ ok: boolean }>(`/api/admin/hxa/orgs/${orgId}/bots/${botId}`, { method: "DELETE" }),

  // Alerts
  listAlerts: (unread?: boolean) =>
    request<AlertsResponse>(`/api/alerts${unread ? "?unread=true" : ""}`),

  markAlertRead: (id: string) =>
    request<{ ok: boolean }>(`/api/alerts/${id}/read`, { method: "POST" }),

  markAllAlertsRead: () =>
    request<{ ok: boolean }>("/api/alerts/read-all", { method: "POST" }),

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
