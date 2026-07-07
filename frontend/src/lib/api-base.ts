export function getApiBase(): string {
  const explicit = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/$/, "");
  if (explicit) return explicit;

  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      return "http://localhost:8000/api/v1";
    }
    // Production: same-origin — proxied by /api/v1 route handler on Vercel
    return "/api/v1";
  }

  const backend = process.env.BACKEND_URL?.trim().replace(/\/$/, "");
  if (backend) return `${backend}/api/v1`;
  return "/api/v1";
}

export function isLocalDev(): boolean {
  if (typeof window === "undefined") return false;
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1";
}
