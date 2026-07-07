"use client";

import { useState } from "react";
import { api, CanonicalEvent } from "@/lib/api";
import { EventCard } from "./EventCard";
import { Loader2 } from "lucide-react";

interface SearchPanelProps {
  selectedCategory: string | null;
}

export function SearchPanel({ selectedCategory }: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CanonicalEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setSearched(true);
    try {
      const data = await api.search(query, selectedCategory ?? undefined);
      setResults(data.events);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  const QUICK_SEARCHES = [
    "OpenAI", "Anthropic", "MCP", "vLLM", "LangGraph",
    "Gemini", "Claude", "LlamaIndex", "Redis", "Postgres",
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--border)] px-6 py-5">
        <h2 className="font-serif text-xl text-stone-900">Search</h2>
        <p className="mt-1 text-sm text-stone-500">
          Companies, products, APIs — across everything you subscribe to
        </p>
        <form onSubmit={handleSearch} className="mt-4 flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Try OpenAI, funding, MCP…"
            className="flex-1 rounded-md border border-[var(--border)] bg-white px-4 py-2.5 text-sm text-stone-900 placeholder:text-stone-400 focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-[var(--accent)] px-5 py-2.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-40"
          >
            Search
          </button>
        </form>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1">
          {QUICK_SEARCHES.map((q) => (
            <button
              key={q}
              onClick={() => {
                setQuery(q);
                setLoading(true);
                setSearched(true);
                api.search(q, selectedCategory ?? undefined)
                  .then((d) => setResults(d.events))
                  .catch(() => setResults([]))
                  .finally(() => setLoading(false));
              }}
              className="text-xs text-stone-500 underline decoration-stone-300 underline-offset-2 hover:text-[var(--accent)]"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2 className="h-5 w-5 animate-spin text-stone-400" />
          </div>
        ) : searched ? (
          results.length > 0 ? (
            <div className="mx-auto max-w-2xl">
              <p className="mb-6 text-sm text-stone-500">{results.length} results</p>
              <div className="space-y-6">
                {results.map((event) => (
                  <EventCard key={event.id} event={event} />
                ))}
              </div>
            </div>
          ) : (
            <p className="py-20 text-center text-stone-500">No matches.</p>
          )
        ) : (
          <p className="py-20 text-center text-sm text-stone-400">
            Search your newsletter archive
          </p>
        )}
      </div>
    </div>
  );
}
