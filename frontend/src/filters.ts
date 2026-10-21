/** Filter form state, validation, and conversion to API query params (no React, no DOM). */

/** Raw form values. Empty string = "not set". */
export interface FilterValues {
  q: string;
  minPrice: string;
  maxPrice: string;
  minRamGb: string;
}

/** Typed values sent to the API; undefined fields are omitted from the URL. */
export interface ProductQuery {
  q?: string;
  minPrice?: number;
  maxPrice?: number;
  minRamGb?: number;
}

export type FilterErrors = Partial<Record<keyof FilterValues, string>>;

export const EMPTY_FILTERS: FilterValues = { q: "", minPrice: "", maxPrice: "", minRamGb: "" };

// Keep these in sync with the backend limits (backend/app/product_filters.py and routers/products.py).
export const MAX_QUERY_LENGTH = 100;
export const MAX_WORDS = 8;
export const MAX_PRICE = 1_000_000;
export const RAM_OPTIONS = [8, 16, 32, 64];

/** undefined = blank, null = not a valid non-negative number, number = ok. */
function parsePrice(raw: string): number | null | undefined {
  const text = raw.trim();
  if (text === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

export function validateFilters(values: FilterValues): FilterErrors {
  const errors: FilterErrors = {};
  const q = values.q.trim();

  if (q.length > MAX_QUERY_LENGTH) errors.q = `Use ${MAX_QUERY_LENGTH} characters or fewer.`;
  else if (q.split(/\s+/).filter(Boolean).length > MAX_WORDS) errors.q = `Use ${MAX_WORDS} words or fewer.`;

  const min = parsePrice(values.minPrice);
  const max = parsePrice(values.maxPrice);
  if (min === null) errors.minPrice = "Enter a price of 0 or more.";
  else if (min !== undefined && min > MAX_PRICE) errors.minPrice = "That price is too high.";
  if (max === null) errors.maxPrice = "Enter a price of 0 or more.";
  else if (max !== undefined && max > MAX_PRICE) errors.maxPrice = "That price is too high.";
  if (typeof min === "number" && typeof max === "number" && min <= MAX_PRICE && max <= MAX_PRICE && min > max) {
    errors.maxPrice = "Max price must be at least the min price.";
  }

  const ram = values.minRamGb.trim();
  if (ram !== "" && !(Number.isInteger(Number(ram)) && Number(ram) >= 1)) errors.minRamGb = "Choose a RAM amount from the list.";

  return errors;
}

/** Convert (already validated) form values to API params. Blank fields are dropped. */
export function toQuery(values: FilterValues): ProductQuery {
  const query: ProductQuery = {};
  const q = values.q.trim();
  if (q) query.q = q;
  const min = parsePrice(values.minPrice);
  const max = parsePrice(values.maxPrice);
  if (typeof min === "number") query.minPrice = min;
  if (typeof max === "number") query.maxPrice = max;
  if (values.minRamGb.trim() !== "") query.minRamGb = Number(values.minRamGb);
  return query;
}

export function hasActiveFilters(values: FilterValues): boolean {
  return Object.keys(toQuery(values)).length > 0;
}
