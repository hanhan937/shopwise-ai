import type { ChatProduct, Product } from "./types";

/**
 * /chat returns every product the agent's tools retrieved, which can include rows the reply rejected
 * (e.g. "the other three don't have an RTX card"). The cards should show what the reply actually
 * recommends, so products named in the reply come first, in the order the reply mentions them; the
 * rest stay available as "other search results".
 */
export function splitChatProducts(reply: string, products: ChatProduct[]): { mentioned: ChatProduct[]; others: ChatProduct[] } {
  const text = reply.toLowerCase();
  const positions = new Map<number, number>();
  for (const p of products) {
    const at = text.indexOf(p.name.toLowerCase());
    if (at >= 0 && !positions.has(p.id)) positions.set(p.id, at);
  }
  const mentioned = products.filter((p) => positions.has(p.id)).sort((a, b) => positions.get(a.id)! - positions.get(b.id)!);
  const others = products.filter((p) => !positions.has(p.id));
  return { mentioned, others };
}

/** Chat rows lack a few catalog fields the comparison never shows; fill them so they fit the compare list. */
export function chatProductToProduct(p: ChatProduct): Product {
  return {
    ...p,
    display_size_in: 0,
    display_resolution: "",
    battery_hours: null,
    description: "",
    source_url: null,
  };
}

/** Error codes worth a "Try again" button (temporary conditions; see backend app/ai/errors.py). */
export const RETRYABLE_CODES = new Set(["ai_timeout", "ai_rate_limited", "ai_unreachable", "timeout", "network", "ai_no_answer"]);
