"use client";

import { cn } from "@/lib/utils";
import type { PersonalMode } from "@/lib/api";

export type View = "chat" | "timeline" | "sources" | "search";

interface SidebarProps {
  activeView: View;
  onViewChange: (view: View) => void;
  categories: string[];
  personalModes: PersonalMode[];
  selectedCategory: string | null;
  onCategoryChange: (category: string | null) => void;
  /** Krishna mentor desk: Ask + TLDR newsletter buttons only */
  tldrOnly?: boolean;
}

const MAIN_NAV: { id: View; label: string }[] = [
  { id: "chat", label: "Ask" },
  { id: "timeline", label: "Timeline" },
  { id: "search", label: "Search" },
];

const FEATURED_CATEGORIES = [
  "Fintech",
  "Edtech",
  "AI Startups",
  "AI Tools Launched",
  "Marketplace & Growth",
  "Research & Updates",
  "Cloud & Infrastructure",
];

function ModeButton({
  label,
  active,
  onClick,
  asChip = false,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  asChip?: boolean;
}) {
  if (asChip) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors",
          active
            ? "border-[var(--accent)] bg-white font-medium text-[var(--accent)] shadow-sm"
            : "border-[var(--border)] bg-white/70 text-stone-700 hover:border-stone-300 hover:bg-white"
        )}
      >
        {label}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-md px-3 py-1.5 text-left text-sm transition-colors",
        active ? "font-medium text-[var(--accent)]" : "text-stone-500 hover:text-stone-800"
      )}
    >
      {label}
    </button>
  );
}

export function Sidebar({
  activeView,
  onViewChange,
  categories,
  personalModes,
  selectedCategory,
  onCategoryChange,
  tldrOnly = false,
}: SidebarProps) {
  const displayCategories = categories.length > 0 ? categories : FEATURED_CATEGORIES;
  const newsletterModes = personalModes.filter((m) => m.kind === "newsletter");
  const themeModes = personalModes.filter((m) => m.kind === "theme");
  const nav = tldrOnly ? MAIN_NAV.filter((item) => item.id === "chat") : MAIN_NAV;

  function selectNewsletter(modeId: string) {
    onCategoryChange(modeId);
    onViewChange("chat");
  }

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--warm)]">
      <div className="border-b border-[var(--border)] px-5 py-5">
        <h1 className="font-serif text-lg tracking-tight text-stone-900">InboxIQ</h1>
        <p className="mt-0.5 text-xs text-stone-500">
          {tldrOnly ? "Your TLDR desk" : "Your newsletter desk"}
        </p>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="mb-6 space-y-0.5">
          {nav.map(({ id, label }) => (
            <li key={id}>
              <button
                type="button"
                onClick={() => onViewChange(id)}
                className={cn(
                  "w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                  activeView === id
                    ? "bg-white font-medium text-stone-900 shadow-sm ring-1 ring-[var(--border)]"
                    : "text-stone-600 hover:bg-white/60 hover:text-stone-900"
                )}
              >
                {label}
              </button>
            </li>
          ))}
        </ul>

        {newsletterModes.length > 0 && (
          <>
            <p className="mb-2 px-1 text-[11px] font-medium tracking-wider text-stone-400 uppercase">
              {tldrOnly ? "TLDR newsletters" : "Your newsletters"}
            </p>
            <ul className="mb-5 space-y-2">
              {newsletterModes.map((m) => (
                <li key={m.id}>
                  <ModeButton
                    label={m.label}
                    asChip
                    active={selectedCategory === m.id && activeView === "chat"}
                    onClick={() => selectNewsletter(m.id)}
                  />
                </li>
              ))}
            </ul>
          </>
        )}

        {!tldrOnly && (
          <>
            <ModeButton
              label="All modes"
              active={!selectedCategory}
              onClick={() => {
                onCategoryChange(null);
                onViewChange("chat");
              }}
            />

            {themeModes.length > 0 && (
              <>
                <p className="mb-2 mt-5 px-3 text-[11px] font-medium tracking-wider text-stone-400 uppercase">
                  Auto-organized
                </p>
                <ul className="space-y-0.5">
                  {themeModes.map((m) => (
                    <li key={m.id}>
                      <ModeButton
                        label={m.label}
                        active={selectedCategory === m.id}
                        onClick={() => {
                          onCategoryChange(m.id);
                          onViewChange("chat");
                        }}
                      />
                    </li>
                  ))}
                </ul>
              </>
            )}

            <p className="mb-2 mt-5 px-3 text-[11px] font-medium tracking-wider text-stone-400 uppercase">
              Topic modes
            </p>
            <ul className="space-y-0.5">
              {displayCategories.map((cat) => (
                <li key={cat}>
                  <ModeButton
                    label={cat}
                    active={selectedCategory === cat}
                    onClick={() => {
                      onCategoryChange(cat);
                      onViewChange("chat");
                    }}
                  />
                </li>
              ))}
            </ul>
          </>
        )}

        {tldrOnly && (
          <button
            type="button"
            onClick={() => {
              onCategoryChange(null);
              onViewChange("chat");
            }}
            className={cn(
              "mt-1 w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
              !selectedCategory
                ? "font-medium text-[var(--accent)]"
                : "text-stone-500 hover:text-stone-800"
            )}
          >
            All TLDR
          </button>
        )}
      </nav>
    </aside>
  );
}
