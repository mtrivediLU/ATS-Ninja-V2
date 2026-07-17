"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export type ArtifactView = "trust" | "content" | "template";

/** Keeps the first-class artifact view in the route without putting content in the URL. */
export function useArtifactView(): [ArtifactView, (view: ArtifactView) => void] {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawView = searchParams.get("view");
  const view: ArtifactView = rawView === "content" || rawView === "template" ? rawView : "trust";
  const setView = useCallback((next: ArtifactView) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "trust") params.delete("view");
    else params.set("view", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);
  return [view, setView];
}
