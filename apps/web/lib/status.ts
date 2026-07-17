import type { LucideIcon } from "lucide-react";
import { Ban, Check, CircleDashed, Clock3, Info, ShieldAlert, TriangleAlert, X } from "lucide-react";

export type StatusTone = "positive" | "warning" | "danger" | "info" | "neutral";
export type KitLifecycleStatus = "pending" | "processing" | "completed" | "failed";
export type ClaimStatus = "supported" | "repaired" | "rejected";

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
    label: "Removed because evidence was missing",
    accessibleLabel: "Claim status: Removed because evidence was missing",
    tone: "danger",
    icon: Ban,
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
