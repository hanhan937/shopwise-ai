import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  EMPTY_FILTERS,
  MAX_QUERY_LENGTH,
  RAM_OPTIONS,
  hasActiveFilters,
  validateFilters,
  type FilterErrors,
  type FilterValues,
} from "../filters";

interface Props {
  /** Filters currently applied to the table. */
  applied: FilterValues;
  busy: boolean;
  onApply: (values: FilterValues) => void;
  onReset: () => void;
}

const inputClass = (error?: string) =>
  `w-full rounded-md border bg-white px-3 py-2 text-sm placeholder:text-ink/40 ${error ? "border-danger" : "border-line focus-visible:border-petrol"}`;

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">
        {label}
      </label>
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export default function SearchFilters({ applied, busy, onApply, onReset }: Props) {
  const [draft, setDraft] = useState<FilterValues>(applied);
  const [errors, setErrors] = useState<FilterErrors>({});

  // Keep the form in sync when filters change from outside (e.g. "Reset filters" in the empty state).
  useEffect(() => {
    setDraft(applied);
    setErrors({});
  }, [applied]);

  const update = (key: keyof FilterValues) => (value: string) => setDraft((d) => ({ ...d, [key]: value }));
  const aria = (id: string, error?: string) => ({ "aria-invalid": error ? true : undefined, "aria-describedby": error ? `${id}-error` : undefined });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found = validateFilters(draft);
    setErrors(found);
    if (Object.keys(found).length === 0) onApply({ ...draft, q: draft.q.trim() });
  };

  const reset = () => {
    setDraft(EMPTY_FILTERS);
    setErrors({});
    onReset();
  };

  return (
    <form onSubmit={submit} noValidate role="search" aria-label="Search and filter laptops" className="rounded-card border border-line bg-white p-4">
      <div className="grid gap-3 sm:grid-cols-12">
        <div className="sm:col-span-12">
          <Field id="filter-q" label="Search" error={errors.q}>
            <input
              id="filter-q"
              type="search"
              value={draft.q}
              maxLength={MAX_QUERY_LENGTH}
              onChange={(e) => update("q")(e.target.value)}
              placeholder="Brand, model, or specs, e.g. lenovo ryzen"
              autoComplete="off"
              className={inputClass(errors.q)}
              {...aria("filter-q", errors.q)}
            />
          </Field>
        </div>

        <div className="sm:col-span-3">
          <Field id="filter-min-price" label="Min price ($)" error={errors.minPrice}>
            <input
              id="filter-min-price"
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              value={draft.minPrice}
              onChange={(e) => update("minPrice")(e.target.value)}
              placeholder="0"
              className={inputClass(errors.minPrice)}
              {...aria("filter-min-price", errors.minPrice)}
            />
          </Field>
        </div>

        <div className="sm:col-span-3">
          <Field id="filter-max-price" label="Max price ($)" error={errors.maxPrice}>
            <input
              id="filter-max-price"
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              value={draft.maxPrice}
              onChange={(e) => update("maxPrice")(e.target.value)}
              placeholder="Any"
              className={inputClass(errors.maxPrice)}
              {...aria("filter-max-price", errors.maxPrice)}
            />
          </Field>
        </div>

        <div className="sm:col-span-3">
          <Field id="filter-ram" label="Min RAM" error={errors.minRamGb}>
            <select
              id="filter-ram"
              value={draft.minRamGb}
              onChange={(e) => update("minRamGb")(e.target.value)}
              className={inputClass(errors.minRamGb)}
              {...aria("filter-ram", errors.minRamGb)}
            >
              <option value="">Any</option>
              {RAM_OPTIONS.map((gb) => (
                <option key={gb} value={gb}>
                  {gb} GB or more
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="flex items-end gap-2 sm:col-span-3">
          <button type="submit" className="btn-primary flex-1" disabled={busy}>
            {busy ? "Searching…" : "Search"}
          </button>
          <button type="button" className="btn-quiet" onClick={reset} disabled={!hasActiveFilters(draft) && !hasActiveFilters(applied)}>
            Reset
          </button>
        </div>
      </div>
    </form>
  );
}
