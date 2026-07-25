"use client";

import { useState } from "react";
import { AdvancedDetails } from "@/components/product/advanced-details";
import { FitPanels } from "@/components/product/fit-panels";
import { FormatSelector } from "@/components/product/format-selector";
import { JobPriorities } from "@/components/product/job-priorities";
import { KeywordsAdded } from "@/components/product/keywords-added";
import { useKit } from "@/components/product/kit-context";
import { useFeedback } from "@/components/product/feedback";
import { PrimaryDocumentCard } from "@/components/product/primary-document-card";
import type { DocumentFormat } from "@/components/product/quick-pdf-download";
import { ResultsHeader } from "@/components/product/results-header";
import { ScoreComparison } from "@/components/product/score-comparison";
import { Banner } from "@/components/ui/primitives";
import { copyText, kitTarget } from "@/lib/product";
import { formatAnswersText, recommendedOutreachDraft } from "@/lib/artifact-content";

/**
 * The results-first Application Kit page (D4 / K1). Renders top to bottom:
 * personalized header, ATS keyword-match comparison, primary downloads with a
 * PDF/Word selector, evidence-backed added keywords, "what matters most" job
 * priorities, exactly two fit panels (strengths/gaps), and one quiet advanced
 * entry. A Kit opened from History renders this identical page — never a
 * different, more-technical view than the one shown right after generation.
 */
export function UnifiedKitWorkspace() {
  const { kit, refresh } = useKit();
  const { notify } = useFeedback();
  const [format, setFormat] = useState<DocumentFormat>("pdf");
  const [previewArtifact, setPreviewArtifact] = useState<"resume" | "cover-letter" | null>(null);
  const target = kitTarget(kit);
  const result = kit?.result;
  if (!kit || !result) return null;
  const completedResult = result;

  async function copyAnswers() {
    if (!completedResult.answers) return;
    try {
      await copyText(formatAnswersText(completedResult.answers));
      notify("All application answers copied from the generated version.");
    } catch {
      notify("Couldn't access the clipboard. Open Application answers to copy manually.", "error");
    }
  }
  async function copyRecommendedOutreach() {
    const draft = recommendedOutreachDraft(completedResult.linkedin_outreach?.drafts ?? []);
    if (!draft) return;
    try {
      await copyText(draft.text);
      notify("Recommended outreach draft copied from the generated version. Nothing was sent.");
    } catch {
      notify("Couldn't access the clipboard. Open LinkedIn Outreach to copy manually.", "error");
    }
  }

  const isCurrentSchema = result.schema_version === "application-kit/v5";
  const isV4 = result.schema_version === "application-kit/v4";

  return (
    <div className="space-y-2 pb-20">
      {!isCurrentSchema && (
        <Banner tone="warning" title={isV4 ? "Earlier kit format (v4)." : "Older or unknown schema."} className="mb-4">
          {isV4
            ? "This Kit was generated before match reporting and the change ledger. Regenerate it to get the current scoring and tailoring transparency."
            : "This Kit is displayed through the compatibility boundary. Some fields may be unavailable."}
        </Banner>
      )}

      <ResultsHeader kit={kit} />

      {result.match_report ? (
        <>
          <ScoreComparison report={result.match_report} />
          <KeywordsAdded report={result.match_report} onSeeWhereTheseAppear={() => setPreviewArtifact("resume")} />
          <JobPriorities report={result.match_report} />
          <FitPanels report={result.match_report} />
        </>
      ) : (
        <Banner tone="neutral" title="Match scores were unavailable for this run." className="mt-6">
          Your documents are still available for download below.
        </Banner>
      )}

      <section aria-labelledby="downloads-heading" className="mt-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="downloads-heading" className="text-md font-semibold">
            Your documents
          </h2>
          <FormatSelector format={format} onChange={setFormat} />
        </div>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <PrimaryDocumentCard
            artifact="resume"
            value={result.resume}
            requested={kit.include_resume}
            expanded={previewArtifact === "resume"}
            onExpandedChange={(open) => setPreviewArtifact(open ? "resume" : null)}
            format={format}
          />
          <PrimaryDocumentCard
            artifact="cover-letter"
            value={result.cover_letter}
            requested={kit.include_cover_letter}
            expanded={previewArtifact === "cover-letter"}
            onExpandedChange={(open) => setPreviewArtifact(open ? "cover-letter" : null)}
            format={format}
          />
        </div>
      </section>

      <AdvancedDetails
        kit={kit}
        result={result}
        target={target}
        onCopyAnswers={() => void copyAnswers()}
        onCopyOutreach={() => void copyRecommendedOutreach()}
        onRefresh={refresh}
      />
    </div>
  );
}
