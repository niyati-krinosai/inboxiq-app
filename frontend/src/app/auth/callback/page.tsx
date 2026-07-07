"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [message, setMessage] = useState("Signing you in…");
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    const token = searchParams.get("token");
    const error = searchParams.get("error");

    if (error) {
      setIsError(true);
      setMessage(decodeURIComponent(error.replace(/\+/g, " ")));
      return;
    }

    if (!token) {
      setIsError(true);
      setMessage("No sign-in token received. Please try again.");
      return;
    }

    setToken(token);
    api
      .getMe()
      .then(() => router.replace("/dashboard"))
      .catch(() => {
        setIsError(true);
        setMessage("Signed in with Google but the app could not verify your session. Is the backend running?");
      });
  }, [searchParams, router]);

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--bg)]">
      <div className="max-w-sm text-center px-6">
        {!isError && <Loader2 className="mx-auto mb-3 h-6 w-6 animate-spin text-stone-400" />}
        <p className="text-sm text-stone-600">{message}</p>
        {isError && (
          <button
            onClick={() => router.replace("/")}
            className="mt-6 text-sm text-[var(--accent)] underline underline-offset-2"
          >
            Back to sign in
          </button>
        )}
      </div>
    </div>
  );
}
