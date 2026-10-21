import { formatPrice, formatStorage } from "../format";
import type { ChatProduct } from "../types";

interface Props {
  product: ChatProduct;
  selected: boolean;
  compareFull: boolean;
  onToggleCompare: (product: ChatProduct) => void;
}

export default function ChatProductCard({ product: p, selected, compareFull, onToggleCompare }: Props) {
  const disabled = !selected && compareFull;
  return (
    <article className={`flex flex-col rounded-card border bg-white p-3 ${selected ? "border-petrol" : "border-line"}`}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold leading-snug">
          <span className="block text-xs font-normal text-ink/60">{p.brand}</span>
          {p.name}
        </h3>
        <span className="whitespace-nowrap text-sm font-bold">{formatPrice(p.price)}</span>
      </div>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs text-ink/80">
        <dt className="text-ink/50">CPU</dt>
        <dd>{p.cpu}</dd>
        <dt className="text-ink/50">GPU</dt>
        <dd>{p.gpu}</dd>
        <dt className="text-ink/50">Memory</dt>
        <dd>
          {p.ram_gb} GB RAM · {formatStorage(p.storage_gb)} {p.storage_type}
        </dd>
        <dt className="text-ink/50">Weight</dt>
        <dd>
          {p.weight_kg} kg · {p.os}
        </dd>
      </dl>
      <div className="mt-auto flex items-center justify-between gap-2 pt-3">
        {p.is_mock && <span className="rounded bg-amber-tint px-1.5 py-0.5 text-xs font-semibold text-amber-ink">Mock</span>}
        <button
          type="button"
          className={`${selected ? "btn-primary" : "btn-quiet"} ml-auto px-3 py-1.5 text-xs`}
          aria-pressed={selected}
          disabled={disabled}
          title={disabled ? "You can compare up to 3 laptops" : undefined}
          onClick={() => onToggleCompare(p)}
        >
          {selected ? "✓ In compare" : "Add to compare"}
        </button>
      </div>
    </article>
  );
}
