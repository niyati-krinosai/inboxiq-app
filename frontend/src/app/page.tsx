"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "@/lib/api";
import { isLocalDev } from "@/lib/api-base";

const FEATURES = [
  {
    title: "Reads your newsletters",
    desc: "Connects to Gmail with read-only access. Only newsletter senders — not your personal inbox.",
  },
  {
    title: "Deduplicates the noise",
    desc: "When TLDR, Ben's Bites, and The Rundown cover the same story, you get one clean summary.",
  },
  {
    title: "Ask questions naturally",
    desc: "\"What happened in AI this week?\" or \"Any new MCP servers?\" — answered from your subscriptions.",
  },
  {
    title: "Browse by topic",
    desc: "Filter by funding, APIs, open source, or whatever categories matter to you.",
  },
];

export default function LandingPage() {
  const router = useRouter();

  useEffect(() => {
    if (getToken()) {
      api.getMe()
        .then(() => router.push("/dashboard"))
        .catch(() => {});
    }
  }, [router]);

  async function handleLogin() {
    try {
      const { auth_url } = await api.getLoginUrl();
      window.location.href = auth_url;
    } catch {
      alert(
        isLocalDev()
          ? "Cannot connect locally. Run: docker compose up -d"
          : "InboxIQ is temporarily unavailable. Please try again shortly."
      );
    }
  }

  return (
    <div className="min-h-screen bg-[var(--bg)] text-stone-900">
      <div className="mx-auto max-w-3xl px-6 py-12 sm:px-8 sm:py-16">
        <header className="mb-16 flex items-center justify-between border-b border-[var(--border)] pb-6">
          <span className="font-serif text-xl tracking-tight text-stone-900">
            InboxIQ
          </span>
          <button
            onClick={handleLogin}
            className="text-sm text-stone-600 underline decoration-stone-300 underline-offset-4 hover:text-[var(--accent)] hover:decoration-[var(--accent)]"
          >
            Sign in
          </button>
        </header>

        <main>
          <p className="mb-4 text-sm font-medium tracking-wide text-[var(--accent)] uppercase">
            Newsletter reader, upgraded
          </p>
          <h1 className="font-serif text-4xl leading-[1.15] tracking-tight text-stone-900 sm:text-5xl">
            Stop re-reading the same story in five different newsletters.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-stone-600">
            InboxIQ pulls in your Gmail subscriptions, merges duplicate coverage,
            and lets you search and ask questions across everything you already read.
          </p>

          <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              onClick={handleLogin}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-[var(--accent)] px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-hover)]"
            >
              Connect Gmail
            </button>
            <span className="text-sm text-stone-500">
              Read-only. We never send or delete mail.
            </span>
          </div>

          <section className="mt-20 border-t border-[var(--border)] pt-14">
            <h2 className="font-serif text-2xl text-stone-900">How it works</h2>
            <ol className="mt-8 space-y-10">
              {FEATURES.map((f, i) => (
                <li key={f.title} className="flex gap-5">
                  <span className="font-serif text-2xl text-stone-300 tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h3 className="font-medium text-stone-900">{f.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-stone-600">
                      {f.desc}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </main>

        <footer className="mt-20 border-t border-[var(--border)] pt-8 text-sm text-stone-500">
          Built for people who subscribe to too many newsletters.
        </footer>
      </div>
    </div>
  );
}
