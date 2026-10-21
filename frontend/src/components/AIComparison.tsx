import { useEffect, useRef, useState } from "react";
import { ApiError, analyzeComparison } from "../api";
import { MAX_COMPARE, MIN_COMPARE, analysisMatches } from "../compare";
import { DEMO_MODE } from "../demo/mode";
import type { ComparisonAnalysis, Product, UseCase } from "../types";

const USE_CASES: Array<{ value: UseCase; label: string }> = [
  { value: "general", label: "General" },
  { value: "programming", label: "Programming" },
  { value: "student", label: "Student" },
  { value: "gaming", label: "Gaming" },
  { value: "travel", label: "Travel" },
];

/**
 * "Analyze with AI" for the open comparison. The parent remounts this component (via `key`) whenever
 * the selection changes, so a result is never shown for a different set of laptops.
 */
export default function AIComparison({ products }: { products: Product[] }) {
  const [useCase, setUseCase] = useState<UseCase>("general");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ComparisonAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []); // cancel on unmount (selection changed or comparison hidden)

  const nameOf = (id: number | null) => {
    const p = products.find((x) => x.id === id);
    return p ? `${p.brand} ${p.name}` : null;
  };

  const changeUseCase = (value: UseCase) => {
    inFlight.current?.abort();
    setUseCase(value);
    setResult(null); // an answer for another use case is stale
    setError(null);
    setBusy(false);
  };

  const analyze = async () => {
    if (inFlight.current) return; // no duplicate submissions (the ref also catches double clicks before re-render)
    const controller = new AbortController();
    inFlight.current = controller;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const analysis = await analyzeComparison(products.map((p) => p.id), useCase, controller.signal);
      if (!controller.signal.aborted) setResult(analysis);
    } catch (e) {
      if (controller.signal.aborted) return;
      setError(e instanceof ApiError ? e.message : "Something went wrong while analyzing these laptops.");
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
        setBusy(false);
      }
    }
  };

  const canAnalyze = products.length >= MIN_COMPARE && products.length <= MAX_COMPARE;
  const shown = result && analysisMatches(result, products) ? result : null;
  const picks = shown
    ? [
        { label: "Overall pick", id: shown.recommended_product_id },
        { label: "Best for budget", id: shown.best_for_budget },
        { label: "Best for performance", id: shown.best_for_performance },
      ]
    : [];

  return (
    <div className="mt-4 rounded-card border border-line bg-paper p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="compare-use-case" className="mb-1 block text-sm font-medium">
            Use case
          </label>
          <select
            id="compare-use-case"
            className="rounded-md border border-line bg-white px-3 py-2 text-sm"
            value={useCase}
            disabled={busy}
            onChange={(e) => changeUseCase(e.target.value as UseCase)}
          >
            {USE_CASES.map((u) => (
              <option key={u.value} value={u.value}>
                {u.label}
              </option>
            ))}
          </select>
        </div>
        <button type="button" className="btn-primary" disabled={!canAnalyze || busy} onClick={() => void analyze()}>
          {busy ? "Analyzing…" : DEMO_MODE ? "Analyze (demo, rule-based)" : "Analyze with AI"}
        </button>
      </div>

      <div className="mt-3" aria-live="polite" aria-busy={busy}>
        {busy && (
          <p role="status" className="flex items-center gap-2 text-sm text-ink/70">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-petrol border-t-transparent" aria-hidden />
            ShopWise AI is comparing these laptops…
          </p>
        )}
        {error && (
          <div role="alert" className="rounded-card border border-danger/30 bg-danger-tint p-3 text-sm">
            <p className="font-semibold text-danger">Couldn’t analyze this comparison</p>
            <p className="mt-1">{error}</p>
          </div>
        )}
        {shown && (
          <div className="space-y-3 text-sm">
            <p>{shown.summary}</p>

            <dl className="grid gap-2 sm:grid-cols-3">
              {picks.map((pick) => (
                <div key={pick.label} className="rounded-md border border-line bg-white p-2.5">
                  <dt className="text-xs font-semibold text-ink/60">{pick.label}</dt>
                  <dd className="mt-0.5 font-semibold">{nameOf(pick.id) ?? <span className="font-normal text-ink/60">No clear choice</span>}</dd>
                </div>
              ))}
            </dl>

            {shown.recommendation_reason && (
              <p>
                <span className="font-semibold">Why: </span>
                {shown.recommendation_reason}
              </p>
            )}

            {[
              { title: "Key trade-offs", items: shown.tradeoffs },
              { title: "Assumptions (general knowledge, not from the catalog)", items: shown.assumptions },
              { title: "Not in the data", items: shown.missing_data },
            ]
              .filter((section) => section.items.length > 0)
              .map((section) => (
                <div key={section.title}>
                  <p className="font-semibold">{section.title}</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {section.items.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              ))}

            {shown.warnings.map((w, i) => (
              <p key={i} className="rounded-md bg-amber-tint px-2.5 py-1.5 text-xs text-amber-ink">
                {w}
              </p>
            ))}
            <p className="text-xs text-amber-ink">{shown.data_notice} AI output may be wrong; check the specs above.</p>
          </div>
        )}
      </div>
    </div>
  );
}
