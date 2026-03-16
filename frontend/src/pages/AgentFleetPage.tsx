import { Link, useOutletContext } from "react-router-dom";

import { api } from "../api";
import type { Employee } from "../types";
import type { AppShellContext } from "../App";
import { SectionCard } from "../components/SectionCard";
import { StatusPill } from "../components/StatusPill";
import { formatDateTime } from "../lib/formatters";

export function AgentFleetPage() {
  const { employees, owner } = useOutletContext<AppShellContext>();

  const canLaunch = owner && employees.length > 0;

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Agent Fleet"
        subtitle="展示用户雇佣的 AI Agent 列表。可查看每个实例状态、模型与 owner 绑定。"
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="overflow-hidden rounded-[24px] border border-white/10">
            <div className="hidden grid-cols-[1.4fr_1fr_1fr_1fr] gap-4 border-b border-white/10 bg-white/5 px-5 py-4 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 md:grid">
              <p>Agent</p>
              <p>状态</p>
              <p>模型</p>
              <p>更新时间</p>
            </div>
            <div className="grid">
              {employees.length > 0 ? (
                employees.map((employee: Employee) => (
                  <Link
                    key={employee.id}
                    className="grid gap-4 border-b border-white/10 bg-slate-950/30 px-5 py-4 transition hover:bg-white/5 md:grid-cols-[1.4fr_1fr_1fr_1fr]"
                    to={`/agents/${employee.id}`}
                  >
                    <div>
                      <p className="text-base font-semibold text-white">{employee.name}</p>
                      <p className="mt-1 text-sm text-slate-400">{employee.role}</p>
                      <p className="mt-2 text-xs text-slate-500">{employee.id}</p>
                    </div>
                    <div className="flex items-start md:items-center">
                      <StatusPill state={employee.current_state} />
                    </div>
                    <div className="text-sm text-slate-300">{employee.model_config}</div>
                    <div className="text-sm text-slate-400">{formatDateTime(employee.updated_at)}</div>
                  </Link>
                ))
              ) : (
                <div className="px-5 py-10 text-sm text-slate-400">
                  {canLaunch
                    ? "该用户还没有雇佣过 Agent。去 Create Agent 发起第一位同伴。"
                    : "未检测到账户或雇佣记录，请先在 Settings 注册并创建 Agent。"}
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-4">
            <div className="rounded-[24px] border border-white/10 bg-slate-950/45 p-5">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">所有者</p>
              <p className="mt-2 text-lg font-semibold text-white">{owner ? owner.name : "未登录"}</p>
              <p className="mt-1 text-sm text-slate-400">{owner ? owner.email : "去 Settings 注册"}</p>
            </div>
            <div className="rounded-[24px] border border-white/10 bg-slate-950/45 p-5 text-sm text-slate-300">
              <p className="font-semibold text-white">Fleet 说明</p>
              <p className="mt-3">一人可雇佣多人，每个雇佣记录拥有独立状态、时间线和配置。初始化过程支持后端脚本异步推进。 </p>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
