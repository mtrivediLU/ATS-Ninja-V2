"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Check, CircleAlert } from "lucide-react";

type FeedbackContextValue = { notify: (message: string, tone?: "success" | "error") => void };
const FeedbackContext = createContext<FeedbackContextValue | null>(null);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const notify = useCallback((message: string, tone: "success" | "error" = "success") => {
    setNotice({ message, tone });
    window.setTimeout(() => setNotice(null), 2800);
  }, []);
  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div aria-live="polite" aria-atomic="true" className="fixed bottom-20 left-1/2 z-[var(--z-toast)] -translate-x-1/2 md:bottom-5">
        {notice && (
          <div
            role={notice.tone === "error" ? "alert" : "status"}
            className={`flex max-w-[min(90vw,520px)] items-center gap-3 rounded-md px-4 py-3 text-sm shadow-lg ${notice.tone === "error" ? "bg-danger text-surface" : "bg-ink text-surface"}`}
          >
            {notice.tone === "error" ? <CircleAlert aria-hidden="true" className="size-[17px]" /> : <Check aria-hidden="true" className="size-[17px] text-positive" />}
            {notice.message}
          </div>
        )}
      </div>
    </FeedbackContext.Provider>
  );
}

export function useFeedback(): FeedbackContextValue {
  const value = useContext(FeedbackContext);
  if (!value) throw new Error("useFeedback must be used within FeedbackProvider");
  return value;
}
