export type User = {
  id: string;
  name: string;
  email: string;
  company_name?: string | null;
  created_at: string;
};

export type Product = "openclaw" | "zylos";

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
  http_port?: number | null;
  telegram_bot_token?: string | null;
  org_token?: string | null;
  created_at: string;
  updated_at: string;
};

export type TelegramConfigResponse = {
  instance_id: string;
  plugin_name: string;
  hub_url: string;
  org_id: string;
  org_token: string;
  message: string;
};

export type InstanceConfig = {
  plugin_name?: string | null;
  hub_url?: string | null;
  org_id?: string | null;
  org_token?: string | null;
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
