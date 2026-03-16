import type { PropsWithChildren, ReactNode } from "react";

type Props = PropsWithChildren<{
  title: string;
  subtitle?: string;
  aside?: ReactNode;
}>;

export function SectionCard({ title, subtitle, aside, children }: Props) {
  return (
    <section className="rounded-[28px] border border-white/10 bg-slate-900/80 p-5 shadow-xl shadow-slate-950/15">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-white md:text-2xl">{title}</h2>
          {subtitle ? <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">{subtitle}</p> : null}
        </div>
        {aside}
      </div>
      <div className="mt-6">{children}</div>
    </section>
  );
}
