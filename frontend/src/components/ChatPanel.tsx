"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { api, ChatResponse, PinnedArticle } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, ExternalLink, MessageCircle, X } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  sourceUrl?: string | null;
  error?: string;
}

interface ArticleThread {
  messages: Message[];
  sessionId?: string;
  loading: boolean;
}

interface ChatPanelProps {
  selectedCategory: string | null;
  selectedLabel?: string | null;
  tldrOnly?: boolean;
}

const DEFAULT_TIMELINE_FILTERS = [
  { key: "24h", label: "Today" },
  { key: "2d", label: "2 days" },
  { key: "4d", label: "4 days" },
  { key: "1w", label: "This week" },
  { key: "2w", label: "2 weeks" },
  { key: "1m", label: "This month" },
];

const KRISHNA_TIMELINE_FILTERS = [
  { key: "24h", label: "Today" },
  { key: "1m", label: "This month" },
  { key: "all", label: "Unlimited" },
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

const KRISHNA_SUGGESTIONS = [
  "Tell me all the TLDR news for this timeline",
  "Give me every Fintech story in this period",
  "Summarize all AI updates from TLDR",
  "What launched or raised funding in TLDR?",
];

export function ChatPanel({
  selectedCategory,
  selectedLabel = null,
  tldrOnly = false,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<
    { role: "user" | "assistant"; content: string; response?: ChatResponse; error?: string }[]
  >([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [timeline, setTimeline] = useState(tldrOnly ? "all" : "1w");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [openArticleId, setOpenArticleId] = useState<string | null>(null);
  const [articleThreads, setArticleThreads] = useState<Record<string, ArticleThread>>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  const timelineFilters = tldrOnly ? KRISHNA_TIMELINE_FILTERS : DEFAULT_TIMELINE_FILTERS;

  const suggestions = useMemo(() => {
    if (tldrOnly) return KRISHNA_SUGGESTIONS;
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
  }, [selectedCategory, tldrOnly]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(question: string) {
    if (!question.trim() || loading) return;
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setLoading(true);
    try {
      const response = await api.chat(question, selectedCategory ?? undefined, timeline, sessionId);
      if (response.session_id) {
        setSessionId(response.session_id);
      }
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

  async function sendArticleMessage(
    articleId: string,
    question: string,
    options?: { showUserMessage?: boolean }
  ) {
    if (!question.trim()) return;
    const showUserMessage = options?.showUserMessage !== false;

    setArticleThreads((prev) => {
      const thread = prev[articleId] ?? { messages: [], sessionId: undefined, loading: false };
      return {
        ...prev,
        [articleId]: {
          ...thread,
          loading: true,
          messages: showUserMessage
            ? [...thread.messages, { role: "user", content: question }]
            : thread.messages,
        },
      };
    });

    const priorSessionId = articleThreads[articleId]?.sessionId;

    try {
      const response = await api.chat(question, selectedCategory ?? undefined, timeline, priorSessionId, {
        articleId,
      });
      const item = response.items?.[0];
      const content = item?.summary || response.brief_summary || response.headline || "No answer available.";
      setArticleThreads((prev) => {
        const thread = prev[articleId] ?? { messages: [], sessionId: undefined, loading: false };
        return {
          ...prev,
          [articleId]: {
            messages: [...thread.messages, { role: "assistant", content, sourceUrl: item?.url }],
            sessionId: response.session_id ?? thread.sessionId,
            loading: false,
          },
        };
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      setArticleThreads((prev) => {
        const thread = prev[articleId] ?? { messages: [], sessionId: undefined, loading: false };
        return {
          ...prev,
          [articleId]: {
            ...thread,
            loading: false,
            messages: [...thread.messages, { role: "assistant", content: msg, error: msg }],
          },
        };
      });
    }
  }

  function handleAskMore(article: PinnedArticle) {
    const id = article.article_id;
    const alreadyStarted = Boolean(articleThreads[id]);
    setOpenArticleId((prev) => (prev === id ? null : id));
    if (!alreadyStarted) {
      setArticleThreads((prev) => ({
        ...prev,
        [id]: { messages: [], sessionId: undefined, loading: false },
      }));
      void sendArticleMessage(
        id,
        "Give me a full detailed account of this story — background, what happened, implications, and limitations.",
        { showUserMessage: false }
      );
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--border)] px-6 py-5">
        <h2 className="font-serif text-xl text-stone-900">Ask</h2>
        <p className="mt-1 text-sm text-stone-500">
          {tldrOnly
            ? "Detailed digests from your TLDR newsletters"
            : "Detailed digests from your Gmail newsletters"}
          {selectedLabel && (
            <span className="text-[var(--accent)]"> · chatting in {selectedLabel}</span>
          )}
          {!selectedLabel && selectedCategory && !selectedCategory.startsWith("newsletter:") && (
            <span className="text-[var(--accent)]"> · {selectedCategory}</span>
          )}
        </p>
        <div className="mt-4 flex flex-wrap gap-1">
          {timelineFilters.map((f) => (
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
              Pick a newsletter on the left and a timeline above, then ask for a detailed
              summary. Click <strong>Ask more</strong> on any story to open a chat about it
              right beside that story.
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
                      <ChatResponseCard
                        response={msg.response}
                        openArticleId={openArticleId}
                        articleThreads={articleThreads}
                        onAskMore={handleAskMore}
                        onSendArticleMessage={sendArticleMessage}
                        onCloseArticlePopup={() => setOpenArticleId(null)}
                      />
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

function ChatResponseCard({
  response,
  openArticleId,
  articleThreads,
  onAskMore,
  onSendArticleMessage,
  onCloseArticlePopup,
}: {
  response: ChatResponse;
  openArticleId: string | null;
  articleThreads: Record<string, ArticleThread>;
  onAskMore: (article: PinnedArticle) => void;
  onSendArticleMessage: (articleId: string, question: string) => void;
  onCloseArticlePopup: () => void;
}) {
  const items = response.items ?? [];

  return (
    <div className="space-y-5 text-sm">
      <div>
        <h3 className="font-serif text-xl text-stone-900">{response.headline}</h3>
        {response.brief_summary && (
          <p className="mt-2 leading-relaxed text-stone-600">{response.brief_summary}</p>
        )}
        {items.length > 0 && (
          <p className="mt-2 text-xs font-medium tracking-wide text-stone-500 uppercase">
            {items.length} {items.length === 1 ? "story" : "stories"} · full list
          </p>
        )}
      </div>

      {items.length > 0 && (
        <ul className="space-y-6">
          {items.map((item, i) => {
            const articleId = item.article_id;
            const isOpen = Boolean(articleId) && articleId === openArticleId;
            return (
              <li
                key={articleId ?? i}
                className={cn(
                  "relative rounded-md border bg-white p-5",
                  isOpen
                    ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/20"
                    : "border-[var(--border)]"
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-base font-medium text-stone-900">{item.title}</p>
                  {articleId && (
                    <button
                      type="button"
                      onClick={() =>
                        onAskMore({
                          article_id: articleId,
                          title: item.title,
                          url: item.url,
                          newsletter: item.newsletter,
                        })
                      }
                      className={cn(
                        "inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium",
                        isOpen
                          ? "border-[var(--accent)] text-[var(--accent)]"
                          : "border-[var(--border)] text-stone-600 hover:border-[var(--accent)] hover:text-[var(--accent)]"
                      )}
                    >
                      <MessageCircle className="h-3.5 w-3.5" />
                      Ask more
                    </button>
                  )}
                </div>
                <p className="mt-3 leading-relaxed whitespace-pre-line text-stone-700">
                  {item.summary}
                </p>
                {item.url ? (
                  <p className="mt-4 text-sm text-stone-600">
                    Read full article here:{" "}
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:underline"
                    >
                      open link
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </p>
                ) : (
                  <p className="mt-4 text-xs text-stone-400">
                    Source: {item.newsletter}
                    {item.published_at && (
                      <>
                        {" "}
                        ·{" "}
                        {new Date(item.published_at).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                        })}
                      </>
                    )}
                  </p>
                )}

                {isOpen && articleId && (
                  <ArticleChatPopup
                    title={item.title}
                    thread={
                      articleThreads[articleId] ?? { messages: [], loading: false }
                    }
                    onSend={(question) => onSendArticleMessage(articleId, question)}
                    onClose={onCloseArticlePopup}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ArticleChatPopup({
  title,
  thread,
  onSend,
  onClose,
}: {
  title: string;
  thread: { messages: Message[]; loading: boolean };
  onSend: (question: string) => void;
  onClose: () => void;
}) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [thread.messages.length, thread.loading]);

  return (
    <div className="absolute left-0 right-0 top-full z-30 mt-2 flex max-h-96 w-full flex-col overflow-hidden rounded-lg border border-[var(--accent)]/40 bg-white shadow-xl sm:left-full sm:right-auto sm:top-0 sm:mt-0 sm:ml-3 sm:w-80">
      <div className="flex items-start justify-between gap-2 border-b border-[var(--border)] bg-[var(--warm)] px-3 py-2.5">
        <p className="line-clamp-2 text-xs font-medium text-stone-700">{title}</p>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded p-0.5 text-stone-400 hover:bg-white hover:text-stone-700"
          aria-label="Close chat"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {thread.messages.map((msg, i) => (
          <div
            key={i}
            className={cn(
              "flex flex-col gap-1",
              msg.role === "user" ? "items-end" : "items-start"
            )}
          >
            {msg.role === "user" ? (
              <div className="max-w-[85%] rounded-md bg-[var(--warm)] px-2.5 py-1.5 text-xs text-stone-800">
                {msg.content}
              </div>
            ) : msg.error ? (
              <p className="text-xs text-red-600">{msg.content}</p>
            ) : (
              <div className="w-full space-y-1.5 border-l-2 border-[var(--accent)] pl-2.5 text-xs leading-relaxed whitespace-pre-line text-stone-700">
                <p>{msg.content}</p>
                {msg.sourceUrl && (
                  <a
                    href={msg.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:underline"
                  >
                    open source
                    <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                )}
              </div>
            )}
          </div>
        ))}
        {thread.loading && (
          <p className="flex items-center gap-1.5 text-xs text-stone-400">
            <Loader2 className="h-3 w-3 animate-spin" />
            Thinking…
          </p>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!input.trim() || thread.loading) return;
          onSend(input);
          setInput("");
        }}
        className="flex gap-1.5 border-t border-[var(--border)] p-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a follow-up…"
          disabled={thread.loading}
          className="flex-1 rounded-md border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs text-stone-900 placeholder:text-stone-400 focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
        />
        <button
          type="submit"
          disabled={thread.loading || !input.trim()}
          className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}
