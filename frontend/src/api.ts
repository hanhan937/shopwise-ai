import type { ProductQuery } from "./filters";
import type { ChatProduct, ComparisonAnalysis, Health, ProductList, UseCase } from "./types";

// In dev, Vite proxies /api/* to the backend (and strips the /api prefix); in Docker, nginx does the same.
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FIELD_LABELS: Record<string, string> = {
  q: "Search",
  min_price: "Min price",
  max_price: "Max price",
  min_ram_gb: "Min RAM",
  cpu: "CPU",
  limit: "Page size",
  offset: "Offset",
  product_ids: "Selected laptops",
  use_case: "Use case",
};

/** FastAPI validation errors look like {loc: ["query", "min_price"], msg: "..."}. */
function describeValidationError(d: { loc?: unknown[]; msg?: string }): string {
  const msg = d.msg ?? "invalid value";
  const field = Array.isArray(d.loc) && d.loc.length > 0 ? String(d.loc[d.loc.length - 1]) : "";
  return field ? `${FIELD_LABELS[field] ?? field}: ${msg}` : msg;
}

async function toApiError(res: Response): Promise<ApiError> {
  let message = `The server returned an error (${res.status}).`;
  let code = "http_error";
  try {
    const detail = (await res.json())?.detail;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) message = "Check your input: " + detail.map(describeValidationError).join("; ");
    else if (detail && typeof detail === "object") {
      message = detail.message ?? message;
      code = detail.code ?? code;
    }
  } catch {
    /* non-JSON body: keep the generic message */
  }
  return new ApiError(message, res.status, code);
}

async function request<T>(path: string, timeoutMs = 10_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("The request took too long. Try again in a moment.", 0, "timeout");
    }
    throw new ApiError("Can't reach the ShopWise API. Make sure the backend is running, then try again.", 0, "network");
  } finally {
    clearTimeout(timer);
  }
  // /health answers 503 with a useful JSON body when degraded, so callers decide what to do with it.
  if (!res.ok && !(path === "/health" && res.status === 503)) throw await toApiError(res);
  return (await res.json()) as T;
}

export const getHealth = () => request<Health>("/health");

export function getProducts(limit: number, offset: number, query: ProductQuery = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (query.q) params.set("q", query.q);
  if (query.minPrice !== undefined) params.set("min_price", String(query.minPrice));
  if (query.maxPrice !== undefined) params.set("max_price", String(query.maxPrice));
  if (query.minRamGb !== undefined) params.set("min_ram_gb", String(query.minRamGb));
  return request<ProductList>(`/products?${params.toString()}`);
}


export interface ChatResult {
  reply: string;
  products: ChatProduct[];
  tools_used: string[];
}

export async function sendChat(message: string): Promise<ChatResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 75000);
  try {
    const response = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal: controller.signal,
    });
    if (!response.ok) throw await toApiError(response);
    return (await response.json()) as ChatResult;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiError("The assistant took too long to respond. Please try again.", 0, "timeout");
    }
    throw new ApiError("Unable to contact the AI assistant.", 0, "network");
  } finally {
    clearTimeout(timer);
  }
}

/** AI comparison of 2-3 products. The server looks the specs up itself; only ids are sent. */
export async function analyzeComparison(productIds: number[], useCase: UseCase, signal?: AbortSignal): Promise<ComparisonAnalysis> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 75000);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort);
  try {
    const response = await fetch(`${BASE}/compare/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_ids: productIds, use_case: useCase }),
      signal: controller.signal,
    });
    if (!response.ok) throw await toApiError(response);
    return (await response.json()) as ComparisonAnalysis;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError") {
      if (signal?.aborted) throw error; // cancelled by the caller: not a user-facing error
      throw new ApiError("The AI analysis took too long. Please try again.", 0, "timeout");
    }
    throw new ApiError("Unable to contact the AI service.", 0, "network");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
