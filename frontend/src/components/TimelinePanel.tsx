"use client";

import { useEffect, useState } from "react";
import { api, CanonicalEvent } from "@/lib/api";
import { EventCard } from "./EventCard";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const DEFAULT_TIMELINE_FILTERS = [
  { key: "24h", label: "Today" },
  { key: "2d", label: "Yesterday" },
  { key: "4d", label: "2 days ago" },
  { key: "1w", label: "This week" },
  { key: "2w", label: "Last week" },
  { key: "1m", label: "This month" },
];

const KRISHNA_TIMELINE_FILTERS = [
  { key: "24h", label: "Today" },
  { key: "1w", label: "This week" },
  { key: "all", label: "Unlimited" },
];

interface TimelinePanelProps {
  selectedCategory: string | null;
  tldrOnly?: boolean;
}

export function TimelinePanel({ selectedCategory, tldrOnly = false }: TimelinePanelProps) {
  const filters = tldrOnly ? KRISHNA_TIMELINE_FILTERS : DEFAULT_TIMELINE_FILTERS;
  const [filter, setFilter] = useState(tldrOnly ? "all" : "1w");
  const [events, setEvents] = useState<CanonicalEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .getTimeline(filter, selectedCategory ?? undefined)
      .then((data) => setEvents(data.events))
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [filter, selectedCategory]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--border)] px-6 py-5">
        <h2 className="font-serif text-xl text-stone-900">Timeline</h2>
        <p className="mt-1 text-sm text-stone-500">
          {tldrOnly
            ? "Stories from your TLDR newsletters"
            : "Stories from your newsletters, deduplicated"}
          {!tldrOnly && selectedCategory && (
            <span className="text-[var(--accent)]"> · {selectedCategory}</span>
          )}
        </p>
        <div className="mt-4 flex flex-wrap gap-1">
          {filters.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm transition-colors",
                filter === f.key
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
        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2 className="h-5 w-5 animate-spin text-stone-400" />
          </div>
        ) : events.length === 0 ? (
          <div className="mx-auto max-w-md py-16 text-center">
            <p className="text-stone-600">Nothing here for this period yet.</p>
            <p className="mt-2 text-sm text-stone-400">
              If you just connected Gmail, give the sync a few minutes.
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-2xl space-y-6">
            {events.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
