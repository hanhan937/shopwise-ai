import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getHealth, getProducts } from "./api";
import HealthBadge from "./components/HealthBadge";
import AIChat from "./components/AIChat";
import CompareBar from "./components/CompareBar";
import ComparisonTable from "./components/ComparisonTable";
import ProductTable from "./components/ProductTable";
import SearchFilters from "./components/SearchFilters";
import { chatProductToProduct } from "./chatProducts";
import { MAX_COMPARE, MIN_COMPARE, toggleSelection } from "./compare";
import { EMPTY_FILTERS, hasActiveFilters, toQuery, type FilterValues } from "./filters";
import type { ChatProduct, Health, Product, ProductList } from "./types";

const PAGE_SIZE = 10;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [applied, setApplied] = useState<FilterValues>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ProductList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);
  // Full product objects (not just ids) so the selection survives page changes and new searches.
  const [compareList, setCompareList] = useState<Product[]>([]);
  const [showCompare, setShowCompare] = useState(false);
  const [compareRequest, setCompareRequest] = useState(0); // bumps on every Compare click, to scroll to the table

  const load = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setLoading(true);
    setError(null);
    try {
      const result = await getProducts(PAGE_SIZE, page * PAGE_SIZE, toQuery(applied));
      if (requestId === latestRequest.current) setData(result); // ignore responses from superseded searches
    } catch (e) {
      if (requestId === latestRequest.current) {
        setError(e instanceof ApiError ? e.message : "Something went wrong while loading products.");
      }
    } finally {
      if (requestId === latestRequest.current) setLoading(false);
    }
  }, [applied, page]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    getHealth()
      .then((h) => {
        setHealth(h);
        setOffline(false);
      })
      .catch(() => setOffline(true));
  }, []);

  // If the current page no longer exists (e.g. results shrank), go back to the first page.
  useEffect(() => {
    if (data && data.items.length === 0 && data.total > 0 && page > 0) setPage(0);
  }, [data, page]);

  const applyFilters = (values: FilterValues) => {
    setApplied(values);
    setPage(0); // a new search always starts on page 1
  };

  const resetFilters = () => {
    setApplied(EMPTY_FILTERS);
    setPage(0);
  };

  const toggleCompare = (product: Product) => setCompareList((list) => toggleSelection(list, product));
  const removeFromCompare = (id: number) => setCompareList((list) => list.filter((p) => p.id !== id));
  const clearCompare = () => {
    setCompareList([]);
    setShowCompare(false);
  };
  const compareIds = new Set(compareList.map((p) => p.id));
  const comparisonVisible = showCompare && compareList.length >= MIN_COMPARE;
  const openComparison = () => {
    setShowCompare(true);
    setCompareRequest((n) => n + 1);
  };

  useEffect(() => {
    if (compareRequest > 0) document.getElementById("compare-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [compareRequest]);

  const filtersActive = hasActiveFilters(applied);
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-baseline gap-2">
            <span className="text-xl font-bold tracking-tight">ShopWise</span>
            <span className="text-sm text-ink/60">laptop research assistant</span>
          </div>
          <HealthBadge health={health} offline={offline} />
        </div>
        <p className="bg-amber-tint px-4 py-1.5 text-center text-xs text-amber-ink">
          Mock data: every laptop, spec, and price here is synthetic and for demonstration only.
        </p>
      </header>

      <main className={`mx-auto max-w-5xl px-4 py-8 ${compareList.length > 0 ? "pb-40" : ""}`}>
        <h1 className="text-2xl font-bold tracking-tight">Product catalog</h1>
        <p className="mt-1 max-w-xl text-sm text-ink/70">
          Search by brand, model, or specs, then narrow by price and RAM. Tick up to 3 laptops to compare them side by
          side.
        </p>

        <div className="mt-6">
          <SearchFilters applied={applied} busy={loading} onApply={applyFilters} onReset={resetFilters} />
        </div>

        <CompareBar selected={compareList} onRemove={removeFromCompare} onClear={clearCompare} onCompare={openComparison} />
        {comparisonVisible && (
          <ComparisonTable products={compareList} onRemove={removeFromCompare} onClose={() => setShowCompare(false)} />
        )}

        <div className="mt-6" aria-live="polite" aria-busy={loading}>
          {error ? (
            <div role="alert" className="rounded-card border border-danger/30 bg-danger-tint p-4">
              <p className="font-semibold text-danger">Couldn’t load the catalog</p>
              <p className="mt-1 text-sm">{error}</p>
              <button type="button" className="btn-quiet mt-3" onClick={() => void load()}>
                Try again
              </button>
            </div>
          ) : loading && !data ? (
            <div className="space-y-2" aria-label="Loading products">
              {Array.from({ length: 6 }, (_, i) => (
                <div key={i} className="h-12 animate-pulse rounded-card border border-line bg-white" />
              ))}
            </div>
          ) : data && data.items.length === 0 ? (
            filtersActive ? (
              <div className="rounded-card border border-line bg-white p-6">
                <p className="font-semibold">No laptops match your filters</p>
                <p className="mt-1 max-w-md text-sm text-ink/70">
                  Try fewer or different search words, a higher max price, or a lower RAM requirement.
                </p>
                <button type="button" className="btn-quiet mt-4" onClick={resetFilters}>
                  Reset filters
                </button>
              </div>
            ) : (
              <div className="rounded-card border border-line bg-white p-6">
                <p className="font-semibold">The catalog is empty</p>
                <p className="mt-1 text-sm text-ink/70">
                  Import the sample laptops with <code>python -m app.ingest</code> in <code>backend/</code>, or restart
                  the backend with <code>AUTO_INGEST=true</code>.
                </p>
              </div>
            )
          ) : data ? (
            <>
              {filtersActive && (
                <p className="mb-3 text-sm text-ink/70">
                  {data.total} laptop{data.total === 1 ? "" : "s"} match your filters.
                </p>
              )}
              <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
                <ProductTable products={data.items} selectedIds={compareIds} onToggleCompare={toggleCompare} />
              </div>
              <nav className="mt-4 flex items-center justify-between text-sm" aria-label="Pagination">
                <p className="text-ink/70">
                  {data.offset + 1}–{data.offset + data.items.length} of {data.total}
                </p>
                <div className="flex items-center gap-2">
                  <button type="button" className="btn-quiet" disabled={page === 0 || loading} onClick={() => setPage((p) => p - 1)}>
                    Previous
                  </button>
                  <span className="px-1 text-ink/70">
                    Page {page + 1} of {totalPages}
                  </span>
                  <button
                    type="button"
                    className="btn-quiet"
                    disabled={page + 1 >= totalPages || loading}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </button>
                </div>
              </nav>
            </>
          ) : null}
        </div>
        <AIChat
          selectedIds={compareIds}
          compareFull={compareList.length >= MAX_COMPARE}
          onToggleCompare={(p: ChatProduct) => toggleCompare(chatProductToProduct(p))}
        />
      </main>
    </div>
  );
}
