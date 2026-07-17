"use client";

import { Menu } from "lucide-react";
import { Brand } from "@/components/shell/brand";
import { NavigationView } from "@/components/shell/navigation-view";
import { IconButton } from "@/components/ui/primitives";

export function Sidebar({ hasCurrentKit, onOpenDrawer, onEvidence }: { hasCurrentKit: boolean; onOpenDrawer: () => void; onEvidence: () => void }) {
  return (
    <aside className="sticky top-0 hidden h-screen w-16 flex-col border-r border-border bg-surface px-2 py-4 md:flex lg:w-[248px] lg:px-3" aria-label="Primary navigation">
      <div className="hidden px-1 lg:block">
        <Brand />
      </div>
      <div className="flex flex-col items-center gap-2 lg:hidden">
        <Brand compact />
        <IconButton aria-label="Open labelled navigation" onClick={onOpenDrawer}>
          <Menu aria-hidden="true" className="size-5" />
        </IconButton>
      </div>
      <div className="mt-4 min-h-0 flex-1">
        <div className="hidden h-full lg:flex">
          <NavigationView hasCurrentKit={hasCurrentKit} expanded onEvidence={onEvidence} />
        </div>
        <div className="flex h-full lg:hidden">
          <NavigationView hasCurrentKit={hasCurrentKit} expanded={false} onEvidence={onEvidence} />
        </div>
      </div>
    </aside>
  );
}
