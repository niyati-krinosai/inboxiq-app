"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { api, ChatResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, ExternalLink } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  error?: string;
}

interface ChatPanelProps {
  selectedCategory: string | null;
}

const TIMELINE_FILTERS = [
  { key: "24h", label: "Today" },
  { key: "2d", label: "2 days" },
  { key: "4d", label: "4 days" },
  { key: "1w", label: "This week" },
  { key: "2w", label: "2 weeks" },
  { key: "1m", label: "This month" },
];

const MODE_SUGGESTIONS: Record<string, string[]> = {
  Fintech: [
    "Summarize fintech funding and product launches",
    "What payments or banking news hit my inbox?",
  ],
  Edtech: [
    "Edtech platform updates and learning tool launches",
    "What's new in online education from my newsletters?",
  ],
  "AI Startups": [
    "AI startup funding rounds and launches",
    "Which AI startups raised money recently?",
  ],
  "AI Tools Launched": [
    "New AI tools and product releases",
    "What AI products launched recently?",
  ],
  "Marketplace & Growth": [
    "Marketplace growth, acquisitions, and IPO news",
    "What's booming in the market from my newsletters?",
  ],
  "Research & Updates": [
    "Latest AI research papers and breakthroughs",
    "Research updates from my subscriptions",
  ],
  "Cloud & Infrastructure": [
    "Cloud provider updates and infrastructure news",
    "AWS, Azure, GCP and DevOps news from newsletters",
  ],
};

const DEFAULT_SUGGESTIONS = [
  "Give me a detailed digest of everything important",
  "TLDR updates from my subscriptions",
  "Startup funding and launches summary",
  "New AI tools released recently",
];

export function ChatPanel({ selectedCategory }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [timeline, setTimeline] = useState("1w");
  const bottomRef = useRef<HTMLDivElement>(null);

  const suggestions = useMemo(() => {
    if (selectedCategory && MODE_SUGGESTIONS[selectedCategory]) {
      return MODE_SUGGESTIONS[selectedCategory];
    }
    if (selectedCategory?.startsWith("newsletter:")) {
      return [
        "Summarize the latest issue",
        "What were the top stories?",
        "Elaborate on the most important story",
      ];
    }
    if (selectedCategory?.startsWith("theme:")) {
      return [
        "Digest of recent stories in this theme",
        "What's the most important update?",
        "Elaborate on the biggest story",
      ];
    }
    return DEFAULT_SUGGESTIONS;
  }, [selectedCategory]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(question: string) {
    if (!question.trim() || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);
    try {
      const response = await api.chat(
        question,
        selectedCategory ?? undefined,
        timeline
      );
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: response.headline, response },
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: msg, error: msg },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--border)] px-6 py-5">
        <h2 className="font-serif text-xl text-stone-900">Ask</h2>
        <p className="mt-1 text-sm text-stone-500">
          Detailed digests from your Gmail newsletters
          {selectedCategory && (
            <span className="text-[var(--accent)]"> · {selectedCategory}</span>
          )}
        </p>
        <div className="mt-4 flex flex-wrap gap-1">
          {TIMELINE_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setTimeline(f.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm transition-colors",
                timeline === f.key
                  ? "bg-[var(--accent)] text-white"
                  : "text-stone-600 hover:bg-[var(--warm)]"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 ? (
          <div className="mx-auto max-w-xl">
            <p className="text-sm leading-relaxed text-stone-600">
              Pick a mode on the left and a timeline above, then ask for a detailed
              summary. Results only include stories from the selected period.
            </p>
            <ul className="mt-6 space-y-2">
              {suggestions.map((s) => (
                <li key={s}>
                  <button
                    onClick={() => sendMessage(s)}
                    className="text-left text-sm text-stone-700 underline decoration-stone-300 underline-offset-2 hover:text-[var(--accent)] hover:decoration-[var(--accent)]"
                  >
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-8">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={cn(
                  "flex flex-col gap-1",
                  msg.role === "user" ? "items-end" : "items-start"
                )}
              >
                {msg.role === "user" ? (
                  <div className="max-w-lg rounded-lg bg-[var(--warm)] px-4 py-3 text-sm text-stone-800 ring-1 ring-[var(--border)]">
                    {msg.content}
                  </div>
                ) : (
                  <div className="w-full max-w-3xl border-l-2 border-[var(--accent)] pl-4">
                    {msg.error ? (
                      <p className="text-sm text-red-600">{msg.error}</p>
                    ) : msg.response ? (
                      <ChatResponseCard response={msg.response} />
                    ) : (
                      <p className="text-sm text-stone-600">{msg.content}</p>
                    )}
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <p className="flex items-center gap-2 text-sm text-stone-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                Building your digest…
              </p>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-[var(--border)] bg-[var(--bg)] p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage(input);
          }}
          className="mx-auto flex max-w-3xl gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              selectedCategory
                ? `Ask about ${selectedCategory}…`
                : "e.g. Detailed fintech digest"
            }
            className="flex-1 rounded-md border border-[var(--border)] bg-white px-4 py-2.5 text-sm text-stone-900 placeholder:text-stone-400 focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="rounded-md bg-[var(--accent)] px-5 py-2.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

function ChatResponseCard({ response }: { response: ChatResponse }) {
  const items = response.items ?? [];

  return (
    <div className="space-y-5 text-sm">
      <h3 className="font-serif text-xl text-stone-900">{response.headline}</h3>
      <p className="whitespace-pre-line leading-relaxed text-stone-700">
        {response.brief_summary}
      </p>

      {items.length > 0 && (
        <div>
          <p className="mb-3 text-xs font-medium tracking-wide text-stone-400 uppercase">
            {items.length} stories with links
          </p>
          <ul className="space-y-5">
            {items.map((item, i) => (
              <li
                key={i}
                className="rounded-md border border-[var(--border)] bg-white p-5"
              >
                <p className="text-base font-medium text-stone-900">{item.title}</p>
                <p className="mt-2 leading-relaxed text-stone-600">{item.summary}</p>
                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-400">
                  <span>{item.newsletter}</span>
                  {item.published_at && (
                    <span>
                      {new Date(item.published_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </span>
                  )}
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:underline"
                    >
                      Read article
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
