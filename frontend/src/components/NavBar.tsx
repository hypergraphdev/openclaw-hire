import { NavLink } from "react-router-dom";

const links = [
  { to: "/dashboard", label: "Dashboard", detail: "总览与告警" },
  { to: "/settings", label: "Settings / Profile", detail: "账户与偏好" },
  { to: "/agents/new", label: "Create Agent", detail: "创建员工/AI 实例" },
  { to: "/agents", label: "Agent Fleet", detail: "管理所有雇佣" },
  { to: "/templates", label: "Templates", detail: "默认模型模板库" },
];

export function NavBar() {
  return (
    <nav className="grid gap-2">
      {links.map((link) => (
        <NavLink
          key={link.to}
          to={link.to}
          className={({ isActive }) =>
            `group rounded-2xl border px-4 py-3 transition ${
              isActive
                ? "border-white/15 bg-white/10 text-white shadow-lg shadow-slate-950/10"
                : "border-transparent bg-transparent text-slate-300 hover:border-white/10 hover:bg-white/5 hover:text-white"
            }`
          }
        >
          <p className="text-sm font-semibold">{link.label}</p>
          <p className="mt-1 text-xs text-slate-400 group-hover:text-slate-300">{link.detail}</p>
        </NavLink>
      ))}
    </nav>
  );
}
