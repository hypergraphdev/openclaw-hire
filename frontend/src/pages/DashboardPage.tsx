import { useEffect, useState } from "react";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import type { AppShellContext } from "../App";
import { useOutletContext } from "react-router-dom";
import { StatusPill } from "../components/StatusPill";

export function DashboardPage() {
  const { owner, refreshEmployees } = useOutletContext<AppShellContext>();
  const [summary, setSummary] = useState({ total: 0, ready: 0, waiting_bot_token: 0, provisioning: 0, failed: 0 });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!owner) {
      return;
    }

    let isActive = true;
    setBusy(true);

    Promise.all([api.dashboard(owner.id), refreshEmployees()])
      .then(([dashboardData]) => {
        if (!isActive) {
          return;
        }
        setSummary(dashboardData.summary);
      })
      .catch(() => {
        if (!isActive) {
          return;
        }
        setSummary({ total: 0, ready: 0, waiting_bot_token: 0, provisioning: 0, failed: 0 });
      })
      .finally(() => {
        if (isActive) {
          setBusy(false);
        }
      });

    const timer = window.setInterval(() => {
      api
        .dashboard(owner.id)
        .then((dashboardData) => {
          if (!isActive) {
            return;
          }
          setSummary(dashboardData.summary);
        })
        .catch(() => {
          if (!isActive) {
            return;
          }
          setSummary({ total: 0, ready: 0, waiting_bot_token: 0, provisioning: 0, failed: 0 });
        });
    }, 12000);

    return () => {
      isActive = false;
      window.clearInterval(timer);
    };
  }, [owner, refreshEmployees]);

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Dashboard"
        subtitle="OpenClaw 多页面控制台总览：账户状态、员工池规模与初始化健康度一眼可见。"
        aside={<StatusPill state={owner ? "ready" : "queued"} />}
      >
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="rounded-[24px] border border-white/10 bg-slate-950/45 p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-slate-500">Account</p>
            <p className="mt-3 text-lg font-semibold text-white">{owner ? owner.name : "未登录"}</p>
            <p className="mt-2 text-sm text-slate-400">{owner ? owner.email : "请先去 Settings 注册/登录账户。"}</p>
          </div>

          <div className="rounded-[24px] border border-white/10 bg-slate-950/45 p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-slate-500">总 Agent 数</p>
            <p className="mt-3 text-3xl font-semibold text-white">{owner ? summary.total : 0}</p>
            <p className="mt-2 text-sm text-slate-400">{busy ? "正在同步状态..." : "已同步最新状态"}</p>
          </div>

          <div className="rounded-[24px] border border-white/10 bg-slate-950/45 p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-slate-500">初始化链路</p>
            <p className="mt-3 text-sm text-white">就绪：{summary.ready}</p>
            <p className="mt-2 text-sm text-slate-400">待 Token：{summary.waiting_bot_token}</p>
            <p className="mt-2 text-sm text-slate-400">进行中：{summary.provisioning}</p>
            <p className="mt-2 text-sm text-slate-400">失败：{summary.failed}</p>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
