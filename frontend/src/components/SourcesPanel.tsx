"use client";

import { useEffect, useState } from "react";
import { api, Newsletter } from "@/lib/api";
import { getApiBase } from "@/lib/api-base";
import { formatRelativeDate } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function SourcesPanel() {
  const [newsletters, setNewsletters] = useState<Newsletter[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Newsletter | null>(null);
  const [articles, setArticles] = useState<
    { id: string; title: string; short_summary: string | null; categories: string[] | null; received_at: string }[]
  >([]);

  useEffect(() => {
    api
      .getNewsletters()
      .then(setNewsletters)
      .catch(() => setNewsletters([]))
      .finally(() => setLoading(false));
  }, []);

  async function selectNewsletter(nl: Newsletter) {
    setSelected(nl);
    try {
      const token = localStorage.getItem("inboxiq_token");
      const headers = { Authorization: `Bearer ${token}` };
      let res = await fetch(
        `${getApiBase()}/newsletters/${nl.id}/articles?limit=5000`,
        { headers }
      );
      if (res.status === 422) {
        res = await fetch(
          `${getApiBase()}/newsletters/${nl.id}/articles?limit=100`,
          { headers }
        );
      }
      const data = await res.json();
      setArticles(Array.isArray(data) ? data : []);
    } catch {
      setArticles([]);
    }
  }

  return (
    <div className="flex h-full">
      <div className="w-72 shrink-0 overflow-y-auto border-r border-[var(--border)] bg-[var(--bg)]">
        <div className="border-b border-[var(--border)] px-5 py-5">
          <h2 className="font-serif text-xl text-stone-900">Sources</h2>
          <p className="mt-1 text-sm text-stone-500">Newsletters we found in your Gmail</p>
        </div>

        {loading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-stone-400" />
          </div>
        ) : newsletters.length === 0 ? (
          <p className="p-5 text-sm text-stone-500">No newsletters yet. Try syncing.</p>
        ) : (
          <ul>
            {newsletters.map((nl) => (
              <li key={nl.id}>
                <button
                  onClick={() => selectNewsletter(nl)}
                  className={cn(
                    "w-full border-b border-[var(--border)] px-5 py-4 text-left transition-colors hover:bg-white",
                    selected?.id === nl.id && "bg-white"
                  )}
                >
                  <p className="truncate text-sm font-medium text-stone-800">{nl.name}</p>
                  <p className="mt-0.5 text-xs text-stone-400">
                    {nl.issue_count} issues · {nl.article_count ?? 0} articles
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6">
        {selected ? (
          <>
            <h3 className="font-serif text-2xl text-stone-900">{selected.name}</h3>
            <p className="mt-1 text-sm text-stone-500">
              {selected.sender_email}
              {selected.last_seen_at && (
                <> · last seen {formatRelativeDate(selected.last_seen_at)}</>
              )}
              <> · {articles.length} articles shown</>
            </p>
            <div className="mt-8 space-y-6">
              {articles.map((a) => (
                <article key={a.id} className="border-b border-[var(--border)] pb-5 last:border-0">
                  <h4 className="font-medium text-stone-800">{a.title}</h4>
                  {a.short_summary && (
                    <p className="mt-2 text-sm leading-relaxed text-stone-600">{a.short_summary}</p>
                  )}
                  {a.categories && a.categories.length > 0 && (
                    <p className="mt-2 text-xs text-stone-400">
                      {a.categories.slice(0, 4).join(" · ")}
                    </p>
                  )}
                </article>
              ))}
              {articles.length === 0 && (
                <p className="text-sm text-stone-500">No processed articles yet.</p>
              )}
            </div>
          </>
        ) : (
          <p className="py-20 text-center text-sm text-stone-400">
            Pick a newsletter from the list
          </p>
        )}
      </div>
    </div>
  );
}
