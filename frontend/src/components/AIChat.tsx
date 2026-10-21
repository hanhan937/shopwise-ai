import { useState, type FormEvent } from "react";
import { ApiError, sendChat } from "../api";

type Message = { from: "you" | "ai"; content: string };

export default function AIChat() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setMessages((all) => [...all, { from: "you", content: text }]);
    setQuestion("");
    setError("");
    setBusy(true);
    try {
      const response = await sendChat(text);
      setMessages((all) => [...all, { from: "ai", content: response.reply }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The assistant is temporarily unavailable.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 rounded-card border border-line bg-white p-4" aria-label="Ask ShopWise AI">
      <h2 className="text-xl font-bold">Ask ShopWise AI</h2>
      <p className="mt-1 text-sm text-ink/70">Ask about laptops in our synthetic demonstration catalog. Prices and specs are not real-world offers.</p>
      <div className="mt-4 space-y-3" aria-live="polite">
        {messages.map((msg, i) => (
          <div key={i} className="rounded-card border border-line p-3">
            <p className="mb-1 text-xs font-semibold">{msg.from === "you" ? "You" : "ShopWise AI"}</p>
            <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
          </div>
        ))}
        {busy && <p role="status" className="text-sm">ShopWise AI is thinking…</p>}
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      </div>
      <form onSubmit={(event) => void submit(event)} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="shopwise-chat" className="sr-only">Your laptop shopping question</label>
        <input id="shopwise-chat" className="min-w-0 flex-1 rounded-card border border-line p-3 text-sm" value={question}
          maxLength={2000} placeholder="Find a Lenovo under $1,000 with 16GB RAM…"
          onChange={(event) => setQuestion(event.target.value)} disabled={busy} />
        <button className="btn-quiet" type="submit" disabled={busy || !question.trim()}>Send</button>
      </form>
    </section>
  );
}
