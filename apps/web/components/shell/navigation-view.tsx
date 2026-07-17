"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { navigationGroups } from "@/lib/navigation";

type NavigationViewProps = {
  hasCurrentKit: boolean;
  expanded: boolean;
  onEvidence: () => void;
  onNavigate?: () => void;
};

export function NavigationView({ hasCurrentKit, expanded, onEvidence, onNavigate }: NavigationViewProps) {
  const pathname = usePathname();
  const groups = navigationGroups(hasCurrentKit);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {groups.map((group) => (
        <div key={group.id} className={group.id === "utility" ? "mt-auto pt-5" : "mt-2 first:mt-0"}>
          {group.label && expanded && (
            <p className="px-2 pb-2 text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">
              {group.label}
            </p>
          )}
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const Icon = item.icon;
              const disabled = Boolean(item.currentKitOnly && !hasCurrentKit);
              const active = Boolean(item.href && (pathname === item.href || (item.id !== "new" && pathname.startsWith(`${item.href}/`))));
              const classes = `flex w-full items-center rounded-md text-left text-base transition-colors ${
                expanded ? "min-h-11 gap-3 px-2" : "min-h-10 justify-center px-2"
              } ${
                item.primary
                  ? "bg-accent font-semibold text-on-accent hover:bg-accent-hover active:bg-accent-active"
                  : active
                    ? "bg-surface-raised font-semibold text-ink"
                    : "text-ink-secondary hover:bg-surface-subtle hover:text-ink active:bg-surface-raised"
              } ${disabled ? "cursor-not-allowed opacity-45" : ""}`;
              const content = (
                <>
                  <Icon aria-hidden="true" className="size-[19px] shrink-0" strokeWidth={1.7} />
                  {expanded && <span className="min-w-0 flex-1 truncate">{item.label}</span>}
                  {expanded && item.count !== undefined && <span className="font-mono text-[11px] text-ink-muted">{item.count}</span>}
                </>
              );

              if (item.action === "evidence") {
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={classes}
                    disabled={disabled}
                    aria-label={!expanded ? item.label : undefined}
                    title={!expanded ? item.label : undefined}
                    onClick={() => {
                      onEvidence();
                      onNavigate?.();
                    }}
                  >
                    {content}
                  </button>
                );
              }

              if (!item.href || disabled) {
                return (
                  <span
                    key={item.id}
                    className={classes}
                    aria-disabled="true"
                    aria-label={!expanded ? `${item.label}, unavailable without an open kit` : undefined}
                    title={!expanded ? `${item.label} — no kit open` : undefined}
                  >
                    {content}
                  </span>
                );
              }

              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className={classes}
                  aria-current={active ? "page" : undefined}
                  aria-label={!expanded ? item.label : undefined}
                  title={!expanded ? item.label : undefined}
                  onClick={onNavigate}
                >
                  {content}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
