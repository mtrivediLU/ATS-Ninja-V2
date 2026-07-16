import type { ClaimStatus, KitLifecycleStatus } from "@/lib/status";

export const demoKit = {
  id: "kit_demo_7f3a92",
  role: "Senior Data Analyst",
  company: "Example Labs",
  schemaVersion: "application-kit/v4",
  status: "completed" as KitLifecycleStatus,
};

export type DemoEvidenceRecord = {
  id: string;
  status: ClaimStatus;
  claim: string;
  source: string;
  locator: string;
  excerpt: string;
};

export const demoEvidence: DemoEvidenceRecord[] = [
  {
    id: "ev-supported",
    status: "supported",
    claim: "Built SQL reporting pipelines for operations teams.",
    source: "candidate-resume",
    locator: "experience:0 · L14",
    excerpt: "Built SQL reporting pipelines used by operations teams.",
  },
  {
    id: "ev-repaired",
    status: "repaired",
    claim: "An unsupported performance percentage was removed.",
    source: "grounding",
    locator: "repair:claim-08",
    excerpt: "The source supported the work, but not the proposed percentage.",
  },
  {
    id: "ev-rejected",
    status: "rejected",
    claim: "A certification claim was removed because no evidence was present.",
    source: "validation",
    locator: "rejected:claim-11",
    excerpt: "No matching certification appeared in the bounded candidate evidence.",
  },
];

export const demoHistory = [
  { id: "kit_demo_7f3a92", role: "Senior Data Analyst", company: "Example Labs", status: "completed" as const, when: "2m ago" },
  { id: "kit_demo_5b1c04", role: "BI Engineer", company: "Sample Freight", status: "completed" as const, when: "Yesterday" },
  { id: "kit_demo_2e88af", role: "Analytics Lead", company: "Demo Health", status: "processing" as const, when: "Just now" },
  { id: "kit_demo_9a41d7", role: "Data Engineer", company: "Example Systems", status: "failed" as const, when: "Monday" },
];
