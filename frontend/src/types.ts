export type User = {
  id: string;
  name: string;
  email: string;
  company_name?: string | null;
  created_at: string;
};

export type TemplateConfig = {
  id: string;
  name: string;
  description: string;
  codex_profile: string;
  notes: string[];
};

export type HireStack = "openclaw" | "zylos";

export type Employee = {
  id: string;
  owner_id: string;
  name: string;
  role: string;
  template_id: string;
  stack: HireStack;
  repo_url: string;
  brief?: string | null;
  telegram_handle?: string | null;
  model_config: string;
  current_state: string;
  created_at: string;
  updated_at: string;
  telegram_bot_token_placeholder?: string | null;
};

export type StatusEvent = {
  state: string;
  message: string;
  created_at: string;
};

export type EmployeeDetail = {
  employee: Employee;
  timeline: StatusEvent[];
};

export type DashboardSummary = {
  total: number;
  ready: number;
  waiting_bot_token: number;
  provisioning: number;
  failed: number;
};

export type DashboardData = {
  owner: User;
  summary: DashboardSummary;
};
