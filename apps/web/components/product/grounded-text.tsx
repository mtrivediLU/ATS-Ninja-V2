"use client";

import { useEffect } from "react";
import { ShieldCheck } from "lucide-react";
import { useKit } from "@/components/product/kit-context";
import type { Claim } from "@/lib/api-types";
import { evidenceStateForClaim } from "@/lib/artifact-presentation";
import { evidenceStatePresentation } from "@/lib/status";

/**
 * The API deliberately does not provide character offsets for claims. We do
 * not guess them by matching browser text: trace markers are rendered as an
 * explicit, source-record list below the generated content instead.
 */
export function GroundedText({ text, claims, className = "" }: { text: string; claims: Claim[]; className?: string }) {
  const { selectedClaimId, highlightClaims, openEvidence } = useKit();

  useEffect(() => {
    if (!selectedClaimId) return;
    document.getElementById(`claim-marker-${selectedClaimId}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedClaimId]);

  return <div className={className}>
    <div className="whitespace-pre-wrap text-pretty leading-relaxed">{text}</div>
    {highlightClaims && claims.length > 0 && <aside aria-label="Available evidence markers" className="mt-5 border-t border-border-subtle pt-4"><p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted"><ShieldCheck aria-hidden="true" className="size-4 text-accent" />Evidence markers</p><p className="mt-1 text-xs text-ink-muted">Trace positions were not included by the API, so markers are listed without guessing text locations.</p><div className="mt-3 flex flex-wrap gap-2">{claims.map((claim) => { const state = evidenceStateForClaim(claim); const presentation = evidenceStatePresentation[state]; const Icon = presentation.icon; const tone = presentation.tone === "positive" ? "border-positive-border bg-positive-bg text-positive" : presentation.tone === "warning" ? "border-warning-border bg-warning-bg text-warning" : presentation.tone === "unavailable" ? "border-unavailable-border border-dashed bg-unavailable-bg text-unavailable" : "border-danger-border bg-danger-bg text-danger"; return <button key={claim.id} id={`claim-marker-${claim.id}`} type="button" onClick={() => openEvidence(claim.id)} className={`inline-flex min-h-10 max-w-full items-center gap-1.5 rounded-pill border px-3 py-1.5 text-left text-xs font-semibold ${tone} ${selectedClaimId === claim.id ? "outline-2 outline-offset-1 outline-accent" : ""}`}><Icon aria-hidden="true" className="size-3.5 shrink-0" /> <span className="max-w-[240px] truncate">{claim.text || "Claim record"}</span></button>; })}</div></aside>}
  </div>;
}
