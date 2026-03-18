import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: "▦" },
  { to: "/catalog", label: "Product Catalog", icon: "◈" },
  { to: "/instances", label: "My Instances", icon: "⊞" },
];

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        {/* Brand */}
        <div className="px-6 py-5 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <span className="text-blue-400 text-lg font-bold tracking-tight">◈ OpenClaw</span>
            <span className="text-xs text-gray-500 ml-1">Hire</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">Cloud Console</p>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV_ITEMS.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-800"
                }`
              }
            >
              <span className="text-base leading-none">{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User footer */}
        {user && (
          <div className="px-4 py-4 border-t border-gray-800">
            <div className="text-xs text-gray-500 truncate">{user.email}</div>
            <div className="text-sm text-gray-300 truncate font-medium">{user.name}</div>
            {user.company_name && (
              <div className="text-xs text-gray-500 mt-0.5 truncate">{user.company_name}</div>
            )}
            <button
              onClick={handleLogout}
              className="mt-3 w-full text-xs text-gray-500 hover:text-red-400 transition-colors text-left"
            >
              Sign out →
            </button>
          </div>
        )}
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto px-8 py-8">
          {children}
        </div>
      </main>
    </div>
  );
}
