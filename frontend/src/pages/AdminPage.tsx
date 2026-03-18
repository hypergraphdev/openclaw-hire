import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AdminUserInstances, User } from "../types";

export function AdminPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [detail, setDetail] = useState<AdminUserInstances | null>(null);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .adminUsers()
      .then((rows) => {
        setUsers(rows);
        if (rows.length > 0) setSelectedUserId(rows[0].id);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load users"))
      .finally(() => setLoadingUsers(false));
  }, []);

  useEffect(() => {
    if (!selectedUserId) return;
    setLoadingDetail(true);
    api
      .adminUserInstances(selectedUserId)
      .then(setDetail)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load user instances"))
      .finally(() => setLoadingDetail(false));
  }, [selectedUserId]);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-white">Admin Console</h1>
        <div className="flex gap-3 mt-2">
          <Link to="/admin/settings" className="text-xs text-blue-400 hover:text-blue-300">⚙️ Settings</Link>
          <Link to="/admin/hxa" className="text-xs text-blue-400 hover:text-blue-300">🔗 HXA Orgs</Link>
        </div>
        <p className="text-gray-500 text-sm mt-1">Users and their instances</p>
      </div>

      {error && <div className="mb-4 p-3 text-sm rounded bg-red-900/40 border border-red-700 text-red-300">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-300 mb-3">Users</h2>
          {loadingUsers ? (
            <div className="text-sm text-gray-500">Loading users...</div>
          ) : users.length === 0 ? (
            <div className="text-sm text-gray-500">No users</div>
          ) : (
            <div className="space-y-2 max-h-[520px] overflow-auto pr-1">
              {users.map((u) => (
                <button
                  key={u.id}
                  onClick={() => setSelectedUserId(u.id)}
                  className={`w-full text-left rounded-md border px-3 py-2 transition-colors ${
                    selectedUserId === u.id ? "border-blue-600 bg-blue-600/10" : "border-gray-800 hover:border-gray-700"
                  }`}
                >
                  <div className="text-sm text-white flex items-center gap-2">
                    <span className="truncate">{u.name}</span>
                    {u.is_admin ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-700/50 text-amber-200">admin</span> : null}
                  </div>
                  <div className="text-xs text-gray-500 truncate">{u.email}</div>
                  <div className="text-[11px] text-gray-600 font-mono truncate">{u.id}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-300 mb-3">User Instances</h2>
          {loadingDetail ? (
            <div className="text-sm text-gray-500">Loading instances...</div>
          ) : !detail ? (
            <div className="text-sm text-gray-500">Select a user</div>
          ) : (
            <>
              <div className="mb-3 text-xs text-gray-400">
                <span className="text-gray-500">User:</span> {detail.user.name} · {detail.user.email}
                {detail.user.is_admin ? " · admin" : ""}
              </div>
              {detail.instances.length === 0 ? (
                <div className="text-sm text-gray-500">No instances</div>
              ) : (
                <div className="overflow-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-800">
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">Name</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">Product</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">State</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">Status</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.instances.map((i) => (
                        <tr key={i.id} className="border-b border-gray-800/70">
                          <td className="py-2 pr-3">
                            <div className="text-white">{i.name}</div>
                            <div className="text-[11px] text-gray-600 font-mono">{i.id}</div>
                          </td>
                          <td className="py-2 pr-3 text-gray-300 capitalize">{i.product}</td>
                          <td className="py-2 pr-3 text-gray-300">{i.install_state}</td>
                          <td className="py-2 pr-3 text-gray-300">{i.status}</td>
                          <td className="py-2 pr-3 text-gray-500">{new Date(i.created_at).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
