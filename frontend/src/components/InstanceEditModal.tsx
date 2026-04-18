import { useEffect, useRef, useState } from "react";
import { api } from "../api";

interface Props {
  instanceId: string;
  currentName: string;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Edit an instance's display name and avatar.
 *
 * NOTE: the HXA org agent_name is deliberately NOT editable here — it's
 * a one-shot operation that propagates to other users' chat views and
 * lives on a dedicated, warn-before-you-save form elsewhere.
 */
export function InstanceEditModal({ instanceId, currentName, onClose, onSaved }: Props) {
  const [name, setName] = useState(currentName);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(true);
  const [pendingAvatar, setPendingAvatar] = useState<{ file: File; preview: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    setAvatarLoading(true);
    api.getAvatar(instanceId)
      .then((r) => setAvatarUrl(r.avatar_url))
      .catch(() => setAvatarUrl(null))
      .finally(() => setAvatarLoading(false));
  }, [instanceId]);

  useEffect(() => {
    return () => {
      if (pendingAvatar) URL.revokeObjectURL(pendingAvatar.preview);
    };
  }, [pendingAvatar]);

  function onPickAvatar(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      setError("仅支持图片");
      return;
    }
    if (f.size > 2 * 1024 * 1024) {
      setError("图片不能超过 2MB");
      return;
    }
    setError("");
    if (pendingAvatar) URL.revokeObjectURL(pendingAvatar.preview);
    setPendingAvatar({ file: f, preview: URL.createObjectURL(f) });
  }

  async function handleRemoveAvatar() {
    if (!confirm("确定移除头像？")) return;
    setSaving(true);
    setError("");
    try {
      await api.deleteAvatar(instanceId);
      setAvatarUrl(null);
      setPendingAvatar(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "移除失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const tasks: Promise<unknown>[] = [];
      const trimmed = name.trim();
      if (trimmed && trimmed !== currentName) {
        tasks.push(api.renameInstance(instanceId, trimmed));
      }
      if (pendingAvatar) {
        tasks.push(api.uploadAvatar(instanceId, pendingAvatar.file));
      }
      if (tasks.length === 0) {
        onClose();
        return;
      }
      await Promise.all(tasks);
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "保存失败");
    } finally {
      setSaving(false);
    }
  }

  // Whichever image to show in the preview slot: pending upload > stored > placeholder
  const previewSrc = pendingAvatar?.preview || avatarUrl || "";

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
              <div className="h-16 w-16 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center text-gray-500 text-xs overflow-hidden">
                {avatarLoading ? (
                  <span>…</span>
                ) : previewSrc ? (
                  <img src={previewSrc} alt="avatar" className="h-full w-full object-cover" />
                ) : (
                  <span>N/A</span>
                )}
              </div>
              <div className="flex flex-col gap-2">
                <input
                  type="file"
                  ref={fileInputRef}
                  accept="image/jpeg,image/png,image/gif,image/webp"
                  onChange={onPickAvatar}
                  className="hidden"
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={saving}
                    className="px-3 py-1 text-xs rounded bg-gray-800 hover:bg-gray-700 text-gray-200 disabled:opacity-50"
                  >
                    {pendingAvatar ? "换一张" : "选择图片"}
                  </button>
                  {(avatarUrl || pendingAvatar) && (
                    <button
                      onClick={() => {
                        if (pendingAvatar) {
                          URL.revokeObjectURL(pendingAvatar.preview);
                          setPendingAvatar(null);
                        } else {
                          void handleRemoveAvatar();
                        }
                      }}
                      disabled={saving}
                      className="px-3 py-1 text-xs rounded bg-gray-800 hover:bg-red-900/60 text-gray-200 disabled:opacity-50"
                    >
                      {pendingAvatar ? "取消选择" : "移除头像"}
                    </button>
                  )}
                </div>
                <div className="text-xs text-gray-500">
                  JPG / PNG / GIF / WebP · 最大 2MB
                </div>
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
