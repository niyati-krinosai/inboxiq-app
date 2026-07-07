import { Suspense } from "react";

export default function AuthCallbackLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center bg-[var(--bg)]">
          <p className="text-sm text-stone-500">Loading…</p>
        </div>
      }
    >
      {children}
    </Suspense>
  );
}
