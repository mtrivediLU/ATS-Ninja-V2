import type { KitRead } from "@/lib/api-types";
import { StatusLabel } from "@/components/ui/primitives";
import { formatDate, kitTarget } from "@/lib/product";
import { buildHeadline } from "@/lib/results-presentation";
import { kitStatusPresentation } from "@/lib/status";

/**
 * The results-first page's single H1: a personalized, honest delivery
 * headline with graceful fallbacks when the candidate name, job title, or
 * company could not be detected. Never fabricates a missing value.
 */
export function ResultsHeader({ kit }: { kit: KitRead }) {
  const target = kitTarget(kit);
  const hasCompany = target.company !== "Target company unavailable";
  const hasRole = target.role !== "Application kit";
  const name = kit.result?.resume?.document?.candidate_name?.trim() || "";
  const warningCount = kit.result?.validation.warning_count ?? 0;

  const headline = buildHeadline({ name, role: target.role, company: target.company, hasRole, hasCompany });
  const contextParts = [
    hasRole || hasCompany ? [hasRole ? target.role : "", hasCompany ? target.company : ""].filter(Boolean).join(" · ") : "Role and organization not detected.",
    kitStatusPresentation[kit.status].label,
    `Generated ${formatDate(kit.created_at)}`,
  ].filter(Boolean);

  return (
    <header className="border-b border-border-subtle pb-5">
      <h1 className="text-2xl font-bold tracking-[-0.01em] sm:text-[26px]">{headline}</h1>
      <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-secondary">
        {contextParts.map((part, index) => (
          <span key={part} className="inline-flex items-center gap-2">
            {index > 0 && <span aria-hidden="true" className="text-ink-muted">·</span>}
            {part}
          </span>
        ))}
        <StatusLabel presentation={kitStatusPresentation[kit.status]} className="ml-1" />
      </p>
      {warningCount > 0 && (
        <p className="mt-2 inline-flex items-center gap-1.5 rounded-pill border border-warning-border bg-warning-bg px-2.5 py-1 text-xs font-semibold text-warning">
          {warningCount} warning{warningCount === 1 ? "" : "s"} to review
        </p>
      )}
    </header>
  );
}
