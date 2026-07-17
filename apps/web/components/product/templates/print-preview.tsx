"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Printer, X } from "lucide-react";
import { Button } from "@/components/ui/primitives";

export function PrintPreview({ open, title, filename, onClose, children, onPrint }: { open: boolean; title: string; filename: string; onClose: () => void; children: ReactNode; onPrint: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusable = () => Array.from(panelRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
    const frame = window.requestAnimationFrame(() => focusable()[0]?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab") return;
      const elements = focusable();
      if (!elements.length) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { window.cancelAnimationFrame(frame); document.removeEventListener("keydown", onKeyDown); restoreFocusRef.current?.focus(); };
  }, [onClose, open]);

  function print() {
    const previousTitle = document.title;
    document.title = `${filename}.pdf`;
    onPrint();
    window.setTimeout(() => { document.title = previousTitle; }, 1000);
    window.setTimeout(() => window.print(), 50);
  }

  if (!open) return null;
  return <div className="t1-print-overlay" role="dialog" aria-modal="true" aria-label={title}>
    <div ref={panelRef} className="t1-print-panel">
      <header className="t1-print-controls"><div><h2>{title}</h2><p>Letter size · browser print only</p></div><span className="flex-1" /><Button variant="primary" onClick={print}><Printer aria-hidden="true" className="size-4" />Print / Save as PDF</Button><Button variant="secondary" onClick={onClose}><X aria-hidden="true" className="size-4" />Close</Button></header>
      <div className="t1-print-root">{children}</div>
    </div>
  </div>;
}
