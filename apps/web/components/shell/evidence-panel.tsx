"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, FileSearch, X } from "lucide-react";
import { useKit } from "@/components/product/kit-context";
import { IconButton, StatusLabel } from "@/components/ui/primitives";
import type { Claim, ClaimStatus } from "@/lib/api-types";
import { claimStatusPresentation } from "@/lib/status";

const filters = ["all", "supported", "repaired", "rejected"] as const;
type Filter = (typeof filters)[number];

function normalizedStatus(status: string): ClaimStatus {
  return status === "repaired" || status === "rejected" ? status : "supported";
}

export function EvidenceCard({ record, active, onSelect }: { record: Claim; active: boolean; onSelect?: () => void }) {
  const status = normalizedStatus(record.status);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-md border bg-surface p-3 text-left ${active ? "border-accent shadow-[0_0_0_2px_var(--accent-subtle-bg)]" : "border-border-subtle"}`}
      aria-pressed={onSelect ? active : undefined}
    >
      <StatusLabel presentation={claimStatusPresentation[status]} />
      <p className="mt-2 text-sm text-ink">{record.text || "Claim text unavailable"}</p>
      {record.reason && <p className="mt-2 text-xs text-ink-secondary">{record.reason}</p>}
      {record.evidence.length ? record.evidence.map((evidence, index) => (
        <div key={`${evidence.source}-${evidence.locator}-${index}`} className="mt-3 border-t border-border-subtle pt-3">
          <p className="font-mono text-xs font-medium text-ink-muted">{evidence.source || "source unavailable"} · {evidence.locator || "locator unavailable"}</p>
          {evidence.excerpt && <blockquote className="mt-2 border-l-2 border-border-strong pl-3 text-pretty text-sm italic text-ink-secondary">“{evidence.excerpt}”</blockquote>}
        </div>
      )) : <p className="mt-3 text-xs text-ink-muted">No bounded evidence excerpt was returned.</p>}
    </button>
  );
}

export function EvidencePanel({ onClose, compact = false }: { onClose?: () => void; compact?: boolean }) {
  const { claims, selectedClaimId, selectClaim, highlightClaims, setHighlightClaims } = useKit();
  const [filter, setFilter] = useState<Filter>("all");
  const filtered = useMemo(
    () => claims.filter((claim) => filter === "all" || normalizedStatus(claim.status) === filter),
    [claims, filter],
  );
  const activeIndex = filtered.findIndex((claim) => claim.id === selectedClaimId);

  function step(direction: number) {
    if (!filtered.length) return;
    const next = activeIndex < 0 ? 0 : (activeIndex + direction + filtered.length) % filtered.length;
    selectClaim(filtered[next].id);
    document.getElementById(`claim-${filtered[next].id}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  return (
    <aside aria-label="Evidence panel" className={compact ? "flex h-full flex-col" : "flex h-full w-[360px] flex-col border-l border-border bg-surface"}>
      {!compact && (
        <header className="flex min-h-[60px] items-center justify-between gap-3 border-b border-border-subtle px-4">
          <div><h2 className="text-md font-semibold leading-tight">Evidence</h2><p className="text-xs text-ink-muted">Real bounded claim trace</p></div>
          {onClose && <IconButton aria-label="Close evidence panel" onClick={onClose}><X aria-hidden="true" className="size-5" /></IconButton>}
        </header>
      )}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <p className="text-pretty text-sm text-ink-secondary">Why was ATS-Ninja allowed to say this? These fields are rendered directly from the ApplicationKit trace.</p>
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input type="checkbox" checked={highlightClaims} onChange={(event) => setHighlightClaims(event.target.checked)} className="size-5 accent-accent" />
          Highlight traced claims in text
        </label>
        <div className="flex flex-wrap gap-1" aria-label="Filter claims">
          {filters.map((value) => {
            const count = value === "all" ? claims.length : claims.filter((claim) => normalizedStatus(claim.status) === value).length;
            return <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)} className="min-h-9 rounded-pill border border-border px-3 text-xs capitalize text-ink-secondary aria-pressed:border-border-strong aria-pressed:bg-surface-raised aria-pressed:font-semibold aria-pressed:text-ink">{value} {count}</button>;
          })}
        </div>
        <div className="flex items-center justify-between border-y border-border-subtle py-2">
          <span className="font-mono text-xs text-ink-muted">{activeIndex >= 0 ? `Claim ${activeIndex + 1} of ${filtered.length}` : `${filtered.length} claims`}</span>
          <span className="flex gap-1"><IconButton aria-label="Previous claim" onClick={() => step(-1)} disabled={!filtered.length}><ChevronLeft aria-hidden="true" className="size-5" /></IconButton><IconButton aria-label="Next claim" onClick={() => step(1)} disabled={!filtered.length}><ChevronRight aria-hidden="true" className="size-5" /></IconButton></span>
        </div>
        {!filtered.length ? (
          <div className="rounded-md border border-dashed border-border-strong bg-surface-subtle p-5 text-center"><FileSearch aria-hidden="true" className="mx-auto size-7 text-ink-muted" /><p className="mt-2 text-sm font-semibold">No evidence records</p><p className="mt-1 text-xs text-ink-muted">This artifact returned no claims matching the selected filter.</p></div>
        ) : filtered.map((claim) => <EvidenceCard key={claim.id} record={claim} active={selectedClaimId === claim.id} onSelect={() => { selectClaim(claim.id); document.getElementById(`claim-${claim.id}`)?.scrollIntoView({ block: "center", behavior: "smooth" }); }} />)}
      </div>
    </aside>
  );
}
