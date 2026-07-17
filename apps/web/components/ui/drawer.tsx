"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { IconButton } from "@/components/ui/primitives";

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  side?: "left" | "right";
  children: ReactNode;
  className?: string;
  fullWidthOnMobile?: boolean;
};

export function Drawer({ open, onClose, title, side = "right", children, className = "", fullWidthOnMobile = false }: DrawerProps) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    if (window.matchMedia("(min-width: 1024px)").matches) return;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      restoreFocusRef.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[var(--z-drawer)] lg:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-ink/35"
        aria-label={`Close ${title}`}
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`absolute inset-y-0 flex w-full ${fullWidthOnMobile ? "max-w-none sm:max-w-[360px]" : "max-w-[360px]"} flex-col bg-surface shadow-lg motion-safe:transition-transform ${
          side === "left" ? "left-0 border-r border-border" : "right-0 border-l border-border"
        } ${className}`}
      >
        <header className="flex min-h-[60px] items-center justify-between gap-3 border-b border-border-subtle px-4">
          <h2 id={titleId} className="text-md font-semibold">
            {title}
          </h2>
          <IconButton ref={closeRef} aria-label={`Close ${title}`} onClick={onClose}>
            <X aria-hidden="true" className="size-5" />
          </IconButton>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </aside>
    </div>
  );
}
