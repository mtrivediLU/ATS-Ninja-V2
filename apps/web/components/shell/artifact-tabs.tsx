"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef } from "react";
import { artifactNavigation } from "@/lib/navigation";

export function ArtifactTabs({ kitId = "demo" }: { kitId?: string }) {
  const pathname = usePathname();
  const refs = useRef<Array<HTMLAnchorElement | null>>([]);

  return (
    <nav aria-label="Kit artifacts" className="scrollbar-none w-full min-w-0 max-w-full overflow-x-auto border-b border-border bg-surface">
      <div role="tablist" aria-label="Application kit artifacts" className="flex min-w-max px-4 sm:px-5">
        {artifactNavigation.map((item, index) => {
          const href = `/kits/${kitId}/${item.id}`;
          const active = pathname === href;
          return (
            <Link
              key={item.id}
              ref={(node) => {
                refs.current[index] = node;
              }}
              href={href}
              role="tab"
              aria-selected={active}
              aria-current={active ? "page" : undefined}
              aria-controls="artifact-workspace"
              tabIndex={active ? 0 : -1}
              onKeyDown={(event) => {
                const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
                if (!direction) return;
                event.preventDefault();
                const next = (index + direction + artifactNavigation.length) % artifactNavigation.length;
                refs.current[next]?.focus();
              }}
              className="flex min-h-11 items-center whitespace-nowrap border-b-2 border-transparent px-3 text-sm text-ink-muted hover:text-ink aria-selected:border-accent aria-selected:font-semibold aria-selected:text-ink sm:px-4"
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
