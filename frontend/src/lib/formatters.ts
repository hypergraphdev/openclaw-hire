export function formatStateLabel(state: string) {
  return state
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function statusTone(state: string) {
  if (state === "ready") {
    return "bg-emerald-500/15 text-emerald-200 ring-1 ring-inset ring-emerald-400/30";
  }
  if (state === "failed") {
    return "bg-rose-500/15 text-rose-200 ring-1 ring-inset ring-rose-400/30";
  }
  if (state === "waiting_bot_token") {
    return "bg-amber-400/15 text-amber-100 ring-1 ring-inset ring-amber-300/30";
  }
  return "bg-sky-400/15 text-sky-100 ring-1 ring-inset ring-sky-300/25";
}
