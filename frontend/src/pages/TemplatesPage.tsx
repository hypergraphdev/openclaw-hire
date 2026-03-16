import { useEffect, useState } from "react";

import { api } from "../api";
import { SectionCard } from "../components/SectionCard";
import type { TemplateConfig } from "../types";

export function TemplatesPage() {
  const [templates, setTemplates] = useState<TemplateConfig[]>([]);

  useEffect(() => {
    api
      .listTemplates()
      .then(setTemplates)
      .catch(() => {
        setTemplates([]);
      });
  }, []);

  return (
    <div className="grid gap-6 p-6 md:p-8">
      <SectionCard
        title="Templates"
        subtitle="模型模板库：目前默认包含 audit-codex-base 与扩展模板，可用于前端模板选择与后台初始化参数下发。"
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {templates.length > 0 ? (
            templates.map((template) => (
              <div key={template.id} className="rounded-[24px] border border-white/10 bg-slate-950/50 p-5">
                <p className="text-sm uppercase tracking-[0.2em] text-cyan-200/70">{template.id}</p>
                <p className="mt-3 text-lg font-semibold text-white">{template.name}</p>
                <p className="mt-2 text-sm text-slate-300">{template.description}</p>
                <p className="mt-4 text-xs text-slate-500">Runtime: {template.codex_profile}</p>
                <ul className="mt-4 grid gap-2 text-sm text-slate-400">
                  {template.notes.map((note) => (
                    <li key={note} className="list-disc pl-4">
                      {note}
                    </li>
                  ))}
                </ul>
              </div>
            ))
          ) : (
            <div className="rounded-[24px] border border-dashed border-white/10 bg-white/5 p-5 text-sm text-slate-400">模板数据加载中或尚未就绪。</div>
          )}
        </div>
      </SectionCard>
    </div>
  );
}
