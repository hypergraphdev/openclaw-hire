import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { useT } from "../contexts/LanguageContext";

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const t = useT();
  const [form, setForm] = useState({ name: "", email: "", password: "", confirm: "", company_name: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function setField(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm) {
      setError(t("register.passwordMismatch"));
      return;
    }
    setLoading(true);
    try {
      await register({
        name: form.name,
        email: form.email,
        password: form.password,
        company_name: form.company_name || undefined,
      });
      navigate("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("register.failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-blue-400 text-2xl font-bold tracking-tight mb-1">{t("register.brand")}</div>
          <p className="text-gray-500 text-sm">{t("register.subtitle")}</p>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-lg p-8">
          <h1 className="text-lg font-semibold text-white mb-6">{t("register.title")}</h1>

          {error && (
            <div className="mb-4 p-3 bg-red-900/40 border border-red-700 rounded-md text-red-300 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1.5">{t("register.name")}</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setField("name", e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Jane Smith"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1.5">{t("register.email")}</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setField("email", e.target.value)}
                required
                autoComplete="email"
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1.5">{t("register.company")}</label>
              <input
                type="text"
                value={form.company_name}
                onChange={(e) => setField("company_name", e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Acme Corp"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1.5">{t("register.password")}</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => setField("password", e.target.value)}
                required
                autoComplete="new-password"
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Min. 8 characters"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1.5">{t("register.confirm")}</label>
              <input
                type="password"
                value={form.confirm}
                onChange={(e) => setField("confirm", e.target.value)}
                required
                autoComplete="new-password"
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="••••••••"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium py-2.5 rounded-md transition-colors"
            >
              {loading ? t("register.submitting") : t("register.submit")}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-gray-500">
            {t("register.hasAccount")}{" "}
            <Link to="/login" className="text-blue-400 hover:text-blue-300">
              {t("register.signin")}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
