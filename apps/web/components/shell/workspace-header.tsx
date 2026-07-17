"use client";

import { Menu, PanelRight } from "lucide-react";
import { IconButton, StatusLabel, Tooltip } from "@/components/ui/primitives";
import type { StatusPresentation } from "@/lib/status";

export function WorkspaceHeader({ title, meta, status, results, evidenceOpen, onMenu, onEvidence }: { title: string; meta?: string; status?: StatusPresentation; results: boolean; evidenceOpen: boolean; onMenu: () => void; onEvidence: () => void }) {
  return (
    <header className="sticky top-0 z-[var(--z-header)] flex min-h-[60px] items-center gap-3 border-b border-border bg-surface px-4 sm:px-5">
      <IconButton aria-label="Open navigation" onClick={onMenu} className="md:hidden"><Menu aria-hidden="true" className="size-5" /></IconButton>
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-lg font-semibold leading-tight tracking-[-0.01em]">{title}</h1>
        {meta && <p className="truncate font-mono text-xs font-medium text-ink-muted">{meta}</p>}
      </div>
      <div className="flex items-center gap-2">
        {status && <span className="hidden sm:contents"><StatusLabel presentation={status} /></span>}
        {results && (
          <Tooltip label={evidenceOpen ? "Close evidence" : "Open evidence"}>
            <IconButton aria-label={evidenceOpen ? "Close evidence panel" : "Open evidence panel"} aria-pressed={evidenceOpen} onClick={onEvidence}>
              <PanelRight aria-hidden="true" className="size-[19px]" />
            </IconButton>
          </Tooltip>
        )}
      </div>
    </header>
  );
}
