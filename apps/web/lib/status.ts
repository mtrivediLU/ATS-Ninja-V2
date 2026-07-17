import type { LucideIcon } from "lucide-react";
import {
  Check,
  CircleDashed,
  CloudOff,
  Clock3,
  FileWarning,
  Info,
  PencilLine,
  Scissors,
  ShieldAlert,
  TriangleAlert,
  X,
} from "lucide-react";

export type StatusTone = "positive" | "warning" | "danger" | "info" | "neutral" | "edited" | "unavailable";
export type KitLifecycleStatus = "pending" | "processing" | "completed" | "failed";
export type ClaimStatus = "supported" | "repaired" | "rejected";
export type EvidenceState = "supported" | "adjusted" | "removed" | "withheld" | "unavailable";
export type ArtifactPresentationState =
  | "generated"
  | "warning"
  | "withheld"
  | "not-requested"
  | "unavailable"
  | "failed"
  | "empty"
  | "edited"
  | "old-schema"
  | "partial";

export type StatusPresentation = {
  label: string;
  accessibleLabel: string;
  tone: StatusTone;
  icon: LucideIcon;
};

export const kitStatusPresentation: Record<KitLifecycleStatus, StatusPresentation> = {
  pending: { label: "Pending", accessibleLabel: "Kit status: Pending", tone: "neutral", icon: CircleDashed },
  processing: { label: "Processing", accessibleLabel: "Kit status: Processing", tone: "info", icon: Clock3 },
  completed: { label: "Completed", accessibleLabel: "Kit status: Completed", tone: "positive", icon: Check },
  failed: { label: "Failed", accessibleLabel: "Kit status: Failed", tone: "danger", icon: X },
};

export const claimStatusPresentation: Record<ClaimStatus, StatusPresentation> = {
  supported: {
    label: "Supported",
    accessibleLabel: "Claim status: Supported by evidence",
    tone: "positive",
    icon: Check,
  },
  repaired: {
    label: "Adjusted to remain accurate",
    accessibleLabel: "Claim status: Adjusted to remain accurate",
    tone: "warning",
    icon: TriangleAlert,
  },
  rejected: {
    label: "Withheld",
    accessibleLabel: "Claim status: Withheld because evidence was missing",
    tone: "danger",
    icon: ShieldAlert,
  },
};

export const evidenceStatePresentation: Record<EvidenceState, StatusPresentation> = {
  supported: claimStatusPresentation.supported,
  adjusted: claimStatusPresentation.repaired,
  removed: {
    label: "Removed because evidence was missing",
    accessibleLabel: "Claim status: Removed because evidence was missing",
    tone: "danger",
    icon: Scissors,
  },
  withheld: claimStatusPresentation.rejected,
  unavailable: {
    label: "Evidence unavailable",
    accessibleLabel: "Evidence status: Unavailable",
    tone: "unavailable",
    icon: CloudOff,
  },
};

export const notRequestedPresentation: StatusPresentation = {
  label: "Not requested",
  accessibleLabel: "Artifact status: Not requested",
  tone: "neutral",
  icon: Info,
};

export const withheldPresentation: StatusPresentation = {
  label: "Withheld",
  accessibleLabel: "Artifact status: Could not be generated safely and was withheld",
  tone: "danger",
  icon: ShieldAlert,
};

export const editedPresentation: StatusPresentation = {
  label: "Edited — not revalidated",
  accessibleLabel: "Artifact status: Edited locally and not revalidated",
  tone: "edited",
  icon: PencilLine,
};

export const unavailablePresentation: StatusPresentation = {
  label: "Artifact unavailable",
  accessibleLabel: "Artifact status: Unavailable",
  tone: "unavailable",
  icon: CloudOff,
};

export const artifactStatePresentation: Record<ArtifactPresentationState, StatusPresentation> = {
  generated: {
    label: "Generated",
    accessibleLabel: "Artifact status: Generated",
    tone: "positive",
    icon: Check,
  },
  warning: {
    label: "Ready with notes",
    accessibleLabel: "Artifact status: Generated with validation notes",
    tone: "warning",
    icon: TriangleAlert,
  },
  withheld: withheldPresentation,
  "not-requested": notRequestedPresentation,
  unavailable: unavailablePresentation,
  failed: {
    label: "Failed",
    accessibleLabel: "Artifact status: Failed",
    tone: "danger",
    icon: X,
  },
  empty: {
    label: "Empty",
    accessibleLabel: "Artifact status: Empty",
    tone: "unavailable",
    icon: FileWarning,
  },
  edited: editedPresentation,
  "old-schema": {
    label: "Older format",
    accessibleLabel: "Artifact status: Older format",
    tone: "neutral",
    icon: Info,
  },
  partial: {
    label: "Partially generated",
    accessibleLabel: "Artifact status: Partially generated",
    tone: "warning",
    icon: TriangleAlert,
  },
};
