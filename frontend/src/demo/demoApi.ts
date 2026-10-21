/**
 * Demo-mode replacements for the API calls in ../api.ts. No network, no AWS.
 *
 * - Catalog search mirrors the backend rules (backend/app/product_filters.py): every query word must appear
 *   (case-insensitive substring) in one of the searchable columns; price bounds are inclusive; ordered by id.
 * - Chat returns PRESET answers for the example questions (built from the bundled catalog, so names, prices and
 *   specs are the real catalog values) and a notice for anything else.
 * - Comparison returns a RULE-BASED summary of the selected specs, labelled as not AI-generated.
 */
import type { ChatResult } from "../api";
import type { ProductQuery } from "../filters";
import { formatPrice, formatStorage } from "../format";
import type { ChatProduct, ComparisonAnalysis, Health, Product, ProductList, UseCase } from "../types";
import catalogJson from "./catalog.json";

export const CATALOG = catalogJson as Product[];
const DATA_NOTICE =
  "Synthetic demonstration data: names, specifications and prices are invented, are not real-time, and carry no stock or benchmark information.";
const DEMO_LABEL = "Demo answer (preset example, not generated live by AI).";

const SEARCH_FIELDS = (p: Product) =>
  [p.brand, p.name, p.cpu, p.gpu, p.os, p.storage_type, p.display_resolution, p.best_for.join(";")].map((v) => v.toLowerCase());

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

export function searchCatalog(query: ProductQuery = {}): Product[] {
  const terms = (query.q ?? "").toLowerCase().split(/\s+/).filter(Boolean);
  return CATALOG.filter((p) => {
    const fields = SEARCH_FIELDS(p);
    return (
      terms.every((t) => fields.some((f) => f.includes(t))) &&
      (query.minPrice === undefined || p.price >= query.minPrice) &&
      (query.maxPrice === undefined || p.price <= query.maxPrice) &&
      (query.minRamGb === undefined || p.ram_gb >= query.minRamGb)
    );
  }).sort((a, b) => a.id - b.id);
}

export async function getHealth(): Promise<Health> {
  return { status: "ok", database: false, pgvector: false, products_total: CATALOG.length };
}

export async function getProducts(limit: number, offset: number, query: ProductQuery = {}): Promise<ProductList> {
  const matches = searchCatalog(query);
  return { items: matches.slice(offset, offset + limit), total: matches.length, limit, offset };
}

// ------------------------------------------------------------------ chat presets
const toChat = (p: Product): ChatProduct => ({
  id: p.id, sku: p.sku, brand: p.brand, name: p.name, price: p.price, cpu: p.cpu, gpu: p.gpu, ram_gb: p.ram_gb,
  storage_gb: p.storage_gb, storage_type: p.storage_type, weight_kg: p.weight_kg, os: p.os, best_for: p.best_for,
  source_name: p.source_name, is_mock: p.is_mock,
});  // prettier-ignore
const line = (p: Product, i: number) =>
  `${i + 1}. ${p.brand} ${p.name} - ${formatPrice(p.price)}: ${p.cpu}, ${p.ram_gb}GB RAM, ${formatStorage(p.storage_gb)} ${p.storage_type}, ${p.weight_kg} kg.`;
const has = (p: Product, ...tags: string[]) => tags.every((t) => p.best_for.includes(t));

const PRESETS: Array<{ question: string; pick: () => Product[]; intro: string; outro: string }> = [
  {
    question: "Lenovo laptops under $1000 with at least 16GB RAM",
    pick: () => CATALOG.filter((p) => p.brand === "Lenovo" && p.price <= 1000 && p.ram_gb >= 16),
    intro: "Lenovo laptops under $1000 with at least 16GB RAM:",
    outro: "Both meet the budget and the RAM minimum.",
  },
  {
    question: "Something light and quiet for coding on train rides",
    pick: () => CATALOG.filter((p) => has(p, "programming", "travel")).sort((a, b) => a.weight_kg - b.weight_kg).slice(0, 3),
    intro: "The lightest laptops tagged for both programming and travel:",
    outro: "The catalog has no noise measurements, so quietness can't be compared.",
  },
  {
    question: "A student laptop for travel, under $900, with 16GB RAM",
    pick: () =>
      CATALOG.filter((p) => (has(p, "students") || has(p, "travel")) && p.price <= 900 && p.ram_gb >= 16)
        .sort((a, b) => a.price - b.price)
        .slice(0, 3),
    intro: "Laptops tagged for students or travel, under $900, with at least 16GB RAM (cheapest first):",
    outro: "All are within the budget and have at least 16GB RAM.",
  },
];
export const DEMO_QUESTIONS = PRESETS.map((p) => p.question);

const normalize = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();

export async function sendChat(message: string): Promise<ChatResult> {
  await wait(500); // keeps the loading state visible
  const preset = PRESETS.find((p) => normalize(p.question) === normalize(message));
  if (!preset) {
    return {
      reply:
        "This online demo can't answer free-form questions: the AI assistant (Amazon Bedrock Nova Lite with catalog search tools) " +
        "only runs in the local Docker version. Try one of the example questions, or use the catalog search and filters above.",
      products: [],
      tools_used: [],
    };
  }
  const picks = preset.pick();
  return {
    reply: [DEMO_LABEL, "", preset.intro, ...picks.map(line), "", preset.outro, "", `(${DATA_NOTICE})`].join("\n"),
    products: picks.map(toChat),
    tools_used: [],
  };
}

// ------------------------------------------------------------------ rule-based comparison
export async function analyzeComparison(productIds: number[], useCase: UseCase, signal?: AbortSignal): Promise<ComparisonAnalysis> {
  await wait(500, signal);
  const products = productIds.map((id) => CATALOG.find((p) => p.id === id)).filter((p): p is Product => !!p);
  const by = (score: (p: Product) => number) => [...products].sort((a, b) => score(a) - score(b));
  const cheapest = by((p) => p.price)[0];
  const priciest = by((p) => -p.price)[0];
  const lightest = by((p) => p.weight_kg)[0];
  const mostRam = by((p) => -p.ram_gb)[0];
  const mostStorage = by((p) => -p.storage_gb)[0];
  const name = (p: Product) => `${p.brand} ${p.name}`;
  const oses = [...new Set(products.map((p) => p.os))];

  return {
    product_ids: productIds,
    use_case: useCase,
    summary: `Demo: rule-based summary of the listed specs, not an AI response. ${name(cheapest)} is the cheapest at ${formatPrice(cheapest.price)}; ${name(priciest)} costs the most at ${formatPrice(priciest.price)}.`,
    best_for_budget: cheapest.id,
    best_for_performance: null,
    recommended_product_id: null,
    recommendation_reason: "",
    tradeoffs: [
      `Price: ${formatPrice(cheapest.price)} to ${formatPrice(priciest.price)}.`,
      `Lightest: ${name(lightest)} (${lightest.weight_kg} kg).`,
      `Most RAM: ${name(mostRam)} (${mostRam.ram_gb} GB); most storage: ${name(mostStorage)} (${formatStorage(mostStorage.storage_gb)}).`,
      oses.length > 1 ? `Operating systems differ: ${oses.join(", ")}.` : `All run ${oses[0]}.`,
    ],
    assumptions: [],
    missing_data: [
      "No benchmarks: CPUs and GPUs can't be ranked from the catalog.",
      "A use-case recommendation needs the live AI analysis, which runs only in the local Docker version with Amazon Bedrock.",
    ],
    warnings: ["Demo mode: this analysis was generated by fixed rules in your browser, not by an AI model."],
    data_notice: DATA_NOTICE,
  };
}
