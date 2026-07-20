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
  // Target company/role is only carried as an explicit field on the LinkedIn
  // outreach draft and the cover letter document — both are optional,
  // independently-requested artifacts. Reading only one of them meant the
  // header showed "unavailable" whenever that one artifact wasn't requested,
  // even though the other (or the JD parse behind it) had the same
  // already-extracted value. Check every artifact that carries it before
  // falling back to "unavailable" — never guess from arbitrary prose.
  const outreach = kit?.result?.linkedin_outreach;
  const draft = outreach?.drafts[0];
  const companyRef = outreach?.target_context.find((ref) => ref.field === "company");
  const roleRef = outreach?.target_context.find((ref) => ref.field === "role");
  const coverDocument = kit?.result?.cover_letter?.document;
  return {
    company:
      draft?.target_company || companyRef?.excerpt || coverDocument?.recipient_company || "Target company unavailable",
    role: draft?.target_role || roleRef?.excerpt || coverDocument?.target_role || "Application kit",
  };
}

/**
 * Turn internal validation error/warning strings into a safe, specific,
 * user-facing withheld reason with an actionable next step.
 *
 * Persisted validation records are diagnostic text for engineers (e.g.
 * `"completeness: resume has 1 experience entries, source has 6"`) and must
 * never be shown verbatim — they can reference internal category names and,
 * in principle, an unusual failure could echo more than intended. `errors`
 * carries the fatal/rejection reason; `warnings` is a fallback for
 * non-fatal-but-withheld cases. Returns `undefined` (letting the caller fall
 * back to the generic message) when no recognized category matches.
 */
export function safeWithheldReason(errors: string[], warnings: string[]): string | undefined {
  const combined = [...errors, ...warnings].join(" ").toLowerCase();
  if (!combined) return undefined;

  if (combined.includes("completeness:")) {
    return "Resume structure could not be generated safely: the uploaded text appears structurally incomplete, so one or more sections could not be carried through. Review the extracted Resume text for missing headings or bullet points, or try uploading a text-based PDF, DOCX, or TXT file, then create a new Kit.";
  }
  if (
    combined.includes("unsupported") ||
    combined.includes("invented") ||
    combined.includes("tier c term") ||
    combined.includes("official title altered") ||
    combined.includes("retired email")
  ) {
    return "One or more unsupported claims could not be repaired without risking a fabricated statement. Remove or correct the flagged content in your source Resume, then create a new Kit.";
  }
  if (combined.includes("email not present")) {
    return "Candidate identity details required to validate this artifact were unavailable. Confirm your name and contact details are present in the source Resume, then create a new Kit.";
  }
  if (
    combined.includes("end{document}") ||
    combined.includes("unbalanced braces") ||
    combined.includes("resumesubheading") ||
    combined.includes("resumeitem") ||
    combined.includes("malformed latex") ||
    combined.includes("stray macro") ||
    combined.includes("escaped")
  ) {
    return "Resume structure could not be generated safely from the available content. Try uploading a text-based PDF, or use DOCX or TXT, then create a new Kit.";
  }
  return undefined;
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

/** A concise filename for template exports; unavailable target values are omitted. */
export function templateFilename(company: string, role: string, artifact: "resume" | "cover-letter", template: "classic" | "modern"): string {
  const usable = (value: string): string => value === "Target company unavailable" || value === "Application kit" ? "" : value;
  return safeFilename(usable(company), usable(role), artifact, template, "ats");
}

export async function copyText(text: string): Promise<void> {
  if (!text) throw new Error("Nothing is available to copy.");
  await navigator.clipboard.writeText(text);
}

export function downloadText(text: string, filename: string, mime = "text/plain;charset=utf-8"): void {
  if (!text) throw new Error("Nothing is available to download.");
  downloadBlob(new Blob([text], { type: mime }), filename);
}

/** Triggers a direct browser download of an already-fetched blob (e.g. a PDF). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
