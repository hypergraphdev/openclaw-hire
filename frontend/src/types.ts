export type User = {
  id: string;
  name: string;
  email: string;
  company_name?: string | null;
  created_at: string;
};

export type Employee = {
  id: string;
  owner_id: string;
  name: string;
  role: string;
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
