"use client";

import { useEffect, useMemo } from "react";
import { useKit } from "@/components/product/kit-context";
import type { Claim } from "@/lib/api-types";

type Segment = { text: string; claim?: Claim };

function segmentsFor(text: string, claims: Claim[]): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  const unused = claims.filter((claim) => claim.text.trim().length >= 3);
  while (cursor < text.length) {
    let nextClaim: Claim | undefined;
    let nextIndex = -1;
    for (const claim of unused) {
      const index = text.indexOf(claim.text, cursor);
      if (index >= 0 && (nextIndex < 0 || index < nextIndex)) {
        nextClaim = claim;
        nextIndex = index;
      }
    }
    if (!nextClaim || nextIndex < 0) {
      segments.push({ text: text.slice(cursor) });
      break;
    }
    if (nextIndex > cursor) segments.push({ text: text.slice(cursor, nextIndex) });
    segments.push({ text: nextClaim.text, claim: nextClaim });
    cursor = nextIndex + nextClaim.text.length;
    unused.splice(unused.indexOf(nextClaim), 1);
  }
  return segments;
}

export function GroundedText({ text, claims, className = "" }: { text: string; claims: Claim[]; className?: string }) {
  const { selectedClaimId, highlightClaims, openEvidence } = useKit();
  const segments = useMemo(() => segmentsFor(text, claims), [claims, text]);

  useEffect(() => {
    if (!selectedClaimId) return;
    document.getElementById(`claim-${selectedClaimId}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedClaimId]);

  return <div className={`whitespace-pre-wrap text-pretty leading-relaxed ${className}`}>{segments.map((segment, index) => {
    if (!segment.claim) return <span key={index}>{segment.text}</span>;
    const status = segment.claim.status === "repaired" || segment.claim.status === "rejected" ? segment.claim.status : "supported";
    return <button key={`${segment.claim.id}-${index}`} id={`claim-${segment.claim.id}`} type="button" onClick={() => openEvidence(segment.claim?.id)} className={`rounded-sm border-b-2 px-0.5 text-left ${highlightClaims ? status === "supported" ? "border-positive-border bg-positive-bg" : status === "repaired" ? "border-warning-border bg-warning-bg" : "border-danger-border bg-danger-bg line-through" : "border-transparent"} ${selectedClaimId === segment.claim.id ? "outline-2 outline-offset-1 outline-accent" : ""}`} title={`Open evidence: ${status}`}>{segment.text}{status === "repaired" && <span className="ml-1 font-mono text-xs text-warning">⚠ repaired</span>}</button>;
  })}</div>;
}
