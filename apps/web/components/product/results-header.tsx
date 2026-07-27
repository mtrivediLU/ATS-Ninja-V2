"use client";

import { useEffect, useState } from "react";
import type { KitRead } from "@/lib/api-types";
import { Field, Input, StatusLabel } from "@/components/ui/primitives";
import { effectiveKitStatus, formatDate, kitTarget } from "@/lib/product";
import { buildHeadline } from "@/lib/results-presentation";
import { kitStatusPresentation } from "@/lib/status";

/**
 * The results-first page's single H1: a personalized, honest delivery
 * headline with graceful fallbacks when the candidate name, job title, or
 * company could not be detected. Never fabricates a missing value.
 */
export function ResultsHeader({ kit }: { kit: KitRead }) {
  const target = kitTarget(kit);
  const initialCompany = target.company === "Target company unavailable" ? "" : target.company;
  const initialRole = target.role === "Application kit" ? "" : target.role;
  const [company, setCompany] = useState(initialCompany);
  const [role, setRole] = useState(initialRole);
  const [targetReviewed, setTargetReviewed] = useState(false);
  useEffect(() => {
    setCompany(initialCompany);
    setRole(initialRole);
    setTargetReviewed(false);
  }, [initialCompany, initialRole, kit.id]);
  const hasCompany = Boolean(company.trim());
  const hasRole = Boolean(role.trim());
  const name = kit.result?.resume?.document?.candidate_name?.trim() || "";
  const warningCount = kit.result?.validation.warning_count ?? 0;
  const lowTargetConfidence = target.confidence !== null && target.confidence < 0.7;
  const lifecycle = effectiveKitStatus(kit);
  const headlineLifecycle = lifecycle === "pending" || lifecycle === "processing" ? "completed" : lifecycle;

  const headline = buildHeadline({ name, role: role.trim(), company: company.trim(), hasRole, hasCompany, lifecycle: headlineLifecycle, targetConfirmed: !lowTargetConfidence || targetReviewed });
  // Completion state is shown once, via the StatusLabel pill below — it must
  // not also appear as plain text in this joined context line.
  const contextParts = [
    hasRole || hasCompany ? [hasRole ? role.trim() : "", hasCompany ? company.trim() : ""].filter(Boolean).join(" · ") : "Role and organization not detected.",
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
        <StatusLabel presentation={kitStatusPresentation[lifecycle]} className="ml-1" />
      </p>
      {warningCount > 0 && (
        <p className="mt-2 inline-flex items-center gap-1.5 rounded-pill border border-warning-border bg-warning-bg px-2.5 py-1 text-xs font-semibold text-warning">
          {warningCount} warning{warningCount === 1 ? "" : "s"} to review
        </p>
      )}
      {lowTargetConfidence && (
        <fieldset className="mt-4 rounded-md border border-warning-border bg-warning-bg p-4">
          <legend className="px-1 text-sm font-semibold text-warning">Is this right?</legend>
          <p id="target-confidence-help" className="text-sm text-ink-secondary">
            Target detection confidence was low. Correct these fields for this view before reviewing the Kit.
            These local edits do not change generated documents.
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label="Target role" htmlFor="target-role-review">
              <Input
                id="target-role-review"
                value={role}
                onChange={(event) => { setRole(event.target.value); setTargetReviewed(true); }}
                aria-describedby="target-confidence-help"
              />
            </Field>
            <Field label="Target company" htmlFor="target-company-review">
              <Input
                id="target-company-review"
                value={company}
                onChange={(event) => { setCompany(event.target.value); setTargetReviewed(true); }}
                aria-describedby="target-confidence-help"
              />
            </Field>
          </div>
        </fieldset>
      )}
    </header>
  );
}
