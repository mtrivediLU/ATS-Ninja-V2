import type { ApplicationKit, Claim, KitRead } from "@/lib/api-types";

export const artifactKeys = [
  "resume",
  "cover_letter",
  "answers",
  "job_fit",
  "interview_prep",
  "linkedin_outreach",
] as const;

export type ArtifactKey = (typeof artifactKeys)[number];

export function allClaims(result: ApplicationKit | null): Claim[] {
  if (!result) return [];
  return artifactKeys.flatMap((key) => result[key]?.claims ?? []);
}

export function kitTarget(kit: KitRead | null): { company: string; role: string } {
  const outreach = kit?.result?.linkedin_outreach;
  const draft = outreach?.drafts[0];
  const companyRef = outreach?.target_context.find((ref) => ref.field === "company");
  const roleRef = outreach?.target_context.find((ref) => ref.field === "role");
  return {
    company: draft?.target_company || companyRef?.excerpt || "Target company unavailable",
    role: draft?.target_role || roleRef?.excerpt || "Application kit",
  };
}

export function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function safeFilename(...parts: string[]): string {
  const joined = parts.filter(Boolean).join("-").toLowerCase();
  const safe = joined
    .normalize("NFKD")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .slice(0, 80);
  return safe || "ats-ninja-artifact";
}

export async function copyText(text: string): Promise<void> {
  if (!text) throw new Error("Nothing is available to copy.");
  await navigator.clipboard.writeText(text);
}

export function downloadText(text: string, filename: string, mime = "text/plain;charset=utf-8"): void {
  if (!text) throw new Error("Nothing is available to download.");
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
