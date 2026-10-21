import type { ReactNode } from "react";
import { HIGHLIGHT_LABELS, computeHighlights, selectionKey, type HighlightKey } from "../compare";
import { formatPrice, formatStorage } from "../format";
import type { Product } from "../types";
import AIComparison from "./AIComparison";

interface Props {
  products: Product[];
  onRemove: (id: number) => void;
  onClose: () => void;
}

const ROWS: Array<{ label: string; render: (p: Product) => ReactNode; highlight?: HighlightKey }> = [
  { label: "Price", render: (p) => formatPrice(p.price), highlight: "price" },
  { label: "CPU", render: (p) => p.cpu },
  { label: "GPU", render: (p) => p.gpu },
  { label: "RAM", render: (p) => `${p.ram_gb} GB`, highlight: "ram" },
  { label: "Storage", render: (p) => `${formatStorage(p.storage_gb)} ${p.storage_type}`, highlight: "storage" },
  { label: "Weight", render: (p) => `${p.weight_kg} kg`, highlight: "weight" },
  { label: "OS", render: (p) => p.os },
];

export default function ComparisonTable({ products, onRemove, onClose }: Props) {
  const highlights = computeHighlights(products);

  return (
    <section aria-labelledby="compare-heading" className="mt-4 rounded-card border border-line bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="compare-heading" className="text-xl font-bold">
          Side-by-side comparison
        </h2>
        <button type="button" className="btn-quiet" onClick={onClose}>
          Hide comparison
        </button>
      </div>
      <p className="mt-1 text-xs text-amber-ink">Mock data: specs and prices are synthetic and for demonstration only.</p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[560px] table-fixed text-left text-sm">
          <caption className="sr-only">Comparison of selected laptops</caption>
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className="w-28 px-3 py-2 font-semibold text-ink/70">
                Spec
              </th>
              {products.map((p) => (
                <th key={p.id} scope="col" className="px-3 py-2 align-top font-medium">
                  <span className="block text-xs font-normal text-ink/60">{p.brand}</span>
                  {p.name}
                  {p.is_mock && <span className="ml-1.5 rounded bg-amber-tint px-1.5 py-0.5 text-xs font-semibold text-amber-ink">Mock</span>}
                  <button
                    type="button"
                    className="mt-1 block text-xs font-normal text-ink/60 underline hover:text-danger"
                    onClick={() => onRemove(p.id)}
                  >
                    Remove
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {ROWS.map((row) => (
              <tr key={row.label}>
                <th scope="row" className="px-3 py-2.5 font-semibold text-ink/70">
                  {row.label}
                </th>
                {products.map((p) => {
                  const best = row.highlight !== undefined && highlights[row.highlight].has(p.id);
                  return (
                    <td key={p.id} className={`px-3 py-2.5 ${best ? "bg-petrol-tint font-semibold text-petrol-dark" : ""}`}>
                      {row.render(p)}
                      {best && row.highlight && (
                        <span className="ml-1.5 whitespace-nowrap rounded bg-petrol px-1.5 py-0.5 text-xs font-semibold text-white">
                          {HIGHLIGHT_LABELS[row.highlight]}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Keyed by the selection: adding/removing a laptop discards any earlier analysis. */}
      <AIComparison key={selectionKey(products)} products={products} />
    </section>
  );
}
