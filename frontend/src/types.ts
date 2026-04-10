export type User = {
  id: string;
  name: string;
  email: string;
  company_name?: string | null;
  is_admin?: boolean;
  created_at: string;
};

export type Product = "openclaw" | "zylos" | "hermes";

export type ProductCatalog = {
  id: string;
  name: string;
  description: string;
  tagline: string;
  repo_url: string;
  tags: string[];
  features: string[];
};

export type Instance = {
  id: string;
  owner_id: string;
  name: string;
  product: Product;
  repo_url: string;
  status: "active" | "failed" | "inactive" | "installing";
  install_state: "idle" | "pulling" | "configuring" | "starting" | "running" | "failed";
  compose_project?: string | null;
  compose_file?: string | null;
  runtime_dir?: string | null;
  web_console_port?: number | null;
  web_console_url?: string | null;
  http_port?: number | null;
  is_telegram_configured?: boolean;
  telegram_token_hint?: string | null;
  // org_token removed - sensitive
  agent_name?: string | null;
  org_id?: string | null;
  org_name?: string | null;
  created_at: string;
  updated_at: string;
};

export type TelegramConfigResponse = {
  instance_id: string;
  plugin_name: string;
  hub_url: string;
  org_id: string;
  // org_token removed - sensitive
  agent_name: string;
  message: string;
};

export type InstanceConfig = {
  plugin_name?: string | null;
  hub_url?: string | null;
  org_id?: string | null;
  org_name?: string | null;
  // org_token removed - sensitive
  agent_name?: string | null;
  allow_group?: boolean;
  allow_dm?: boolean;
  configured_at?: string | null;
};

export type InstallEvent = {
  id: number;
  state: string;
  message: string;
  created_at: string;
};

export type InstanceDetail = {
  instance: Instance;
  install_timeline: InstallEvent[];
  config?: InstanceConfig | null;
};

export type InstanceLogs = {
  instance_id: string;
  compose_project?: string | null;
  logs: string;
};

export type AuthToken = {
  access_token: string;
  token_type: string;
  user: User;
};

export type DashboardSummary = {
  total: number;
  running: number;
  idle: number;
  installing: number;
  failed: number;
};

export type DashboardData = {
  user: User;
  summary: DashboardSummary;
};

export type AdminUserInstances = {
  user: User;
  instances: Instance[];
};

// ─── Docker container management ───

export type DockerContainerInfo = {
  name: string;
  state: string;
  status: string;
};

export type DockerContainerGroup = {
  project: string;
  containers: DockerContainerInfo[];
  product: string;
  instance_id: string | null;
  instance_name: string | null;
  owner_email: string | null;
  install_state: string | null;
  runtime_dir: string | null;
  runtime_exists: boolean;
  is_orphan: boolean;
  is_ghost?: boolean;
  owner_name?: string | null;
};

// ─── Chat types ───

export type ChatPeer = {
  id: string;
  name: string;
  online: boolean;
};

export type ChatInfo = {
  target_name: string;
  target_online: boolean;
  target_id: string;
  admin_bot_name: string;
  admin_bot_id: string;
  instance_bot_name?: string;
  instance_bot_id?: string;
  dm_channel_id?: string;
};

export type ChatMessage = {
  id: string;
  channel_id: string;
  sender_id: string;
  sender_name: string;
  content: string;
  content_type?: string;
  parts?: { type: string; content?: string; url?: string; alt?: string; name?: string }[];
  created_at: number;
};

export type ChatMessagesResponse = {
  messages: ChatMessage[];
  has_more: boolean;
};

export type ChatSendResponse = {
  channel_id: string;
  message: ChatMessage;
};

export type ChatWsTicketResponse = {
  ticket: string;
  ws_url: string;
};

// ─── HXA Organization types ───

export type HxaOrg = {
  id: string;
  name: string;
  status: string;
  bot_count: number;
  created_at: number;
  is_default: boolean;
};

export type HxaOrgDetail = {
  id: string;
  name: string;
  status: string;
  org_secret?: string;
  created_at?: number;
};

// ─── My Org types ───

export type MyOrgBot = {
  instance_id: string;
  instance_name: string;
  agent_name: string;
  product: string;
};

export type MyOrgPeer = {
  bot_id: string;
  name: string;
  online: boolean;
  is_mine: boolean;
};

export type MyOrgInfo = {
  org_id: string;
  org_name: string;
  is_default: boolean;
  is_active: boolean;
};

export type MyOrgData = {
  status: "ok" | "no_instances" | "no_org";
  org_id?: string;
  org_name?: string;
  is_default_org?: boolean;
  my_bots?: MyOrgBot[];
  all_bots?: MyOrgPeer[];
  orgs?: MyOrgInfo[];
};

export type OrgThread = {
  id: string;
  topic: string;
  status: string;
  created_at: number;
  last_activity_at: number;
  participant_count?: number;
};

export type ThreadMessage = {
  id: string;
  thread_id: string;
  sender_id: string | null;
  sender_name?: string;
  content: string;
  created_at: number;
};

export type SearchResult = {
  id: string;
  org_id: string;
  channel_type: string;
  channel_id: string;
  channel_name: string;
  sender_id: string;
  sender_name: string;
  content: string;
  mentions: string;
  created_at: number;
};

// ─── HXA Organization types ───

export type HxaOrgAgent = {
  bot_id: string;
  name: string;
  online: boolean;
  auth_role: string;
  token_prefix: string;
  instance_id?: string | null;
  instance_name?: string | null;
  product?: string | null;
  owner_name?: string | null;
  owner_email?: string | null;
};

// Metrics types
export type InstanceMetric = {
  collected_at: string;
  cpu_percent: number | null;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  disk_usage_mb: number | null;
  claude_running: boolean;
  claude_mem_mb: number | null;
};

export type MetricsResponse = {
  metrics: InstanceMetric[];
  summary: {
    avg_cpu: number;
    max_cpu: number;
    avg_mem: number;
    max_mem: number;
    data_points: number;
  };
};

export type SparklineResponse = {
  values: number[];
  labels: string[];
};

// ─── Alert types ───

export type Alert = {
  id: string;
  instance_id: string | null;
  alert_type: string;
  severity: "info" | "warning" | "critical";
  message: string;
  is_read: number;
  created_at: string;
  resolved_at: string | null;
};

export type AlertsResponse = {
  alerts: Alert[];
  unread_count: number;
};

export type ConnectivityResult = {
  ok: boolean;
  elapsed_ms: number;
  detail?: string;
  error?: string;
};

export type ConnectivityTestResponse = Record<string, ConnectivityResult>;

// ─── Session types ───

export type SessionTokenUsage = {
  input: number;
  output: number;
};

export type ClaudeSession = {
  id: string;
  type: string;
  lastActivity: string;
  tokenUsage?: SessionTokenUsage;
};

export type SessionsResponse = {
  sessions: ClaudeSession[];
  count: number;
  container: string;
};

export type SessionClearResponse = {
  ok: boolean;
  detail: string;
};

// ─── Skills/Plugins types ───

export type InstanceSkill = {
  id: string;
  name: string;
  source: "extension" | "component" | "skill";
  description: string;
};

export type SkillsResponse = {
  skills: InstanceSkill[];
};

export type SkillContentResponse = {
  content: string;
  filename: string;
};

// ─── Agent Activity types ───

export type AgentServiceInfo = {
  name: string;
  status: string;
  uptime: string;
  memory_mb: number;
  restarts: number;
};

export type AgentActivityResponse = {
  claude: {
    running: boolean;
    pid: number | null;
    uptime_seconds: number | null;
    memory_mb: number | null;
  };
  services: AgentServiceInfo[];
  state: "idle" | "busy" | "waiting" | "offline";
};

// ─── Marketplace types ───

export type MarketplaceItem = {
  id: string;
  type: "plugin" | "skill";
  name: string;
  name_zh?: string;
  description: string;
  description_zh?: string;
  icon: string;
  product: "openclaw" | "zylos" | "hermes" | "all";
  tags: string[];
  version: string;
  install_time?: string;
  note?: string;
  note_zh?: string;
  models?: string[];
};

export type MarketplaceInstall = {
  item_id: string;
  item_type: "plugin" | "skill";
  status: "installing" | "installed" | "failed";
  install_log: string;
  installed_at: string;
};

// ─── Thread Quality Control types ───

export type TaskDepth = "shallow" | "moderate" | "thorough" | "exhaustive";
export type TaskStatus = "pending" | "in_progress" | "review" | "revision" | "completed" | "failed";

export type ThreadTask = {
  id: string;
  thread_id: string;
  title: string;
  description: string;
  assigned_to: string;
  assigned_by: string;
  status: TaskStatus;
  depth: TaskDepth;
  acceptance_criteria: string[];
  quality_score: number | null;
  quality_feedback: string | null;
  revision_count: number;
  max_revisions: number;
  created_at: string;
  updated_at: string;
};

export type QCConfig = {
  thread_id: string;
  enabled: boolean;
  min_quality_score?: number;
  auto_revision?: boolean;
  max_revisions?: number;
  has_api_key?: boolean;
};

export type TaskEvaluation = {
  overall_score: number;
  dimensions: Record<string, number>;
  verdict: "PASS" | "REVISE" | "FAIL";
  feedback: string;
  unmet_criteria: string[];
  strengths: string[];
};

export type EvaluateResult = {
  task_id: string;
  evaluation: TaskEvaluation;
  new_status: string;
  revision_sent: boolean;
};
