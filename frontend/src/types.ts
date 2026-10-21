export interface Product {
  id: number;
  sku: string;
  name: string;
  brand: string;
  price: number;
  cpu: string;
  gpu: string;
  ram_gb: number;
  storage_gb: number;
  storage_type: string;
  display_size_in: number;
  display_resolution: string;
  weight_kg: number;
  battery_hours: number | null;
  os: string;
  best_for: string[];
  description: string;
  source_name: string;
  source_url: string | null;
  is_mock: boolean;
}

export interface ProductList {
  items: Product[];
  total: number;
  limit: number;
  offset: number;
}

export interface Health {
  status: "ok" | "degraded";
  database: boolean;
  pgvector: boolean;
  products_total: number;
}

export type UseCase = "general" | "programming" | "student" | "gaming" | "travel";

/** POST /compare/analyze response (Module 2C-2). Recommended ids are always among `product_ids` or null. */
export interface ComparisonAnalysis {
  product_ids: number[];
  use_case: UseCase;
  summary: string;
  best_for_budget: number | null;
  best_for_performance: number | null;
  recommended_product_id: number | null;
  recommendation_reason: string;
  tradeoffs: string[];
  assumptions: string[];
  missing_data: string[];
  warnings: string[];
  data_notice: string;
}
