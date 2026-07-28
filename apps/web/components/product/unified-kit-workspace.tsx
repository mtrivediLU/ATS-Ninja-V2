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
import { copyText, effectiveKitStatus, kitTarget } from "@/lib/product";
import { formatAnswersText, recommendedOutreachDraft } from "@/lib/artifact-content";

/**
 * The results-first Application Kit page (D4 / K1). Renders top to bottom in
 * the approved order: personalized header, ATS keyword-match comparison,
 * primary downloads with a PDF/Word selector, evidence-backed added keywords,
 * "what matters most" job priorities, exactly two fit panels (strengths/
 * gaps), and one quiet advanced entry. A Kit opened from History renders this
 * identical page — never a different, more-technical view than the one shown
 * right after generation.
 */
export function UnifiedKitWorkspace() {
  const { kit, refresh } = useKit();
  const { notify } = useFeedback();
  const [format, setFormat] = useState<DocumentFormat>("pdf");
  const [previewArtifact, setPreviewArtifact] = useState<"resume" | "cover-letter" | null>(null);
  const target = kitTarget(kit);
  const result = kit?.result;
  if (!kit || !result) return null;
  const lifecycle = effectiveKitStatus(kit);
  const completedResult = result;

  function openResumePreview() {
    setPreviewArtifact("resume");
    // The resume card may already be on screen (its expand/focus effect fires
    // regardless), but an explicit smooth scroll guarantees the user actually
    // sees where the added keywords appear, not just that focus moved there.
    window.requestAnimationFrame(() => {
      document.getElementById("resume")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

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

  const isSupportedSchema =
    result.schema_version === "application-kit/v5" ||
    result.schema_version === "application-kit/v6" ||
    result.schema_version === "application-kit/v7";
  const isV4 = result.schema_version === "application-kit/v4";

  return (
    <div className="space-y-2 pb-20">
      {!isSupportedSchema && (
        <Banner tone="warning" title={isV4 ? "Earlier kit format (v4)." : "Older or unknown schema."} className="mb-4">
          {isV4
            ? "This Kit was generated before match reporting and the change ledger. Regenerate it to get the current scoring and tailoring transparency."
            : "This Kit is displayed through the compatibility boundary. Some fields may be unavailable."}
        </Banner>
      )}

      <ResultsHeader kit={kit} />

      {lifecycle === "partially_completed" && (
        <Banner tone="warning" title="This Kit was partially completed." className="mt-4">
          Some requested artifacts could not be delivered. Successfully generated documents remain available below.
        </Banner>
      )}
      {lifecycle === "needs_input_review" && (
        <Banner tone="warning" title="Some input needs review." className="mt-4">
          At least one requested artifact could not be delivered from the extracted input. Successfully delivered
          artifacts remain available below; review the source résumé and job description before creating a new Kit.
        </Banner>
      )}

      {result.match_report && (
        <ScoreComparison report={result.match_report} resumeState={result.delivery_reports?.resume?.state} />
      )}
      {!result.match_report && (
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
            deliveryReport={result.delivery_reports?.resume}
          />
          <PrimaryDocumentCard
            artifact="cover-letter"
            value={result.cover_letter}
            requested={kit.include_cover_letter}
            expanded={previewArtifact === "cover-letter"}
            onExpandedChange={(open) => setPreviewArtifact(open ? "cover-letter" : null)}
            format={format}
            deliveryReport={result.delivery_reports?.cover_letter}
          />
        </div>
      </section>

      {result.match_report && (
        <>
          <KeywordsAdded report={result.match_report} onSeeWhereTheseAppear={openResumePreview} />
          <JobPriorities report={result.match_report} />
          <FitPanels report={result.match_report} />
        </>
      )}

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
