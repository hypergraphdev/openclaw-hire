/**
 * SkillsPanel — Displays installed skills/plugins for an instance.
 * Shows a grid of cards; clicking one opens a modal with source code.
 */
import { useEffect, useState } from "react";
import { api } from "../api";
import type { InstanceSkill } from "../types";

const SOURCE_BADGE: Record<string, { label: string; color: string }> = {
  extension: { label: "Extension", color: "bg-blue-600/30 text-blue-300" },
  component: { label: "Component", color: "bg-green-600/30 text-green-300" },
  skill: { label: "Skill", color: "bg-purple-600/30 text-purple-300" },
};

export function SkillsPanel({ instanceId }: { instanceId: string }) {
  const [skills, setSkills] = useState<InstanceSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [selected, setSelected] = useState<InstanceSkill | null>(null);
  const [content, setContent] = useState("");
  const [filename, setFilename] = useState("");
  const [contentLoading, setContentLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.instanceSkills(instanceId)
      .then((res) => setSkills(res.skills))
      .catch(() => setSkills([]))
      .finally(() => setLoading(false));
  }, [instanceId]);

  async function openSkill(skill: InstanceSkill) {
    setSelected(skill);
    setContentLoading(true);
    setContent("");
    setFilename("");
    try {
      const res = await api.instanceSkillContent(instanceId, skill.id);
      setContent(res.content);
      setFilename(res.filename);
    } catch {
      setContent("// Failed to load source code.");
      setFilename("error");
    }
    setContentLoading(false);
  }

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
      {/* Header */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center justify-between w-full text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-300 font-medium">Skills / Plugins</span>
          <span className="text-[10px] text-gray-500">({skills.length})</span>
        </div>
        <span className="text-gray-500 text-xs">{collapsed ? "+" : "-"}</span>
      </button>

      {!collapsed && (
        <div className="mt-3">
          {loading ? (
            <div className="text-center text-gray-600 text-xs py-4">Loading...</div>
          ) : skills.length === 0 ? (
            <div className="text-center text-gray-600 text-xs py-4">No skills installed</div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
              {skills.map((skill) => {
                const badge = SOURCE_BADGE[skill.source] || SOURCE_BADGE.extension;
                return (
                  <button
                    key={skill.id}
                    onClick={() => openSkill(skill)}
                    className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-3 py-2 text-left hover:border-gray-600 transition-colors"
                  >
                    <div className="flex items-start gap-1.5">
                      <span className="text-sm mt-0.5">📦</span>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs text-gray-200 font-medium truncate">{skill.name}</div>
                        {skill.description && (
                          <div className="text-[10px] text-gray-500 truncate mt-0.5">{skill.description}</div>
                        )}
                        <span className={`inline-block text-[9px] px-1.5 py-0.5 rounded mt-1 ${badge.color}`}>
                          {badge.label}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Source code modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={() => setSelected(null)}>
          <div
            className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
              <div>
                <span className="text-sm text-gray-200 font-medium">{selected.name}</span>
                {filename && (
                  <span className="ml-2 text-xs text-gray-500">{filename}</span>
                )}
              </div>
              <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-gray-300 text-lg px-2">
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {contentLoading ? (
                <div className="text-center text-gray-600 text-sm py-8">Loading...</div>
              ) : (
                <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words leading-relaxed">
                  {content}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
