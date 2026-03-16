import type { PropsWithChildren } from "react";

export function PhoneFrame({ children }: PropsWithChildren) {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 md:px-8">
      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="rounded-[32px] border border-white/70 bg-ink px-6 py-8 text-sand shadow-panel">
          <p className="font-display text-xs uppercase tracking-[0.4em] text-sand/70">OpenClaw Hire</p>
          <h1 className="mt-4 font-display text-4xl leading-tight">Build agent employees with a visible bootstrap path.</h1>
          <p className="mt-4 text-sm leading-6 text-sand/80">
            First scaffold for Michael Wu&apos;s hiring platform. Provisioning is intentionally partial until Telegram
            bot credentials are supplied.
          </p>
          <div className="mt-8 rounded-[24px] bg-white/10 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-sand/60">Default model</p>
            <p className="mt-2 text-sm text-sand">openai-codex/gpt-5.3-codex-spark</p>
          </div>
        </aside>
        <main className="overflow-hidden rounded-[36px] border border-white/70 bg-white/80 shadow-panel backdrop-blur">
          {children}
        </main>
      </div>
    </div>
  );
}
