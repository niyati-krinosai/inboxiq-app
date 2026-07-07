"use client";

import { CanonicalEvent } from "@/lib/api";
import { cn, formatRelativeDate } from "@/lib/utils";

interface EventCardProps {
  event: CanonicalEvent;
  compact?: boolean;
}

export function EventCard({ event, compact }: EventCardProps) {
  const categories = event.categories?.slice(0, 3) ?? [];

  return (
    <article
      className={cn(
        "border-b border-[var(--border)] pb-6 last:border-0",
        compact && "pb-4"
      )}
    >
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-serif text-lg leading-snug text-stone-900">
          {event.headline}
        </h3>
        {event.published_at && (
          <time className="text-xs text-stone-400">
            {formatRelativeDate(event.published_at)}
          </time>
        )}
      </div>

      {categories.length > 0 && (
        <p className="mb-2 text-xs text-stone-500">
          {categories.join(" · ")}
        </p>
      )}

      <p className={cn("leading-relaxed text-stone-600", compact ? "text-sm line-clamp-2" : "text-sm")}>
        {event.primary_summary}
      </p>

      {event.why_it_matters && !compact && (
        <p className="mt-3 text-sm text-stone-500">
          <span className="text-stone-700">Note: </span>
          {event.why_it_matters}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-stone-400">
        {event.sources?.slice(0, 3).map((s, i) => (
          <span key={i}>{s.newsletter_name || "Newsletter"}</span>
        ))}
        {event.official_link && (
          <a
            href={event.official_link}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] hover:underline"
          >
            Read more
          </a>
        )}
      </div>
    </article>
  );
}
