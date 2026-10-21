import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, sendChat } from "../api";
import { RETRYABLE_CODES, splitChatProducts } from "../chatProducts";
import type { ChatProduct } from "../types";
import ChatProductCard from "./ChatProductCard";

type Message = { from: "you" | "ai"; content: string; products?: ChatProduct[] };

const EXAMPLES = [
  "Lenovo laptops under $1000 with at least 16GB RAM",
  "Something light and quiet for coding on train rides",
  "A student laptop for travel, under $900, with 16GB RAM",
];

interface Props {
  /** Ids already in the compare list (shared with the catalog table). */
  selectedIds: Set<number>;
  compareFull: boolean;
  onToggleCompare: (product: ChatProduct) => void;
}

export default function AIChat({ selectedIds, compareFull, onToggleCompare }: Props) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; retry: string | null } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (messages.length > 0 || busy) endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, busy]);

  async function ask(text: string, isRetry = false) {
    if (!text || busy) return;
    if (!isRetry) setMessages((all) => [...all, { from: "you", content: text }]);
    setQuestion("");
    setError(null);
    setBusy(true);
    try {
      const response = await sendChat(text);
      setMessages((all) => [...all, { from: "ai", content: response.reply, products: response.products }]);
    } catch (err) {
      const retryable = err instanceof ApiError && RETRYABLE_CODES.has(err.code);
      setError({
        message: err instanceof ApiError ? err.message : "The assistant is temporarily unavailable.",
        retry: retryable ? text : null,
      });
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question.trim());
  }

  return (
    <section className="mt-8 rounded-card border border-line bg-white p-4" aria-label="Ask ShopWise AI">
      <h2 className="text-xl font-bold">Ask ShopWise AI</h2>
      <p className="mt-1 text-sm text-ink/70">Ask about laptops in our synthetic demonstration catalog. Prices and specs are not real-world offers.</p>

      {messages.length === 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold text-ink/60">Try asking</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                className="rounded-full border border-line bg-paper px-3 py-1.5 text-left text-xs hover:border-petrol hover:text-petrol-dark disabled:opacity-50"
                disabled={busy}
                onClick={() => void ask(example)}
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 space-y-3" aria-live="polite">
        {messages.map((msg, i) => (
          <div key={i}>
            <div
              className={
                msg.from === "you"
                  ? "ml-auto max-w-[85%] rounded-card border border-petrol/30 bg-petrol-tint p-3"
                  : "mr-auto max-w-full rounded-card border border-line bg-paper p-3 sm:max-w-[85%]"
              }
            >
              <p className={`mb-1 text-xs font-semibold ${msg.from === "you" ? "text-petrol-dark" : "text-ink/70"}`}>
                {msg.from === "you" ? "You" : "ShopWise AI"}
              </p>
              <p className="whitespace-pre-wrap break-words text-sm">{msg.content}</p>
            </div>
            {msg.products && msg.products.length > 0 && (
              <ProductResults reply={msg.content} products={msg.products} selectedIds={selectedIds} compareFull={compareFull} onToggleCompare={onToggleCompare} />
            )}
          </div>
        ))}
        {busy && (
          <p role="status" className="flex items-center gap-2 text-sm text-ink/70">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-petrol border-t-transparent" aria-hidden />
            ShopWise AI is searching the catalog…
          </p>
        )}
        {error && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-danger/30 bg-danger-tint p-3 text-sm">
            <span className="text-danger">{error.message}</span>
            {error.retry && (
              <button type="button" className="btn-quiet px-3 py-1.5 text-xs" onClick={() => void ask(error.retry!, true)}>
                Try again
              </button>
            )}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="shopwise-chat" className="sr-only">Your laptop shopping question</label>
        <input id="shopwise-chat" className="min-w-0 flex-1 rounded-card border border-line p-3 text-sm" value={question}
          maxLength={2000} placeholder="Find a Lenovo under $1,000 with 16GB RAM…"
          onChange={(event) => setQuestion(event.target.value)} disabled={busy} />
        <button className="btn-primary" type="submit" disabled={busy || !question.trim()}>
          {busy ? "Sending…" : "Send"}
        </button>
      </form>
    </section>
  );
}

function ProductResults({ reply, products, selectedIds, compareFull, onToggleCompare }: { reply: string; products: ChatProduct[] } & Props) {
  const { mentioned, others } = splitChatProducts(reply, products);
  const grid = (items: ChatProduct[]) => (
    <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((p) => (
        <ChatProductCard key={p.id} product={p} selected={selectedIds.has(p.id)} compareFull={compareFull} onToggleCompare={onToggleCompare} />
      ))}
    </div>
  );
  return (
    <div className="mt-2">
      {mentioned.length > 0 && grid(mentioned)}
      {others.length > 0 && (
        <details className="mt-2 text-sm" open={mentioned.length === 0}>
          <summary className="cursor-pointer text-xs font-semibold text-ink/60">
            {mentioned.length > 0 ? `Other search results (${others.length})` : `Search results (${others.length})`}
          </summary>
          {grid(others)}
        </details>
      )}
    </div>
  );
}
