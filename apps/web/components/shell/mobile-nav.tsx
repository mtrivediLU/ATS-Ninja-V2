"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "@/components/shell/brand";
import { NavigationView } from "@/components/shell/navigation-view";
import { Drawer } from "@/components/ui/drawer";
import { mobileMoreItem, navigationGroups } from "@/lib/navigation";

export function MobileNavDrawer({ open, onClose, hasCurrentKit, onEvidence }: { open: boolean; onClose: () => void; hasCurrentKit: boolean; onEvidence: () => void }) {
  return (
    <Drawer open={open} onClose={onClose} title="Navigation" side="left" className="max-w-[280px]">
      <div className="border-b border-border-subtle px-4 py-3">
        <Brand />
      </div>
      <nav aria-label="Labelled navigation" className="flex min-h-0 flex-1 px-3 py-4">
        <NavigationView hasCurrentKit={hasCurrentKit} expanded onEvidence={onEvidence} onNavigate={onClose} />
      </nav>
    </Drawer>
  );
}

export function MobileBottomNav({ hasCurrentKit, onMore }: { hasCurrentKit: boolean; onMore: () => void }) {
  const pathname = usePathname();
  const groups = navigationGroups(hasCurrentKit);
  const all = groups.flatMap((group) => group.items);
  const items = [
    all.find((item) => item.id === "new"),
    all.find((item) => item.id === "history"),
    all.find((item) => item.id === "resume"),
    mobileMoreItem,
  ].filter((item) => item !== undefined);

  return (
    <nav aria-label="Mobile primary navigation" className="fixed inset-x-0 bottom-0 z-[var(--z-header)] flex h-[60px] border-t border-border bg-surface md:hidden">
      {items.map((item) => {
        const Icon = item.icon;
        const active = Boolean(item.href && pathname === item.href);
        const disabled = Boolean(item.currentKitOnly && !hasCurrentKit);
        const classes = `flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] ${active ? "font-semibold text-accent" : "text-ink-muted"} ${disabled ? "opacity-45" : ""}`;
        const content = <><Icon aria-hidden="true" className="size-5" strokeWidth={1.7} /><span>{item.shortLabel ?? (item.id === "resume" ? "Kit" : item.label)}</span></>;
        if (item.action === "more") {
          return <button key={item.id} type="button" className={classes} onClick={onMore}>{content}</button>;
        }
        if (!item.href || disabled) {
          return <span key={item.id} className={classes} aria-disabled="true">{content}</span>;
        }
        return <Link key={item.id} href={item.href} className={classes} aria-current={active ? "page" : undefined}>{content}</Link>;
      })}
    </nav>
  );
}
