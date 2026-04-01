/**
 * ThreadTaskPanel — Thread 质量控制面板
 *
 * 包含：QC 开关、任务列表、任务创建弹窗、质量评估
 * 作为独立组件嵌入 MyOrgPage 的 Thread 视图中
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { QCConfig, ThreadTask, TaskDepth } from "../types";

// ── 状态颜色映射 ──
const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-600",
  in_progress: "bg-blue-600",
  review: "bg-yellow-600",
  revision: "bg-orange-600",
  completed: "bg-green-600",
  failed: "bg-red-600",
};

function scoreColor(score: number | null): string {
  if (score === null) return "text-gray-500";
  if (score >= 0.8) return "text-green-400";
  if (score >= 0.6) return "text-yellow-400";
  return "text-red-400";
}

// ── Task Create Modal ──
function TaskCreateModal({ threadId, orgId, participants, onClose, onCreated }: {
  threadId: string;
  orgId: string;
  participants: { name?: string }[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [criteriaText, setCriteriaText] = useState("");
  const [depth, setDepth] = useState<TaskDepth>("thorough");
  const [assignTo, setAssignTo] = useState("");
  const [sendMessage, setSendMessage] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!title.trim()) return;
    setSubmitting(true);
    const criteria = criteriaText.split("\n").map(l => l.trim()).filter(Boolean);
    try {
      if (sendMessage) {
        // Send as task message to thread
        await api.myOrgThreadSendAsTask(threadId, description || title, {
          title, description, acceptance_criteria: criteria, depth, assigned_to: assignTo || undefined,
        }, orgId);
      } else {
        // Just create task record
        await api.myOrgThreadTaskCreate(threadId, {
          title, description, acceptance_criteria: criteria, depth, assigned_to: assignTo || undefined,
        }, orgId);
      }
      onCreated();
      onClose();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-gray-800 rounded-lg p-5 w-[460px] max-h-[80vh] overflow-auto border border-gray-700" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-medium text-gray-100 mb-3">{t("qc.createTask")}</h3>

        <label className="text-xs text-gray-400 block mb-1">{t("qc.taskTitle")}</label>
        <input value={title} onChange={e => setTitle(e.target.value)}
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 mb-3 focus:outline-none focus:border-blue-500" />

        <label className="text-xs text-gray-400 block mb-1">{t("qc.taskDesc")}</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)} rows={3}
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 mb-3 resize-none focus:outline-none focus:border-blue-500" />

        <label className="text-xs text-gray-400 block mb-1">{t("qc.acceptanceCriteria")} <span className="text-gray-600">({t("qc.acceptanceCriteriaHint")})</span></label>
        <textarea value={criteriaText} onChange={e => setCriteriaText(e.target.value)} rows={3}
          placeholder={"完整分析所有可能的原因\n给出具体的解决方案\n包含测试验证步骤"}
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 mb-3 resize-none focus:outline-none focus:border-blue-500" />

        <div className="flex gap-3 mb-3">
          <div className="flex-1">
            <label className="text-xs text-gray-400 block mb-1">{t("qc.depth")}</label>
            <select value={depth} onChange={e => setDepth(e.target.value as TaskDepth)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-blue-500">
              <option value="shallow">{t("qc.depth.shallow")}</option>
              <option value="moderate">{t("qc.depth.moderate")}</option>
              <option value="thorough">{t("qc.depth.thorough")}</option>
              <option value="exhaustive">{t("qc.depth.exhaustive")}</option>
            </select>
          </div>
          <div className="flex-1">
            <label className="text-xs text-gray-400 block mb-1">{t("qc.assignTo")}</label>
            <select value={assignTo} onChange={e => setAssignTo(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-blue-500">
              <option value="">-- {t("qc.assignTo")} --</option>
              {participants.map(p => p.name && <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </div>
        </div>

        <label className="flex items-center gap-2 text-xs text-gray-400 mb-4 cursor-pointer">
          <input type="checkbox" checked={sendMessage} onChange={e => setSendMessage(e.target.checked)}
            className="rounded bg-gray-900 border-gray-700" />
          {t("qc.sendAsTask")}
        </label>

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="text-xs text-gray-500 px-3 py-1.5">{t("common.cancel")}</button>
          <button onClick={handleSubmit} disabled={submitting || !title.trim()}
            className="text-xs bg-blue-600 text-white px-4 py-1.5 rounded disabled:opacity-50">
            {submitting ? t("common.loading") : t("qc.createTask")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Evaluate Modal ──
function EvaluateModal({ threadId, task, orgId, onClose, onDone }: {
  threadId: string;
  task: ThreadTask;
  orgId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const [responseContent, setResponseContent] = useState("");
  const [evaluating, setEvaluating] = useState(false);
  const [result, setResult] = useState<{ evaluation: { overall_score: number; verdict: string; feedback: string; dimensions: Record<string, number>; unmet_criteria: string[]; strengths: string[] }; revision_sent: boolean } | null>(null);

  async function handleEvaluate() {
    if (!responseContent.trim()) return;
    setEvaluating(true);
    try {
      const r = await api.myOrgThreadTaskEvaluate(threadId, task.id, responseContent, orgId);
      setResult(r);
      onDone();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Evaluation failed");
    } finally {
      setEvaluating(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-gray-800 rounded-lg p-5 w-[520px] max-h-[80vh] overflow-auto border border-gray-700" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-medium text-gray-100 mb-1">{t("qc.evaluate")}: {task.title}</h3>
        <p className="text-xs text-gray-500 mb-3">Task ID: {task.id}</p>

        {!result ? (
          <>
            <label className="text-xs text-gray-400 block mb-1">Bot 的回复内容</label>
            <textarea value={responseContent} onChange={e => setResponseContent(e.target.value)} rows={8}
              placeholder="粘贴 Bot 的回复内容到这里..."
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-xs text-gray-100 mb-3 resize-none focus:outline-none focus:border-blue-500 font-mono" />
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="text-xs text-gray-500 px-3 py-1.5">{t("common.cancel")}</button>
              <button onClick={handleEvaluate} disabled={evaluating || !responseContent.trim()}
                className="text-xs bg-purple-600 text-white px-4 py-1.5 rounded disabled:opacity-50">
                {evaluating ? "评估中..." : t("qc.evaluate")}
              </button>
            </div>
          </>
        ) : (
          <>
            {/* Score */}
            <div className="flex items-center gap-3 mb-3">
              <span className={`text-2xl font-bold ${scoreColor(result.evaluation.overall_score)}`}>
                {(result.evaluation.overall_score * 100).toFixed(0)}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded ${
                result.evaluation.verdict === "PASS" ? "bg-green-900/50 text-green-400" :
                result.evaluation.verdict === "REVISE" ? "bg-yellow-900/50 text-yellow-400" :
                "bg-red-900/50 text-red-400"
              }`}>
                {t(`qc.verdict.${result.evaluation.verdict}`)}
              </span>
              {result.revision_sent && <span className="text-xs text-orange-400">已自动发送修改请求</span>}
            </div>

            {/* Dimensions */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              {Object.entries(result.evaluation.dimensions).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2">
                  <span className="text-xs text-gray-500 w-20">{k}</span>
                  <div className="flex-1 bg-gray-900 rounded-full h-1.5">
                    <div className={`h-1.5 rounded-full ${v >= 0.7 ? "bg-green-500" : v >= 0.4 ? "bg-yellow-500" : "bg-red-500"}`}
                      style={{ width: `${v * 100}%` }} />
                  </div>
                  <span className="text-xs text-gray-400 w-8">{(v * 100).toFixed(0)}</span>
                </div>
              ))}
            </div>

            {/* Feedback */}
            <div className="bg-gray-900 rounded p-3 mb-3">
              <p className="text-xs text-gray-300">{result.evaluation.feedback}</p>
            </div>

            {result.evaluation.unmet_criteria.length > 0 && (
              <div className="mb-3">
                <p className="text-xs text-red-400 mb-1">未满足的标准：</p>
                <ul className="text-xs text-gray-400 list-disc pl-4">
                  {result.evaluation.unmet_criteria.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}

            <div className="flex justify-end">
              <button onClick={onClose} className="text-xs bg-gray-700 text-gray-300 px-4 py-1.5 rounded">{t("common.close")}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── QC Config Modal ──
function QCConfigModal({ threadId, orgId, currentConfig, onClose, onSaved }: {
  threadId: string;
  orgId: string;
  currentConfig: QCConfig | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const [minScore, setMinScore] = useState(currentConfig?.min_quality_score ?? 0.6);
  const [autoRev, setAutoRev] = useState(currentConfig?.auto_revision ?? true);
  const [maxRev, setMaxRev] = useState(currentConfig?.max_revisions ?? 2);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await api.myOrgThreadQCEnable(threadId, {
        min_quality_score: minScore,
        auto_revision: autoRev,
        max_revisions: maxRev,
        ...(apiKey ? { evaluator_api_key: apiKey } : {}),
      }, orgId);
      onSaved();
      onClose();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDisable() {
    try {
      await api.myOrgThreadQCDisable(threadId);
      onSaved();
      onClose();
    } catch { /* */ }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-gray-800 rounded-lg p-5 w-[380px] border border-gray-700" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-medium text-gray-100 mb-3">{t("qc.title")}</h3>

        <label className="text-xs text-gray-400 block mb-1">{t("qc.minScore")}</label>
        <input type="number" value={minScore} onChange={e => setMinScore(Number(e.target.value))} step={0.1} min={0} max={1}
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 mb-3 focus:outline-none focus:border-blue-500" />

        <label className="flex items-center gap-2 text-xs text-gray-400 mb-3 cursor-pointer">
          <input type="checkbox" checked={autoRev} onChange={e => setAutoRev(e.target.checked)} className="rounded bg-gray-900 border-gray-700" />
          {t("qc.autoRevision")}
        </label>

        <label className="text-xs text-gray-400 block mb-1">{t("qc.maxRevisions")}</label>
        <input type="number" value={maxRev} onChange={e => setMaxRev(Number(e.target.value))} min={0} max={5}
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 mb-3 focus:outline-none focus:border-blue-500" />

        <label className="text-xs text-gray-400 block mb-1">{t("qc.apiKey")} <span className="text-gray-600">({currentConfig?.has_api_key ? "已配置" : "未配置"})</span></label>
        <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-ant-..."
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 mb-4 focus:outline-none focus:border-blue-500" />

        <div className="flex justify-between">
          {currentConfig?.enabled && (
            <button onClick={handleDisable} className="text-xs text-red-400 hover:text-red-300">{t("qc.disable")}</button>
          )}
          <div className="flex gap-2 ml-auto">
            <button onClick={onClose} className="text-xs text-gray-500 px-3 py-1.5">{t("common.cancel")}</button>
            <button onClick={handleSave} disabled={saving}
              className="text-xs bg-blue-600 text-white px-4 py-1.5 rounded disabled:opacity-50">
              {saving ? t("common.loading") : t("common.save")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Panel ──
export default function ThreadTaskPanel({ threadId, orgId, participants }: {
  threadId: string;
  orgId: string;
  participants: { bot_id: string; name?: string; online: boolean }[];
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [qcConfig, setQcConfig] = useState<QCConfig | null>(null);
  const [tasks, setTasks] = useState<ThreadTask[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [showQCConfig, setShowQCConfig] = useState(false);
  const [evalTask, setEvalTask] = useState<ThreadTask | null>(null);

  const loadQC = useCallback(async () => {
    try {
      const c = await api.myOrgThreadQCGet(threadId);
      setQcConfig(c);
    } catch { /* */ }
  }, [threadId]);

  const loadTasks = useCallback(async () => {
    try {
      const r = await api.myOrgThreadTasks(threadId);
      setTasks(r.tasks);
    } catch { /* */ }
  }, [threadId]);

  useEffect(() => { loadQC(); loadTasks(); }, [loadQC, loadTasks]);

  const activeCount = tasks.filter(t => !["completed", "failed"].includes(t.status)).length;

  return (
    <>
      {/* Toggle bar */}
      <div className="border-b border-gray-800 px-4 py-1.5 flex items-center gap-2 cursor-pointer select-none hover:bg-gray-800/50"
        onClick={() => setExpanded(!expanded)}>
        <span className="text-xs text-gray-400">{expanded ? "▼" : "▶"}</span>
        <span className="text-xs text-gray-300 font-medium">{t("qc.tasks")}</span>
        {activeCount > 0 && <span className="text-[10px] bg-blue-600 text-white px-1.5 rounded-full">{activeCount}</span>}
        {qcConfig?.enabled && <span className="text-[10px] text-green-400 ml-auto">QC {t("qc.enabled")}</span>}
        <button onClick={e => { e.stopPropagation(); setShowQCConfig(true); }}
          className="text-gray-500 hover:text-gray-300 text-xs ml-1" title={t("qc.title")}>
          ⚙
        </button>
      </div>

      {expanded && (
        <div className="border-b border-gray-800 bg-gray-900/30 px-4 py-2 max-h-48 overflow-auto">
          {tasks.length === 0 ? (
            <p className="text-xs text-gray-600 text-center py-2">{t("qc.noTasks")}</p>
          ) : (
            <div className="space-y-1.5">
              {tasks.map(task => (
                <div key={task.id} className="flex items-center gap-2 text-xs group">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${STATUS_COLORS[task.status] || "bg-gray-600"}`} />
                  <span className="text-gray-300 truncate flex-1" title={task.title}>{task.title}</span>
                  {task.assigned_to && <span className="text-gray-600 text-[10px]">@{task.assigned_to}</span>}
                  {task.quality_score !== null && (
                    <span className={`text-[10px] font-mono ${scoreColor(task.quality_score)}`}>
                      {(task.quality_score * 100).toFixed(0)}
                    </span>
                  )}
                  <span className="text-[10px] text-gray-600">{t(`qc.status.${task.status}`)}</span>
                  {qcConfig?.enabled && task.status !== "completed" && (
                    <button onClick={() => setEvalTask(task)}
                      className="text-[10px] text-purple-400 hover:text-purple-300 opacity-0 group-hover:opacity-100 transition-opacity">
                      {t("qc.evaluate")}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          <button onClick={() => setShowCreate(true)}
            className="mt-2 text-xs text-blue-400 hover:text-blue-300 w-full text-center py-1 border border-dashed border-gray-700 rounded">
            + {t("qc.createTask")}
          </button>
        </div>
      )}

      {/* Modals */}
      {showCreate && (
        <TaskCreateModal threadId={threadId} orgId={orgId}
          participants={participants}
          onClose={() => setShowCreate(false)}
          onCreated={loadTasks} />
      )}
      {showQCConfig && (
        <QCConfigModal threadId={threadId} orgId={orgId}
          currentConfig={qcConfig}
          onClose={() => setShowQCConfig(false)}
          onSaved={loadQC} />
      )}
      {evalTask && (
        <EvaluateModal threadId={threadId} task={evalTask} orgId={orgId}
          onClose={() => setEvalTask(null)}
          onDone={() => { loadTasks(); setEvalTask(null); }} />
      )}
    </>
  );
}
