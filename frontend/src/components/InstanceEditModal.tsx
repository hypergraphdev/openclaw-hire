import { useEffect, useState } from "react";
import { api } from "../api";

interface Props {
  instanceId: string;
  currentName: string;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Edit an instance's display name and (eventually) its avatar.
 *
 * NOTE: the HXA org agent_name is deliberately NOT editable here — it's
 * a one-shot operation that propagates to other users' chat views and
 * lives on a dedicated, warn-before-you-save form elsewhere. Avatar is
 * disabled in this build (hxa-connect's Bot model has no avatar field).
 */
export function InstanceEditModal({ instanceId, currentName, onClose, onSaved }: Props) {
  const [name, setName] = useState(currentName);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const trimmed = name.trim();
      if (!trimmed || trimmed === currentName) {
        onClose();
        return;
      }
      await api.renameInstance(instanceId, trimmed);
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">编辑实例</h3>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-xl leading-none"
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        {error && (
          <div className="mb-3 rounded border border-red-700 bg-red-900/30 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="text-xs text-gray-400 block mb-1">实例名称</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={128}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500"
              disabled={saving}
              autoFocus
            />
            <div className="text-xs text-gray-500 mt-1">只在控制台显示，不影响聊天身份。</div>
          </div>

          <div>
            <label className="text-xs text-gray-400 block mb-1">头像</label>
            <div className="flex items-center gap-3">
              <div className="h-12 w-12 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center text-gray-500 text-xs">
                N/A
              </div>
              <div className="text-xs text-gray-500">
                即将支持。目前 HXA 协议尚未包含头像字段。
              </div>
            </div>
          </div>

          <div className="text-xs text-gray-500 border-t border-gray-800 pt-3">
            组织内名称（群聊 @ 你时的名字）不在这里修改 —— 这是对整个组织可见的变更，需要在专用入口完成。
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-sm rounded bg-gray-800 hover:bg-gray-700 text-gray-200 disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
