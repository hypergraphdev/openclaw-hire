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
  created_at: string;
  updated_at: string;
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
