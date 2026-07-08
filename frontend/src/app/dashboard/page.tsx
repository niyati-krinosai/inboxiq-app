"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { api, User, SyncStatus, PersonalMode } from "@/lib/api";
import { getToken, clearToken } from "@/lib/api";
import { Sidebar, View } from "@/components/Sidebar";
import { ChatPanel } from "@/components/ChatPanel";
import { TimelinePanel } from "@/components/TimelinePanel";
import { SourcesPanel } from "@/components/SourcesPanel";
import { SearchPanel } from "@/components/SearchPanel";
import { Loader2 } from "lucide-react";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeView, setActiveView] = useState<View>("chat");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [personalModes, setPersonalModes] = useState<PersonalMode[]>([]);
  const [syncing, setSyncing] = useState(false);
  const autoSyncStarted = useRef(false);

  useEffect(() => {
    if (!getToken()) {
      router.push("/");
      return;
    }

    Promise.all([api.getMe(), api.getSyncStatus(), api.getCategories()])
      .then(async ([u, s, c]) => {
        setUser(u);
        setSyncStatus(s);
        setCategories(c.categories);
        setPersonalModes(c.personal_modes ?? []);
        if (
          s.gmail_connected &&
          !s.initial_sync_complete &&
          !autoSyncStarted.current
        ) {
          autoSyncStarted.current = true;
          setSyncing(true);
          try {
            await api.triggerSync();
            await api.processNewsletters();
          } catch {
            /* status poll will recover */
          } finally {
            setSyncing(false);
          }
        } else if ((s.pending_processing ?? 0) > 0 || s.article_count === 0) {
          api.processNewsletters().catch(() => {});
        }
      })
      .catch((err) => {
        console.error("Dashboard load failed:", err);
        router.push("/");
      })
      .finally(() => setLoading(false));

    const interval = setInterval(() => {
      api.getSyncStatus().then(setSyncStatus).catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, [router]);

  async function handleSync() {
    setSyncing(true);
    try {
      await api.triggerSync();
      await api.processNewsletters();
    } finally {
      setSyncing(false);
    }
  }

  function handleLogout() {
    clearToken();
    router.push("/");
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[var(--bg)]">
        <Loader2 className="h-6 w-6 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[var(--bg)] text-stone-900">
      <Sidebar
        activeView={activeView}
        onViewChange={setActiveView}
        categories={categories}
        personalModes={personalModes}
        selectedCategory={selectedCategory}
        onCategoryChange={setSelectedCategory}
      />

      <div className="flex flex-1 flex-col overflow-hidden bg-[var(--surface)]">
        <header className="flex items-center justify-between border-b border-[var(--border)] px-6 py-3">
          <div className="text-xs text-stone-500">
            {syncStatus && (
              <>
                {syncStatus.newsletter_count} newsletters · {syncStatus.article_count} articles
                {syncStatus.sync_status === "syncing" && (
                  <span className="ml-2 text-amber-700">
                    · importing from Gmail
                    <Loader2 className="ml-1 inline h-3 w-3 animate-spin" />
                  </span>
                )}
                {syncStatus.sync_status === "failed" && (
                  <span className="ml-2 text-red-600">· sync failed — click Sync now</span>
                )}
                {!syncStatus.initial_sync_complete &&
                  syncStatus.sync_status !== "syncing" &&
                  syncStatus.sync_status !== "failed" &&
                  syncStatus.gmail_connected && (
                  <span className="ml-2 text-amber-700">
                    · starting sync
                    <Loader2 className="ml-1 inline h-3 w-3 animate-spin" />
                  </span>
                )}
              </>
            )}
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={handleSync}
              disabled={syncing}
              className="text-xs text-stone-500 underline decoration-stone-300 underline-offset-2 hover:text-[var(--accent)] disabled:opacity-50"
            >
              {syncing ? "Syncing…" : "Sync now"}
            </button>
            <span className="text-sm text-stone-600">{user?.name || user?.email}</span>
            {user?.picture && (
              <img src={user.picture} alt="" className="h-7 w-7 rounded-full ring-1 ring-[var(--border)]" />
            )}
            <button
              onClick={handleLogout}
              className="text-xs text-stone-400 hover:text-stone-700"
            >
              Log out
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-hidden">
          {activeView === "chat" && <ChatPanel selectedCategory={selectedCategory} />}
          {activeView === "timeline" && <TimelinePanel selectedCategory={selectedCategory} />}
          {activeView === "sources" && <SourcesPanel />}
          {activeView === "search" && <SearchPanel selectedCategory={selectedCategory} />}
        </main>
      </div>
    </div>
  );
}
