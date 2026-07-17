"use client";

import { useEffect, useMemo, useRef } from "react";
import { ChevronLeft, ChevronRight, FileSearch, RotateCcw, X } from "lucide-react";
import { useKit } from "@/components/product/kit-context";
import { IconButton, Select, StatusLabel } from "@/components/ui/primitives";
import type { Claim } from "@/lib/api-types";
import { artifactLabelFromClaim, evidenceStateForClaim } from "@/lib/artifact-presentation";
import { evidenceStatePresentation, type EvidenceState } from "@/lib/status";

const filters: Array<"all" | EvidenceState> = ["all", "supported", "adjusted", "removed", "withheld", "unavailable"];

export function EvidenceCard({ record, active, onSelect }: { record: Claim; active: boolean; onSelect?: () => void }) {
  const state = evidenceStateForClaim(record);
  const presentation = evidenceStatePresentation[state];
  const reasonLabel = state === "adjusted" ? "Why adjusted" : state === "removed" ? "Why removed" : state === "withheld" ? "Why withheld" : "Validation context";
  return <button type="button" onClick={onSelect} className={`w-full rounded-md border bg-surface p-3 text-left ${active ? "border-accent shadow-[0_0_0_2px_var(--accent-subtle-bg)]" : state === "unavailable" ? "border-unavailable-border border-dashed" : "border-border-subtle"}`} aria-pressed={onSelect ? active : undefined}>
    <div className="flex flex-wrap items-center gap-2"><StatusLabel presentation={presentation} /><span className="rounded-pill border border-neutral-border bg-neutral-bg px-2 py-0.5 text-xs font-semibold text-neutral">{artifactLabelFromClaim(record)}</span>{record.disposition && <span className="rounded-pill border border-border bg-surface-subtle px-2 py-0.5 font-mono text-[11px] text-ink-secondary">{record.disposition}</span>}</div>
    <p className="mt-3 text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">Generated claim</p><p className="mt-1 text-sm text-ink">{record.text || "Claim text unavailable"}</p>
    {state === "unavailable" ? <p className="mt-3 rounded-sm border border-dashed border-unavailable-border bg-unavailable-bg p-3 text-xs text-unavailable">Evidence unavailable for this trace record. Reopen the Kit to retrieve the persisted response; the claim itself was not changed in the browser.</p> : record.evidence.length ? record.evidence.map((evidence, index) => <div key={`${evidence.source}-${evidence.locator}-${index}`} className="mt-3 border-t border-border-subtle pt-3"><p className="font-mono text-xs font-medium text-ink-muted">{evidence.source || "source unavailable"} · {evidence.locator || "locator unavailable"}</p>{evidence.excerpt && <blockquote className="mt-2 border-l-2 border-border-strong pl-3 text-pretty text-sm italic text-ink-secondary">“{evidence.excerpt}”</blockquote>}</div>) : <p className="mt-3 text-xs text-ink-muted">No supporting candidate excerpt was returned for this removed or withheld trace record.</p>}
    {record.reason && <p className="mt-3 text-xs text-ink-secondary"><strong>{reasonLabel}:</strong> {record.reason}</p>}
  </button>;
}

export function EvidencePanel({ onClose, compact = false }: { onClose?: () => void; compact?: boolean }) {
  const { claims, selectedClaimId, selectClaim, highlightClaims, setHighlightClaims, evidenceStatusFilter, evidenceArtifactFilter, setEvidenceFilters } = useKit();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const artifacts = useMemo(() => Array.from(new Set(claims.map((claim) => claim.artifact))).sort(), [claims]);
  const filtered = useMemo(() => claims.filter((claim) => (evidenceStatusFilter === "all" || evidenceStateForClaim(claim) === evidenceStatusFilter) && (evidenceArtifactFilter === "all" || claim.artifact === evidenceArtifactFilter)), [claims, evidenceArtifactFilter, evidenceStatusFilter]);
  const activeIndex = filtered.findIndex((claim) => claim.id === selectedClaimId);

  useEffect(() => { window.requestAnimationFrame(() => headingRef.current?.focus()); }, []);
  useEffect(() => {
    const step = (direction: number) => {
      if (!filtered.length) return;
      const next = activeIndex < 0 ? 0 : (activeIndex + direction + filtered.length) % filtered.length;
      const claim = filtered[next];
      selectClaim(claim.id);
      document.getElementById(`claim-marker-${claim.id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (/input|textarea|select/i.test((document.activeElement as HTMLElement | null)?.tagName ?? "")) return;
      if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
      if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [activeIndex, filtered, selectClaim]);

  function step(direction: number) {
    if (!filtered.length) return;
    const next = activeIndex < 0 ? 0 : (activeIndex + direction + filtered.length) % filtered.length;
    selectClaim(filtered[next].id);
    document.getElementById(`claim-marker-${filtered[next].id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function clearFilters() { setEvidenceFilters({ status: "all", artifact: "all" }); }

  return <aside aria-label="Evidence panel" className={compact ? "flex h-full flex-col" : "flex h-full w-[360px] flex-col border-l border-border bg-surface"}>
    {!compact && <header className="flex min-h-[60px] items-center justify-between gap-3 border-b border-border-subtle px-4"><div><h2 ref={headingRef} tabIndex={-1} className="text-md font-semibold leading-tight">Evidence</h2><p className="text-xs text-ink-muted">Bounded claim trace</p></div>{onClose && <IconButton aria-label="Close evidence panel" onClick={onClose}><X aria-hidden="true" className="size-5" /></IconButton>}</header>}
    {compact && <h2 ref={headingRef} tabIndex={-1} className="sr-only">Evidence</h2>}
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
      <p className="text-pretty text-sm text-ink-secondary">Why was ATS-Ninja allowed to say this? These are bounded fields returned by the ApplicationKit trace. Use ← and → to move through the filtered trace.</p>
      <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" checked={highlightClaims} onChange={(event) => setHighlightClaims(event.target.checked)} className="size-5 accent-accent" />Show available trace markers</label>
      <fieldset><legend className="text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">Status filter</legend><div className="mt-2 flex flex-wrap gap-1">{filters.map((value) => { const count = value === "all" ? claims.length : claims.filter((claim) => evidenceStateForClaim(claim) === value).length; const label = value === "all" ? "All" : evidenceStatePresentation[value].label; return <button key={value} type="button" aria-pressed={evidenceStatusFilter === value} onClick={() => setEvidenceFilters({ status: value })} className="min-h-9 rounded-pill border border-border px-3 text-xs text-ink-secondary aria-pressed:border-border-strong aria-pressed:bg-surface-raised aria-pressed:font-semibold aria-pressed:text-ink">{label} {count}</button>; })}</div></fieldset>
      <label className="block text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">Artifact filter<Select aria-label="Artifact filter" value={evidenceArtifactFilter} onChange={(event) => setEvidenceFilters({ artifact: event.target.value })} className="mt-2 text-sm normal-case tracking-normal"><option value="all">All artifacts</option>{artifacts.map((artifact) => <option key={artifact} value={artifact}>{artifactLabelFromClaim({ artifact })}</option>)}</Select></label>
      {(evidenceStatusFilter !== "all" || evidenceArtifactFilter !== "all") && <button type="button" onClick={clearFilters} className="inline-flex min-h-10 items-center gap-2 text-sm font-semibold text-accent hover:underline"><RotateCcw aria-hidden="true" className="size-4" />Clear filters</button>}
      <div className="flex items-center justify-between border-y border-border-subtle py-2"><span className="font-mono text-xs text-ink-muted">{activeIndex >= 0 ? `Claim ${activeIndex + 1} of ${filtered.length}` : `${filtered.length} matching claims`}</span><span className="flex gap-1"><IconButton aria-label="Previous claim" onClick={() => step(-1)} disabled={!filtered.length}><ChevronLeft aria-hidden="true" className="size-5" /></IconButton><IconButton aria-label="Next claim" onClick={() => step(1)} disabled={!filtered.length}><ChevronRight aria-hidden="true" className="size-5" /></IconButton></span></div>
      {!filtered.length ? <div className="rounded-md border border-dashed border-border-strong bg-surface-subtle p-5 text-center"><FileSearch aria-hidden="true" className="mx-auto size-7 text-ink-muted" /><p className="mt-2 text-sm font-semibold">No matching claims</p><p className="mt-1 text-xs text-ink-muted">No returned trace records match these filters.</p><button type="button" onClick={clearFilters} className="mt-3 text-sm font-semibold text-accent hover:underline">Clear filters</button></div> : filtered.map((claim) => <EvidenceCard key={claim.id} record={claim} active={selectedClaimId === claim.id} onSelect={() => { selectClaim(claim.id); document.getElementById(`claim-marker-${claim.id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }} />)}
    </div>
  </aside>;
}
