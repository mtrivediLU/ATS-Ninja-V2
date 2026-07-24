"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { AnswersWorkspace } from "@/components/product/document-workspaces";
import { ArtifactSummarySection } from "@/components/product/artifact-summary-section";
import { InterviewWorkspace } from "@/components/product/interview-workspace";
import { JobFitWorkspace } from "@/components/product/job-fit-workspace";
import { KitQuickActions } from "@/components/product/kit-quick-actions";
import { useKit } from "@/components/product/kit-context";
import { KitTrustStrip } from "@/components/product/kit-trust-strip";
import { KitLineageActions } from "@/components/product/kit-lineage";
import { MatchInsights } from "@/components/product/match-insights";
import { ChangeLedger } from "@/components/product/change-ledger";
import { useFeedback } from "@/components/product/feedback";
import { OutreachWorkspace } from "@/components/product/outreach-workspace";
import { PrimaryDocumentCard } from "@/components/product/primary-document-card";
import { Banner, Button, Card, StatusLabel } from "@/components/ui/primitives";
import { copyText, formatDate, kitTarget } from "@/lib/product";
import { artifactPresentationState } from "@/lib/artifact-presentation";
import { formatAnswersText, recommendedOutreachDraft } from "@/lib/artifact-content";
import { kitStatusPresentation } from "@/lib/status";

const hashes = ["resume", "cover-letter", "answers", "job-fit", "interview-prep", "linkedin-outreach"] as const;
type OpenArtifact = (typeof hashes)[number] | null;

export function UnifiedKitWorkspace() {
  const { kit, openEvidence, setEvidenceFilters, refresh } = useKit();
  const { notify } = useFeedback();
  const [openArtifact, setOpenArtifact] = useState<OpenArtifact>(null);
  const target = kitTarget(kit);
  const changeOpen = useCallback((next: OpenArtifact, updateHistory = true) => {
    setOpenArtifact(next);
    if (!updateHistory) return;
    const url = next ? `${window.location.pathname}${window.location.search}#${next}` : `${window.location.pathname}${window.location.search}`;
    window.history.pushState(null, "", url);
  }, []);
  useEffect(() => {
    const readHash = () => {
      const hash = window.location.hash.slice(1);
      setOpenArtifact(hashes.includes(hash as (typeof hashes)[number]) ? hash as OpenArtifact : null);
    };
    readHash();
    window.addEventListener("popstate", readHash);
    window.addEventListener("hashchange", readHash);
    return () => { window.removeEventListener("popstate", readHash); window.removeEventListener("hashchange", readHash); };
  }, []);
  useEffect(() => {
    if (openArtifact) window.requestAnimationFrame(() => document.getElementById(openArtifact)?.scrollIntoView({ block: "nearest" }));
  }, [openArtifact]);
  const result = kit?.result;
  const requestedCount = useMemo(() => kit ? [kit.include_resume, kit.include_cover_letter, kit.include_application_answers, kit.include_job_fit, kit.include_interview_prep, kit.include_linkedin_outreach].filter(Boolean).length : 0, [kit]);
  if (!kit || !result) return null;
  const completedResult = result;
  const openWarnings = () => { setEvidenceFilters({ status: "all" }); openEvidence(); };
  const answerState = result.answers ? artifactPresentationState(result.answers.validation, result.answers.text) : kit.include_application_answers ? "unavailable" : "not-requested";
  const fitState = result.job_fit ? artifactPresentationState(result.job_fit.validation, result.job_fit.summary) : kit.include_job_fit ? "unavailable" : "not-requested";
  const interviewState = result.interview_prep ? artifactPresentationState(result.interview_prep.validation, result.interview_prep.strategy_summary) : kit.include_interview_prep ? "unavailable" : "not-requested";
  const outreachState = result.linkedin_outreach ? artifactPresentationState(result.linkedin_outreach.validation, result.linkedin_outreach.strategy_summary) : kit.include_linkedin_outreach ? "unavailable" : "not-requested";
  async function copyAnswers() { if (!completedResult.answers) return; try { await copyText(formatAnswersText(completedResult.answers)); notify("All application answers copied from the generated version."); } catch { notify("Couldn't access the clipboard. Open Application answers to copy manually.", "error"); } }
  async function copyRecommendedOutreach() { const draft = recommendedOutreachDraft(completedResult.linkedin_outreach?.drafts ?? []); if (!draft) return; try { await copyText(draft.text); notify("Recommended outreach draft copied from the generated version. Nothing was sent."); } catch { notify("Couldn't access the clipboard. Open LinkedIn Outreach to copy manually.", "error"); } }
  const isCurrentSchema = result.schema_version === "application-kit/v5";
  const isV4 = result.schema_version === "application-kit/v4";
  return <div className="space-y-6 pb-20">
    {!isCurrentSchema && <Banner tone="warning" title={isV4 ? "Earlier kit format (v4)." : "Older or unknown schema."}>{isV4 ? "This Kit was generated before match reporting and the change ledger. Regenerate it to get the current scoring and tailoring transparency." : "This Kit is displayed through the compatibility boundary. Some fields may be unavailable."}</Banner>}
    <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border-subtle pb-5"><div><p className="text-xs font-semibold uppercase tracking-[0.06em] text-ink-muted">Application Kit</p><h1 className="mt-1 text-2xl font-bold tracking-[-0.01em]">{target.role}</h1><p className="mt-1 text-ink-secondary">{target.company}</p><p className="mt-3 text-xs text-ink-muted">Created {formatDate(kit.created_at)} · {requestedCount} of 6 artifacts requested · revision {kit.revision}{kit.parent_kit_id ? " · regenerated" : ""}</p></div><div className="flex flex-wrap items-center gap-2"><StatusLabel presentation={kitStatusPresentation[kit.status]} />{result.validation.warning_count > 0 && <Button size="sm" variant="secondary" onClick={openWarnings}>Review {result.validation.warning_count} warning{result.validation.warning_count === 1 ? "" : "s"}</Button>}<Link href="/kits/new" className="inline-flex min-h-11 items-center rounded-control px-3 text-sm font-semibold text-accent hover:bg-accent-subtle">New Kit</Link><Link href="/history" className="inline-flex min-h-11 items-center rounded-control px-3 text-sm font-semibold text-accent hover:bg-accent-subtle">History</Link></div></header>
    {result.validation.warning_count > 0 && <Banner tone="warning" title="Completed with warnings.">Review repaired or withheld states before using affected content. Safe, available documents can still be downloaded.</Banner>}
    <KitLineageActions kitId={kit.id} parentKitId={kit.parent_kit_id} revision={kit.revision} />
    <KitQuickActions kit={kit} result={result} onReviewWarnings={openWarnings} onOpenAnswers={() => changeOpen("answers")} />
    <KitTrustStrip />
    {result.match_report && <MatchInsights report={result.match_report} />}
    <section aria-labelledby="primary-documents"><h2 id="primary-documents" className="text-md font-semibold">Primary documents</h2><div className="mt-3 grid gap-4 md:grid-cols-2"><PrimaryDocumentCard artifact="resume" value={result.resume} requested={kit.include_resume} expanded={openArtifact === "resume"} onExpandedChange={(open) => changeOpen(open ? "resume" : null)} /><PrimaryDocumentCard artifact="cover-letter" value={result.cover_letter} requested={kit.include_cover_letter} expanded={openArtifact === "cover-letter"} onExpandedChange={(open) => changeOpen(open ? "cover-letter" : null)} /></div></section>
    <section aria-labelledby="application-support"><h2 id="application-support" className="text-md font-semibold">Application support</h2><div className="mt-3 grid gap-4"><ArtifactSummarySection artifact="answers" title="Application answers" state={answerState} summary={result.answers ? `${result.answers.items.length} questions · ${result.answers.items.length - result.answers.placeholders.length} completed · ${result.answers.placeholders.length} withheld or placeholder` : "Not returned for this Kit."} primaryLabel="Copy all answers" onPrimary={() => void copyAnswers()} onRetry={() => void refresh()} expanded={openArtifact === "answers"} onExpandedChange={(open) => changeOpen(open ? "answers" : null)} kitId={kit.id} route="answers">{result.answers && <AnswersWorkspace artifact={result.answers} company={target.company} role={target.role} />}</ArtifactSummarySection><ArtifactSummarySection artifact="job-fit" title="Job Fit" state={fitState} summary={result.job_fit ? `${result.job_fit.fit_band} · ${result.job_fit.requirement_coverage_score} coverage · ${result.job_fit.must_have_gaps.length} must-have gaps · ${result.job_fit.genuine_gaps.length} genuine gaps` : "Not returned for this Kit."} primaryLabel="View gaps" onPrimary={() => changeOpen("job-fit")} onRetry={() => void refresh()} expanded={openArtifact === "job-fit"} onExpandedChange={(open) => changeOpen(open ? "job-fit" : null)} kitId={kit.id} route="job-fit">{result.job_fit && <JobFitWorkspace artifact={result.job_fit} company={target.company} role={target.role} />}</ArtifactSummarySection></div></section>
    <section aria-labelledby="preparation-outreach"><h2 id="preparation-outreach" className="text-md font-semibold">Preparation and outreach</h2><div className="mt-3 grid gap-4"><ArtifactSummarySection artifact="interview-prep" title="Interview Preparation" state={interviewState} summary={result.interview_prep ? `${result.interview_prep.questions.length} questions · ${result.interview_prep.focus_areas.length} focus areas · ${result.interview_prep.star_stories.filter((story) => story.completeness === "complete").length} complete STAR candidates · ${result.interview_prep.technical_study_topics.length} study topics` : "Not returned for this Kit."} primaryLabel="Start review" onPrimary={() => changeOpen("interview-prep")} onRetry={() => void refresh()} expanded={openArtifact === "interview-prep"} onExpandedChange={(open) => changeOpen(open ? "interview-prep" : null)} kitId={kit.id} route="interview-prep">{result.interview_prep && <InterviewWorkspace artifact={result.interview_prep} company={target.company} role={target.role} />}</ArtifactSummarySection><ArtifactSummarySection artifact="linkedin-outreach" title="LinkedIn Outreach" state={outreachState} summary={result.linkedin_outreach ? `${result.linkedin_outreach.drafts.length} drafts · ${result.linkedin_outreach.drafts[0]?.audience?.replaceAll("_", " ") || "No recommended draft"} · Draft only / LinkedIn not connected` : "Not returned for this Kit."} primaryLabel="Copy recommended draft" onPrimary={() => void copyRecommendedOutreach()} onRetry={() => void refresh()} expanded={openArtifact === "linkedin-outreach"} onExpandedChange={(open) => changeOpen(open ? "linkedin-outreach" : null)} kitId={kit.id} route="linkedin-outreach">{result.linkedin_outreach && <OutreachWorkspace artifact={result.linkedin_outreach} company={target.company} role={target.role} />}</ArtifactSummarySection></div></section>
    {(result.resume?.change_ledger?.length || result.cover_letter?.change_ledger?.length) ? <section aria-labelledby="tailoring-changes"><h2 id="tailoring-changes" className="text-md font-semibold">Tailoring changes</h2><p className="mt-1 text-sm text-ink-secondary">Every change is transparent and reversible, except permanent truth-grounding removals.</p>{result.resume && result.resume.change_ledger.length > 0 && <ChangeLedger kitId={kit.id} records={result.resume.change_ledger} revision={kit.revision} onApplied={refresh} title="Resume changes" />}{result.cover_letter && result.cover_letter.change_ledger.length > 0 && <ChangeLedger kitId={kit.id} records={result.cover_letter.change_ledger} revision={kit.revision} onApplied={refresh} title="Cover letter changes" />}</section> : null}
    <section aria-labelledby="trust-evidence"><h2 id="trust-evidence" className="text-md font-semibold">Trust and Evidence</h2><Card className="mt-3 flex flex-wrap items-center gap-3 shadow-none"><ShieldCheck aria-hidden="true" className="size-5 text-accent" /><p className="min-w-0 flex-1 text-sm text-ink-secondary">Inspect persisted claim excerpts, source locators, validation reasons, and artifact filters without leaving this workspace.</p><Button size="sm" variant="secondary" onClick={openWarnings}>Review warnings</Button></Card></section>
  </div>;
}
