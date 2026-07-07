import { getApiBase, isLocalDev } from "@/lib/api-base";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("inboxiq_token");
}

export function setToken(token: string) {
  localStorage.setItem("inboxiq_token", token);
}

export function clearToken() {
  localStorage.removeItem("inboxiq_token");
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const API_BASE = getApiBase();

  const token = getToken();

  const headers: Record<string, string> = {

    "Content-Type": "application/json",

    ...(options.headers as Record<string, string>),

  };

  if (token) headers.Authorization = `Bearer ${token}`;



  let res: Response;

  try {

    res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  } catch {
    const hint = isLocalDev()
      ? "Cannot reach the server. Run: docker compose up -d"
      : "Cannot reach InboxIQ right now. Please try again in a moment.";
    throw new Error(hint);
  }



  if (res.status === 401) {

    clearToken();

    if (typeof window !== "undefined") window.location.href = "/";

    throw new Error("Session expired — please sign in again.");

  }

  if (!res.ok) {

    let detail = `Request failed (${res.status})`;

    try {

      const body = await res.json();

      detail = body.detail || body.message || detail;

    } catch {

      const text = await res.text();

      if (text) detail = text.slice(0, 200);

    }

    throw new Error(detail);

  }

  return res.json();

}



export interface User {

  id: string;

  email: string;

  name: string | null;

  picture: string | null;

  initial_sync_complete: boolean;

  last_sync_at: string | null;

}



export interface EventSource {

  newsletter_name: string;

  article_url: string | null;

  summary_snippet: string | null;

}



export interface CanonicalEvent {

  id: string;

  headline: string;

  primary_summary: string | null;

  why_it_matters: string | null;

  technical_impact: string | null;

  business_impact: string | null;

  categories: string[] | null;

  companies: string[] | null;

  importance_score: number | null;

  official_link: string | null;

  published_at: string | null;

  sources: EventSource[];

}



export interface Newsletter {

  id: string;

  name: string;

  sender_email: string;

  issue_count: number;

  domain: string | null;

  last_seen_at: string;

}



export interface ChatArticleItem {

  title: string;

  summary: string;

  url: string | null;

  newsletter: string;

  published_at?: string | null;

}



export interface ChatResponse {

  headline: string;

  brief_summary: string;

  why_it_matters?: string;

  technical_impact?: string | null;

  business_impact?: string | null;

  sources: { newsletter: string; url: string | null }[];

  official_link?: string | null;

  related_news: string[];

  items?: ChatArticleItem[];

  session_id?: string | null;

}



export interface PersonalMode {
  id: string;
  label: string;
  kind: "newsletter" | "theme";
  description?: string;
  newsletter_id?: string;
}

export interface CategoriesResponse {
  categories: string[];
  personal_modes: PersonalMode[];
}

export interface SyncStatus {

  initial_sync_complete: boolean;

  last_sync_at: string | null;

  newsletter_count: number;

  issue_count: number;

  article_count: number;

  pending_processing?: number;

}



export const api = {

  getLoginUrl: () => apiFetch<{ auth_url: string }>("/auth/login"),

  getMe: () => apiFetch<User>("/auth/me"),

  getSyncStatus: () => apiFetch<SyncStatus>("/sync/status"),

  triggerSync: () => apiFetch<{ status: string }>("/sync/trigger", { method: "POST" }),

  processNewsletters: () => apiFetch<{ status: string }>("/sync/process", { method: "POST" }),

  getTimeline: (filter: string, category?: string) => {

    const params = new URLSearchParams({ filter });

    if (category) params.set("category", category);

    return apiFetch<{ events: CanonicalEvent[]; total: number }>(`/timeline?${params}`);

  },

  search: (q: string, category?: string, timeline?: string) => {

    const params = new URLSearchParams();

    if (q) params.set("q", q);

    if (category) params.set("category", category);

    if (timeline) params.set("timeline", timeline);

    return apiFetch<{ events: CanonicalEvent[]; total: number }>(`/search?${params}`);

  },

  chat: (question: string, category?: string, timeline?: string, sessionId?: string) =>

    apiFetch<ChatResponse>("/chat", {

      method: "POST",

      body: JSON.stringify({
        question,
        category,
        timeline,
        session_id: sessionId ?? null,
      }),

    }),

  getNewsletters: () => apiFetch<Newsletter[]>("/newsletters"),

  getCategories: () => apiFetch<CategoriesResponse>("/categories"),

};


