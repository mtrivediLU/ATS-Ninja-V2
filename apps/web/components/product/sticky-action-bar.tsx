import type { ReactNode } from "react";

/** Mobile-only actions stay above the bottom navigation and safe-area inset. */
export function StickyActionBar({ children }: { children: ReactNode }) {
  return <div className="fixed inset-x-0 bottom-[calc(var(--bottomnav-h)+env(safe-area-inset-bottom))] z-[calc(var(--z-header)+1)] flex gap-2 border-t border-border bg-surface p-3 shadow-lg md:hidden">{children}</div>;
}
