import { DEMO_MODE } from "../demo/mode";
import type { Health } from "../types";

interface Props {
  health: Health | null;
  offline: boolean;
}

export default function HealthBadge({ health, offline }: Props) {
  let text = "Checking API…";
  let tone = "border-line text-ink/60";

  if (DEMO_MODE) {
    text = "Demo mode · static data";
    tone = "border-amber-ink/30 bg-amber-tint text-amber-ink";
  } else if (offline) {
    text = "API offline";
    tone = "border-danger/30 bg-danger-tint text-danger";
  } else if (health && health.status === "ok") {
    text = `API ok · ${health.products_total} products · pgvector on`;
    tone = "border-petrol/30 bg-petrol-tint text-petrol-dark";
  } else if (health) {
    text = !health.database ? "Database unreachable" : "pgvector extension missing";
    tone = "border-amber-ink/30 bg-amber-tint text-amber-ink";
  }

  return (
    <span role="status" className={`rounded-full border px-2.5 py-1 text-xs font-medium ${tone}`}>
      {text}
    </span>
  );
}
