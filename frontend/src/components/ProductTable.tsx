import { MAX_COMPARE } from "../compare";
import { formatPrice, formatStorage } from "../format";
import type { Product } from "../types";

interface Props {
  products: Product[];
  /** Ids of products picked for comparison (may include products on other pages). */
  selectedIds: Set<number>;
  onToggleCompare: (product: Product) => void;
}

export default function ProductTable({ products, selectedIds, onToggleCompare }: Props) {
  const full = selectedIds.size >= MAX_COMPARE;

  return (
    <div className="overflow-x-auto rounded-card border border-line bg-white">
      <table className="w-full min-w-[720px] text-left text-sm">
        <caption className="sr-only">Laptop catalog</caption>
        <thead className="border-b border-line bg-paper text-ink/70">
          <tr>
            {["Compare", "Laptop", "Price", "CPU", "RAM", "Storage", "Weight", "Source"].map((h) => (
              <th key={h} scope="col" className="px-4 py-2.5 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {products.map((p) => {
            const checked = selectedIds.has(p.id);
            const disabled = !checked && full;
            return (
              <tr key={p.id} className={checked ? "bg-petrol-tint/60" : undefined}>
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-petrol disabled:cursor-not-allowed"
                    checked={checked}
                    disabled={disabled}
                    title={disabled ? `You can compare up to ${MAX_COMPARE} laptops` : undefined}
                    aria-label={`Compare ${p.brand} ${p.name}`}
                    onChange={() => onToggleCompare(p)}
                  />
                </td>
                <th scope="row" className="px-4 py-3 font-medium">
                  <span className="block text-xs font-normal text-ink/60">{p.brand}</span>
                  {p.name}
                </th>
                <td className="px-4 py-3 font-semibold">{formatPrice(p.price)}</td>
                <td className="px-4 py-3">{p.cpu}</td>
                <td className="px-4 py-3">{p.ram_gb} GB</td>
                <td className="px-4 py-3">
                  {formatStorage(p.storage_gb)} {p.storage_type}
                </td>
                <td className="px-4 py-3">{p.weight_kg} kg</td>
                <td className="px-4 py-3 text-xs text-ink/70">
                  {p.source_name}
                  {p.is_mock && <span className="ml-1.5 rounded bg-amber-tint px-1.5 py-0.5 font-semibold text-amber-ink">Mock</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
