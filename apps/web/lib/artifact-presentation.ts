import type { ArtifactValidation, Claim, DocumentState } from "@/lib/api-types";
import type { ArtifactPresentationState, EvidenceState } from "@/lib/status";

export type TrustCounts = {
  supported: number;
  adjusted: number;
  removed: number;
  withheld: number;
  warnings: number;
  total: number;
};

/**
 * This is a vocabulary adapter, not client-side grounding. The engine owns the
 * claim status and repair disposition; the browser only gives that persisted
 * state its D2 presentation name.
 */
export function evidenceStateForClaim(claim: Claim): EvidenceState {
  if (claim.status === "unavailable") return "unavailable";
  if (claim.status === "adjusted") return "adjusted";
  // The engine contract defines `repaired` as deterministic removal, never a
  // browser-side wording adjustment. Preserve that exact persisted outcome.
  if (claim.status === "repaired") return "removed";
  if (claim.status === "rejected") return "withheld";
  return "supported";
}

export function trustCounts(claims: Claim[], validation: ArtifactValidation): TrustCounts {
  const counts: TrustCounts = {
    supported: 0,
    adjusted: 0,
    removed: 0,
    withheld: 0,
    warnings: validation.warnings.length + validation.errors.length,
    total: claims.length,
  };
  for (const claim of claims) {
    const state = evidenceStateForClaim(claim);
    if (state !== "unavailable") counts[state] += 1;
  }
  return counts;
}

export function artifactPresentationState(
  validation: ArtifactValidation,
  text: string,
  manuallyEdited = false,
  deliveryState?: DocumentState,
): ArtifactPresentationState {
  if (manuallyEdited) return "edited";
  if (deliveryState === "generated_with_fallback") return text.trim() ? "generated-with-fallback" : "empty";
  if (deliveryState === "needs_input_review") return "needs-input-review";
  if (deliveryState === "failed") return "failed";
  if (deliveryState === "not_requested") return "not-requested";
  // A v7 delivery report is authoritative. In particular, do not hide a
  // delivered document because a legacy validation string was also retained.
  if (deliveryState === "generated") {
    if (!text.trim()) return "empty";
    if (validation.status === "repaired" || validation.warnings.length > 0 || validation.errors.length > 0) {
      return "warning";
    }
    return "generated";
  }
  if (validation.fatal || validation.status === "rejected") return "withheld";
  if (!text.trim()) return "empty";
  if (validation.status === "repaired" || validation.warnings.length > 0 || validation.errors.length > 0) return "warning";
  return "generated";
}

export function artifactLabelFromClaim(record: Pick<Claim, "artifact">): string {
  const labels: Record<string, string> = {
    resume: "Resume",
    cover_letter: "Cover letter",
    answers: "Application answers",
    job_fit: "Job fit",
    interview_prep: "Interview preparation",
    linkedin_outreach: "LinkedIn outreach",
  };
  return labels[record.artifact] ?? (record.artifact.replaceAll("_", " ") || "Artifact");
}
