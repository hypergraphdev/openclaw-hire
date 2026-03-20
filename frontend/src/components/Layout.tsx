import { useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { useT } from "../contexts/LanguageContext";

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const t = useT();

  const items = [
    { to: "/dashboard", label: t("nav.dashboard"), icon: "▦" },
    { to: "/catalog", label: t("nav.catalog"), icon: "◈" },
    { to: "/instances", label: t("nav.instances"), icon: "⊞" },
    ...(user?.is_admin ? [{ to: "/admin", label: t("nav.admin"), icon: "⚙" }] : []),
    { to: "/settings", label: t("nav.settings"), icon: "☰" },
  ];

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Mobile top bar */}
      <header className="md:hidden sticky top-0 z-40 bg-gray-900/95 border-b border-gray-800 backdrop-blur">
        <div className="h-14 px-4 flex items-center justify-between">
          <div className="text-blue-400 text-base font-bold tracking-tight">{t("layout.brand")} <span className="text-xs text-gray-500">{t("layout.brandSuffix")}</span></div>
          <button
            onClick={() => setMobileMenuOpen((v) => !v)}
            className="text-sm px-3 py-1.5 rounded-md bg-gray-800 text-gray-200"
          >
            {mobileMenuOpen ? t("layout.close") : t("layout.menu")}
          </button>
        </div>

        {mobileMenuOpen && (
          <div className="border-t border-gray-800 px-3 py-3 space-y-1">
            {items.map(({ to, label, icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                    isActive ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-800"
                  }`
                }
              >
                <span className="text-base leading-none">{icon}</span>
                {label}
              </NavLink>
            ))}

            {user && (
              <div className="mt-3 pt-3 border-t border-gray-800">
                <div className="text-xs text-gray-500 truncate">{user.email}</div>
                <div className="text-sm text-gray-300 truncate font-medium">{user.name}</div>
                <button
                  onClick={handleLogout}
                  className="mt-2 text-xs text-gray-500 hover:text-red-400 transition-colors"
                >
                  {t("nav.signout")}
                </button>
              </div>
            )}
          </div>
        )}
      </header>

      <div className="md:flex md:h-screen md:overflow-hidden">
        {/* Desktop sidebar */}
        <aside className="hidden md:flex w-64 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex-col">
          <div className="px-6 py-5 border-b border-gray-800">
            <div className="flex items-center gap-2">
              <span className="text-blue-400 text-lg font-bold tracking-tight">{t("layout.brand")}</span>
              <span className="text-xs text-gray-500 ml-1">{t("layout.brandSuffix")}</span>
            </div>
            <p className="text-xs text-gray-500 mt-1">{t("layout.subtitle")}</p>
          </div>

          <nav className="flex-1 px-3 py-4 space-y-1">
            {items.map(({ to, label, icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                    isActive ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-800"
                  }`
                }
              >
                <span className="text-base leading-none">{icon}</span>
                {label}
              </NavLink>
            ))}
          </nav>

          {user && (
            <div className="px-4 py-4 border-t border-gray-800">
              <div className="text-xs text-gray-500 truncate">{user.email}</div>
              <div className="text-sm text-gray-300 truncate font-medium">{user.name}</div>
              {user.company_name && <div className="text-xs text-gray-500 mt-0.5 truncate">{user.company_name}</div>}
              <button
                onClick={handleLogout}
                className="mt-3 w-full text-xs text-gray-500 hover:text-red-400 transition-colors text-left"
              >
                {t("nav.signout")}
              </button>
            </div>
          )}
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto">
          <div className="px-4 md:px-8 py-4 md:py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
