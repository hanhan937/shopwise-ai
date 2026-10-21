import { MAX_COMPARE, MIN_COMPARE } from "../compare";
import type { Product } from "../types";

interface Props {
  selected: Product[];
  onRemove: (id: number) => void;
  onClear: () => void;
  onCompare: () => void;
}

export default function CompareBar({ selected, onRemove, onClear, onCompare }: Props) {
  if (selected.length === 0) return null;
  const needed = MIN_COMPARE - selected.length;

  return (
    <section aria-label="Laptops selected for comparison" className="mt-4 rounded-card border border-petrol/40 bg-petrol-tint p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-semibold">
          Compare ({selected.length}/{MAX_COMPARE})
          <span className="ml-2 font-normal text-ink/70">
            {needed > 0
              ? `Select ${needed} more to compare.`
              : selected.length >= MAX_COMPARE
                ? "Maximum reached."
                : "Selections are kept when you change pages."}
          </span>
        </p>
        <div className="flex gap-2">
          <button type="button" className="btn-quiet" onClick={onClear}>
            Clear all
          </button>
          <button type="button" className="btn-primary" disabled={selected.length < MIN_COMPARE} onClick={onCompare}>
            Compare
          </button>
        </div>
      </div>
      <ul className="mt-2 flex flex-wrap gap-2">
        {selected.map((p) => (
          <li key={p.id} className="flex items-center gap-1 rounded-md border border-line bg-white py-1 pl-2.5 pr-1 text-sm">
            <span>
              <span className="text-ink/60">{p.brand}</span> {p.name}
            </span>
            <button
              type="button"
              className="rounded px-1.5 text-ink/60 hover:bg-paper hover:text-danger"
              aria-label={`Remove ${p.brand} ${p.name} from comparison`}
              onClick={() => onRemove(p.id)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
