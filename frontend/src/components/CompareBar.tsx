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
    // Fixed to the bottom of the screen so it stays visible wherever laptops are added (table or chat).
    <section
      aria-label="Laptops selected for comparison"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-petrol/40 bg-petrol-tint/95 shadow-[0_-4px_12px_rgba(20,33,43,0.08)] backdrop-blur"
    >
      <div className="mx-auto max-w-5xl px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2 sm:gap-3">
        <p className="text-sm font-semibold">
          Compare ({selected.length}/{MAX_COMPARE})
          <span className="ml-2 hidden font-normal text-ink/70 sm:inline">
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
      <ul className="mt-2 flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible sm:pb-0">
        {selected.map((p) => (
          <li key={p.id} className="flex shrink-0 items-center gap-1 rounded-md border border-line bg-white py-1 pl-2.5 pr-1 text-sm">
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
      </div>
    </section>
  );
}
