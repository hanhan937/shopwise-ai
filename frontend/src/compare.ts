import type { Product } from "./types";

/** Product comparison helpers (Module 2C-1). No React, so the rules stay easy to reason about. */

export const MAX_COMPARE = 3;
export const MIN_COMPARE = 2;

/**
 * Add the product if it isn't selected yet, remove it if it is.
 * Adding beyond MAX_COMPARE is a no-op, so callers can pass the click straight through.
 */
export function toggleSelection(selected: Product[], product: Product): Product[] {
  if (selected.some((p) => p.id === product.id)) return selected.filter((p) => p.id !== product.id);
  if (selected.length >= MAX_COMPARE) return selected;
  return [...selected, product];
}

export type HighlightKey = "price" | "weight" | "ram" | "storage";

export const HIGHLIGHT_LABELS: Record<HighlightKey, string> = {
  price: "Lowest price",
  weight: "Lightest",
  ram: "Most RAM",
  storage: "Most storage",
};

const RULES: Record<HighlightKey, { value: (p: Product) => number; best: "min" | "max" }> = {
  price: { value: (p) => p.price, best: "min" },
  weight: { value: (p) => p.weight_kg, best: "min" },
  ram: { value: (p) => p.ram_gb, best: "max" },
  storage: { value: (p) => p.storage_gb, best: "max" },
};

/**
 * For each highlighted spec, the ids of the products holding the best value. Ties highlight every
 * tied product; when all products share the same value nothing is highlighted, since nobody "wins".
 */
export function computeHighlights(products: Product[]): Record<HighlightKey, Set<number>> {
  const result = {} as Record<HighlightKey, Set<number>>;
  for (const key of Object.keys(RULES) as HighlightKey[]) {
    const { value, best } = RULES[key];
    const values = products.map(value);
    const target = best === "min" ? Math.min(...values) : Math.max(...values);
    const allEqual = values.every((v) => v === values[0]);
    result[key] = new Set(products.length < 2 || allEqual ? [] : products.filter((p) => value(p) === target).map((p) => p.id));
  }
  return result;
}

/** Identity of a selection; when it changes, any earlier AI analysis is stale. */
export function selectionKey(products: Product[]): string {
  return products.map((p) => p.id).join(",");
}

/** True only when an analysis was made for exactly these products, in this order. */
export function analysisMatches(analysis: { product_ids: number[] } | null, products: Product[]): boolean {
  return analysis !== null && analysis.product_ids.join(",") === selectionKey(products);
}
