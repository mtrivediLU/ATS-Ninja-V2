"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export type ArtifactView = "trust" | "content";

/** Keeps the first-class trust/content view in the route without putting content in the URL. */
export function useArtifactView(): [ArtifactView, (view: ArtifactView) => void] {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const view: ArtifactView = searchParams.get("view") === "content" ? "content" : "trust";
  const setView = useCallback((next: ArtifactView) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "trust") params.delete("view");
    else params.set("view", "content");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);
  return [view, setView];
}
