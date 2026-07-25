"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AnswersWorkspace } from "@/components/product/document-workspaces";
import { ArtifactSummarySection } from "@/components/product/artifact-summary-section";
import { ChangeLedger } from "@/components/product/change-ledger";
import { InterviewWorkspace } from "@/components/product/interview-workspace";
import { JobFitWorkspace } from "@/components/product/job-fit-workspace";
import { KitLineageActions } from "@/components/product/kit-lineage";
import { KitTrustStrip } from "@/components/product/kit-trust-strip";
import { MatchInsights } from "@/components/product/match-insights";
import { OutreachWorkspace } from "@/components/product/outreach-workspace";
import { Button } from "@/components/ui/primitives";
import { artifactPresentationState } from "@/lib/artifact-presentation";
import type { ApplicationKit, KitRead } from "@/lib/api-types";

type SecondaryArtifact = "answers" | "job-fit" | "interview-prep" | "linkedin-outreach";

/**
 * The single quiet advanced entry: "View detailed analysis and evidence".
 * The main results page is complete and useful without opening this. Behind
 * it: the full match-report breakdown, tailoring change ledgers, trust and
 * evidence, application answers, job-fit requirement assessment, interview
 * prep, LinkedIn outreach, and kit lineage (regenerate / revision history).
 * Only one of the four secondary-artifact sub-sections opens at a time.
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
  const [openArtifact, setOpenArtifact] = useState<SecondaryArtifact | null>(null);
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
    ? artifactPresentationState(result.answers.validation, result.answers.text)
    : kit.include_application_answers
      ? "unavailable"
      : "not-requested";
  const fitState = result.job_fit
    ? artifactPresentationState(result.job_fit.validation, result.job_fit.summary)
    : kit.include_job_fit
      ? "unavailable"
      : "not-requested";
  const interviewState = result.interview_prep
    ? artifactPresentationState(result.interview_prep.validation, result.interview_prep.strategy_summary)
    : kit.include_interview_prep
      ? "unavailable"
      : "not-requested";
  const outreachState = result.linkedin_outreach
    ? artifactPresentationState(result.linkedin_outreach.validation, result.linkedin_outreach.strategy_summary)
    : kit.include_linkedin_outreach
      ? "unavailable"
      : "not-requested";

  const hasChanges = Boolean(result.resume?.change_ledger?.length || result.cover_letter?.change_ledger?.length);

  return (
    <section className="mt-8 border-t border-border-subtle pt-6">
      <Button ref={triggerRef} variant="secondary" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronUp aria-hidden="true" className="size-4" /> : <ChevronDown aria-hidden="true" className="size-4" />}
        {open ? "Hide detailed analysis and evidence" : "View detailed analysis and evidence"}
      </Button>
      {open && (
        <div id={panelId} ref={panelRef} tabIndex={-1} className="mt-5 space-y-6">
          {result.match_report && <MatchInsights report={result.match_report} />}
          <KitTrustStrip />
          <KitLineageActions kitId={kit.id} parentKitId={kit.parent_kit_id} revision={kit.revision} />
          {hasChanges && (
            <section aria-labelledby="tailoring-changes-heading">
              <h3 id="tailoring-changes-heading" className="text-sm font-semibold">
                Detailed tailoring changes
              </h3>
              <p className="mt-1 text-sm text-ink-secondary">
                Every change is transparent and reversible, except permanent truth-grounding removals.
              </p>
              {result.resume && result.resume.change_ledger.length > 0 && (
                <ChangeLedger kitId={kit.id} records={result.resume.change_ledger} revision={kit.revision} onApplied={onRefresh} title="Resume changes" />
              )}
              {result.cover_letter && result.cover_letter.change_ledger.length > 0 && (
                <ChangeLedger kitId={kit.id} records={result.cover_letter.change_ledger} revision={kit.revision} onApplied={onRefresh} title="Cover letter changes" />
              )}
            </section>
          )}
          <div className="space-y-4">
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
              expanded={openArtifact === "answers"}
              onExpandedChange={(next) => setOpenArtifact(next ? "answers" : null)}
              kitId={kit.id}
              route="answers"
            >
              {result.answers && <AnswersWorkspace artifact={result.answers} company={target.company} role={target.role} />}
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
              onPrimary={() => setOpenArtifact("job-fit")}
              onRetry={() => void onRefresh()}
              expanded={openArtifact === "job-fit"}
              onExpandedChange={(next) => setOpenArtifact(next ? "job-fit" : null)}
              kitId={kit.id}
              route="job-fit"
            >
              {result.job_fit && <JobFitWorkspace artifact={result.job_fit} company={target.company} role={target.role} />}
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
              onPrimary={() => setOpenArtifact("interview-prep")}
              onRetry={() => void onRefresh()}
              expanded={openArtifact === "interview-prep"}
              onExpandedChange={(next) => setOpenArtifact(next ? "interview-prep" : null)}
              kitId={kit.id}
              route="interview-prep"
            >
              {result.interview_prep && <InterviewWorkspace artifact={result.interview_prep} company={target.company} role={target.role} />}
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
              expanded={openArtifact === "linkedin-outreach"}
              onExpandedChange={(next) => setOpenArtifact(next ? "linkedin-outreach" : null)}
              kitId={kit.id}
              route="linkedin-outreach"
            >
              {result.linkedin_outreach && <OutreachWorkspace artifact={result.linkedin_outreach} company={target.company} role={target.role} />}
            </ArtifactSummarySection>
          </div>
        </div>
      )}
    </section>
  );
}
