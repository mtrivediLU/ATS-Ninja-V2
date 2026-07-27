"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AnswersWorkspace } from "@/components/product/document-workspaces";
import { ArtifactSummarySection } from "@/components/product/artifact-summary-section";
import { ChangeLedger } from "@/components/product/change-ledger";
import { ExpandableArtifact } from "@/components/product/expandable-artifact";
import { InterviewWorkspace } from "@/components/product/interview-workspace";
import { JobFitWorkspace } from "@/components/product/job-fit-workspace";
import { KitLineageActions } from "@/components/product/kit-lineage";
import { KitTrustStrip } from "@/components/product/kit-trust-strip";
import { MatchInsights } from "@/components/product/match-insights";
import { OutreachWorkspace } from "@/components/product/outreach-workspace";
import { Button, Card } from "@/components/ui/primitives";
import { artifactPresentationState } from "@/lib/artifact-presentation";
import type { ApplicationKit, DocumentState, KitRead } from "@/lib/api-types";
import type { ArtifactPresentationState } from "@/lib/status";

// All seven large content subsections behind the advanced entry. Only one is
// ever open at a time, regardless of which group (match insights / trust /
// tailoring changes, or the four artifact workspaces) it belongs to.
type Subsection =
  | "match-insights"
  | "trust-evidence"
  | "tailoring-changes"
  | "answers"
  | "job-fit"
  | "interview-prep"
  | "linkedin-outreach";

/**
 * The single quiet advanced entry: "View detailed analysis and evidence".
 * The main results page is complete and useful without opening this. Behind
 * it: the full match-report breakdown, trust and evidence, tailoring change
 * ledgers, application answers, job-fit requirement assessment, interview
 * prep, and LinkedIn outreach — seven large subsections, only one of which is
 * ever expanded at a time. Kit lineage (regenerate / revision history) is a
 * compact, always-visible control row, not a large subsection.
 */
export function AdvancedDetails({
  kit,
  result,
  target,
  onCopyAnswers,
  onCopyOutreach,
  onRefresh,
}: {
  kit: KitRead;
  result: ApplicationKit;
  target: { company: string; role: string };
  onCopyAnswers: () => void;
  onCopyOutreach: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [openSubsection, setOpenSubsection] = useState<Subsection | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = "advanced-details-panel";

  useEffect(() => {
    if (open) window.requestAnimationFrame(() => panelRef.current?.focus());
  }, [open]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && open) {
        event.preventDefault();
        setOpen(false);
        window.requestAnimationFrame(() => triggerRef.current?.focus());
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);

  const answerState = result.answers
    ? artifactPresentationState(
        result.answers.validation,
        result.answers.text,
        false,
        result.delivery_reports?.answers?.state,
      )
    : kit.include_application_answers
      ? missingArtifactState(result.delivery_reports?.answers?.state)
      : "not-requested";
  const fitState = result.job_fit
    ? artifactPresentationState(
        result.job_fit.validation,
        result.job_fit.summary,
        false,
        result.delivery_reports?.job_fit?.state,
      )
    : kit.include_job_fit
      ? missingArtifactState(result.delivery_reports?.job_fit?.state)
      : "not-requested";
  const interviewState = result.interview_prep
    ? artifactPresentationState(
        result.interview_prep.validation,
        result.interview_prep.strategy_summary,
        false,
        result.delivery_reports?.interview_prep?.state,
      )
    : kit.include_interview_prep
      ? missingArtifactState(result.delivery_reports?.interview_prep?.state)
      : "not-requested";
  const outreachState = result.linkedin_outreach
    ? artifactPresentationState(
        result.linkedin_outreach.validation,
        result.linkedin_outreach.strategy_summary,
        false,
        result.delivery_reports?.linkedin_outreach?.state,
      )
    : kit.include_linkedin_outreach
      ? missingArtifactState(result.delivery_reports?.linkedin_outreach?.state)
      : "not-requested";

  const hasChanges = Boolean(result.resume?.change_ledger?.length || result.cover_letter?.change_ledger?.length);
  const changeCount = (result.resume?.change_ledger?.length ?? 0) + (result.cover_letter?.change_ledger?.length ?? 0);

  return (
    <section className="mt-8 border-t border-border-subtle pt-6">
      <Button ref={triggerRef} variant="secondary" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronUp aria-hidden="true" className="size-4" /> : <ChevronDown aria-hidden="true" className="size-4" />}
        {open ? "Hide detailed analysis and evidence" : "View detailed analysis and evidence"}
      </Button>
      {open && (
        <div id={panelId} ref={panelRef} tabIndex={-1} className="mt-5 space-y-4">
          <KitLineageActions kitId={kit.id} parentKitId={kit.parent_kit_id} revision={kit.revision} />

          {result.match_report && (
            <SubsectionRow
              id="match-insights"
              title="Match insights"
              summary={`${result.match_report.fit_category.replace(/_/g, " ")} · ${result.match_report.confidence} confidence`}
              expanded={openSubsection === "match-insights"}
              onExpandedChange={(next) => setOpenSubsection(next ? "match-insights" : null)}
            >
              <MatchInsights report={result.match_report} />
            </SubsectionRow>
          )}

          <SubsectionRow
            id="trust-evidence"
            title="Trust and evidence"
            summary={
              result.validation.passed
                ? `No blocking issues · ${result.validation.warning_count} warning${result.validation.warning_count === 1 ? "" : "s"}`
                : `Issues need review · ${result.validation.warning_count} warning${result.validation.warning_count === 1 ? "" : "s"}`
            }
            expanded={openSubsection === "trust-evidence"}
            onExpandedChange={(next) => setOpenSubsection(next ? "trust-evidence" : null)}
          >
            <KitTrustStrip />
          </SubsectionRow>

          {hasChanges && (
            <SubsectionRow
              id="tailoring-changes"
              title="Detailed tailoring changes"
              summary={`${changeCount} change${changeCount === 1 ? "" : "s"} · transparent and reversible, except permanent truth-grounding removals`}
              expanded={openSubsection === "tailoring-changes"}
              onExpandedChange={(next) => setOpenSubsection(next ? "tailoring-changes" : null)}
            >
              {result.resume && result.resume.change_ledger.length > 0 && (
                <ChangeLedger kitId={kit.id} records={result.resume.change_ledger} revision={kit.revision} onApplied={onRefresh} title="Resume changes" />
              )}
              {result.cover_letter && result.cover_letter.change_ledger.length > 0 && (
                <ChangeLedger kitId={kit.id} records={result.cover_letter.change_ledger} revision={kit.revision} onApplied={onRefresh} title="Cover letter changes" />
              )}
            </SubsectionRow>
          )}

          <ArtifactSummarySection
            artifact="answers"
            title="Application answers"
            state={answerState}
            summary={
              result.answers
                ? `${result.answers.items.length} questions · ${result.answers.items.length - result.answers.placeholders.length} completed · ${result.answers.placeholders.length} withheld or placeholder`
                : "Not returned for this Kit."
            }
            primaryLabel="Copy all answers"
            onPrimary={onCopyAnswers}
            onRetry={() => void onRefresh()}
            expanded={openSubsection === "answers"}
            onExpandedChange={(next) => setOpenSubsection(next ? "answers" : null)}
            kitId={kit.id}
            route="answers"
          >
            {result.answers && <AnswersWorkspace artifact={result.answers} company={target.company} role={target.role} deliveryState={result.delivery_reports?.answers?.state} />}
          </ArtifactSummarySection>
          <ArtifactSummarySection
            artifact="job-fit"
            title="Complete requirement assessment"
            state={fitState}
            summary={
              result.job_fit
                ? `${result.job_fit.fit_band} · ${result.job_fit.requirement_coverage_score} coverage · ${result.job_fit.must_have_gaps.length} must-have gaps · ${result.job_fit.genuine_gaps.length} genuine gaps`
                : "Not returned for this Kit."
            }
            primaryLabel="View full assessment"
            onPrimary={() => setOpenSubsection("job-fit")}
            onRetry={() => void onRefresh()}
            expanded={openSubsection === "job-fit"}
            onExpandedChange={(next) => setOpenSubsection(next ? "job-fit" : null)}
            kitId={kit.id}
            route="job-fit"
          >
            {result.job_fit && <JobFitWorkspace artifact={result.job_fit} company={target.company} role={target.role} deliveryState={result.delivery_reports?.job_fit?.state} />}
          </ArtifactSummarySection>
          <ArtifactSummarySection
            artifact="interview-prep"
            title="Interview preparation"
            state={interviewState}
            summary={
              result.interview_prep
                ? `${result.interview_prep.questions.length} questions · ${result.interview_prep.focus_areas.length} focus areas · ${result.interview_prep.star_stories.filter((story) => story.completeness === "complete").length} complete STAR candidates`
                : "Not returned for this Kit."
            }
            primaryLabel="Start review"
            onPrimary={() => setOpenSubsection("interview-prep")}
            onRetry={() => void onRefresh()}
            expanded={openSubsection === "interview-prep"}
            onExpandedChange={(next) => setOpenSubsection(next ? "interview-prep" : null)}
            kitId={kit.id}
            route="interview-prep"
          >
            {result.interview_prep && <InterviewWorkspace artifact={result.interview_prep} company={target.company} role={target.role} deliveryState={result.delivery_reports?.interview_prep?.state} />}
          </ArtifactSummarySection>
          <ArtifactSummarySection
            artifact="linkedin-outreach"
            title="LinkedIn outreach"
            state={outreachState}
            summary={
              result.linkedin_outreach
                ? `${result.linkedin_outreach.drafts.length} drafts · Draft only / LinkedIn not connected`
                : "Not returned for this Kit."
            }
            primaryLabel="Copy recommended draft"
            onPrimary={onCopyOutreach}
            onRetry={() => void onRefresh()}
            expanded={openSubsection === "linkedin-outreach"}
            onExpandedChange={(next) => setOpenSubsection(next ? "linkedin-outreach" : null)}
            kitId={kit.id}
            route="linkedin-outreach"
          >
            {result.linkedin_outreach && <OutreachWorkspace artifact={result.linkedin_outreach} company={target.company} role={target.role} deliveryState={result.delivery_reports?.linkedin_outreach?.state} />}
          </ArtifactSummarySection>
        </div>
      )}
    </section>
  );
}

function missingArtifactState(deliveryState?: DocumentState): ArtifactPresentationState {
  if (deliveryState === "needs_input_review") return "needs-input-review";
  if (deliveryState === "failed") return "failed";
  if (deliveryState === "not_requested") return "not-requested";
  return "unavailable";
}

/**
 * A collapsible row for a large subsection that is not a requested/withheld
 * "artifact" in `ArtifactSummarySection`'s sense (match insights, trust and
 * evidence, tailoring changes) — same visual chrome and the same
 * `ExpandableArtifact` expand/collapse primitive (aria-expanded/aria-controls,
 * focus in/out, Escape-to-collapse), so it participates in the same
 * single-open coordination as the artifact rows above.
 */
function SubsectionRow({
  id,
  title,
  summary,
  expanded,
  onExpandedChange,
  children,
}: {
  id: string;
  title: string;
  summary: string;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <article id={id} className="k1-artifact-row">
      <Card className="shadow-none">
        <div className="flex min-h-[var(--artifact-row-min-h)] flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold">{title}</h3>
            <p className="mt-1 text-sm text-ink-muted">{summary}</p>
          </div>
          <ExpandableArtifact artifact={id} expanded={expanded} onExpandedChange={onExpandedChange} label="Open">
            {children}
          </ExpandableArtifact>
        </div>
      </Card>
    </article>
  );
}
