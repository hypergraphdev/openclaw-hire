import { formatStateLabel, statusTone } from "../lib/formatters";

type Props = {
  state: string;
};

export function StatusPill({ state }: Props) {
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${statusTone(state)}`}>
      {formatStateLabel(state)}
    </span>
  );
}
