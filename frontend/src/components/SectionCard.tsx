import type { PropsWithChildren, ReactNode } from "react";

type Props = PropsWithChildren<{
  title: string;
  subtitle?: string;
  aside?: ReactNode;
}>;

export function SectionCard({ title, subtitle, aside, children }: Props) {
  return (
    <section className="rounded-[28px] border border-ink/10 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl text-ink">{title}</h2>
          {subtitle ? <p className="mt-1 text-sm text-ink/70">{subtitle}</p> : null}
        </div>
        {aside}
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}
