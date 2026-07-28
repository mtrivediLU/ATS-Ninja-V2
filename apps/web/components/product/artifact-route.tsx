"use client";

import { ArtifactState, NotRequestedArtifact, WithheldArtifact } from "@/components/product/artifact-states";
import { DeliveryFallbackBanner } from "@/components/product/delivery-notice";
import { AnswersWorkspace, DocumentWorkspace } from "@/components/product/document-workspaces";
import { InterviewWorkspace } from "@/components/product/interview-workspace";
import { JobFitWorkspace } from "@/components/product/job-fit-workspace";
import { useKit } from "@/components/product/kit-context";
import { OutreachWorkspace } from "@/components/product/outreach-workspace";
import type { ArtifactSlug } from "@/lib/navigation";
import type { ArtifactKind } from "@/lib/api-types";
import { kitTarget, safeWithheldReason } from "@/lib/product";

const titles: Record<ArtifactSlug, string> = {
  resume: "Resume",
  "cover-letter": "Cover letter",
  answers: "Application answers",
  "job-fit": "Job fit",
  "interview-prep": "Interview preparation",
  "linkedin-outreach": "LinkedIn outreach",
};
const deliveryKeys: Record<ArtifactSlug, ArtifactKind> = {
  resume: "resume",
  "cover-letter": "cover_letter",
  answers: "answers",
  "job-fit": "job_fit",
  "interview-prep": "interview_prep",
  "linkedin-outreach": "linkedin_outreach",
};

export function ArtifactRoute({ artifact }: { artifact: ArtifactSlug }) {
  const { kit, refresh } = useKit();
  if (!kit?.result) return null;
  const result = kit.result;
  const target = kitTarget(kit);
  const selected = artifact === "resume" ? kit.include_resume : artifact === "cover-letter" ? kit.include_cover_letter : artifact === "answers" ? kit.include_application_answers : artifact === "job-fit" ? kit.include_job_fit : artifact === "interview-prep" ? kit.include_interview_prep : kit.include_linkedin_outreach;
  if (!selected) return <NotRequestedArtifact title={titles[artifact]} />;
  const deliveryReport = result.delivery_reports?.[deliveryKeys[artifact]];
  if (deliveryReport?.state === "not_requested") return <NotRequestedArtifact title={titles[artifact]} />;
  if (deliveryReport?.state === "needs_input_review") {
    return <ArtifactState title={`${titles[artifact]} needs input review`} state="needs-input-review" reason={deliveryReport.fallback_reason ?? undefined} />;
  }
  if (deliveryReport?.state === "failed") {
    return <ArtifactState title={`${titles[artifact]} failed`} state="failed" reason={deliveryReport.fallback_reason ?? undefined} />;
  }

  if (artifact === "resume") {
    if (!result.resume) return <Unavailable title="Resume" onRetry={() => void refresh()} />;
    if (!deliveryReport && (result.resume.validation.fatal || result.resume.validation.status === "rejected")) return <WithheldArtifact title="Resume" reason={safeWithheldReason(result.resume.validation.errors, result.resume.validation.warnings)} />;
    return <>{deliveryReport?.state === "generated_with_fallback" && <DeliveryFallbackBanner artifact="resume" report={deliveryReport} className="mb-4" />}<DocumentWorkspace kind="resume" artifact={result.resume} company={target.company} role={target.role} kitId={kit.id} deliveryState={deliveryReport?.state} /></>;
  }
  if (artifact === "cover-letter") {
    if (!result.cover_letter) return <Unavailable title="Cover letter" onRetry={() => void refresh()} />;
    if (!deliveryReport && (result.cover_letter.validation.fatal || result.cover_letter.validation.status === "rejected")) return <WithheldArtifact title="Cover letter" reason={safeWithheldReason(result.cover_letter.validation.errors, result.cover_letter.validation.warnings)} />;
    return <>{deliveryReport?.state === "generated_with_fallback" && <DeliveryFallbackBanner artifact="cover-letter" report={deliveryReport} className="mb-4" />}<DocumentWorkspace kind="cover-letter" artifact={result.cover_letter} company={target.company} role={target.role} kitId={kit.id} deliveryState={deliveryReport?.state} /></>;
  }
  if (artifact === "answers") {
    if (!result.answers) return <Unavailable title="Application answers" onRetry={() => void refresh()} />;
    if (!deliveryReport && result.answers.validation.fatal && !result.answers.items.length) return <WithheldArtifact title="Application answers" reason={safeWithheldReason(result.answers.validation.errors, result.answers.validation.warnings)} />;
    return <AnswersWorkspace artifact={result.answers} company={target.company} role={target.role} deliveryState={deliveryReport?.state} />;
  }
  if (artifact === "job-fit") {
    if (!result.job_fit) return <Unavailable title="Job fit" onRetry={() => void refresh()} />;
    if (!deliveryReport && (result.job_fit.withheld || result.job_fit.validation.fatal)) return <WithheldArtifact title="Job fit" reason={safeWithheldReason(result.job_fit.validation.errors, result.job_fit.warnings)} />;
    return <JobFitWorkspace artifact={result.job_fit} company={target.company} role={target.role} deliveryState={deliveryReport?.state} />;
  }
  if (artifact === "interview-prep") {
    if (!result.interview_prep) return <Unavailable title="Interview preparation" onRetry={() => void refresh()} />;
    if (!deliveryReport && (result.interview_prep.withheld || result.interview_prep.validation.fatal)) return <WithheldArtifact title="Interview preparation" reason={safeWithheldReason(result.interview_prep.validation.errors, result.interview_prep.warnings)} />;
    return <InterviewWorkspace artifact={result.interview_prep} company={target.company} role={target.role} deliveryState={deliveryReport?.state} />;
  }
  if (!result.linkedin_outreach) return <Unavailable title="LinkedIn outreach" onRetry={() => void refresh()} />;
  if (!deliveryReport && (result.linkedin_outreach.withheld || result.linkedin_outreach.validation.fatal)) return <WithheldArtifact title="LinkedIn outreach" reason={safeWithheldReason(result.linkedin_outreach.validation.errors, result.linkedin_outreach.warnings)} />;
  return <OutreachWorkspace artifact={result.linkedin_outreach} company={target.company} role={target.role} deliveryState={deliveryReport?.state} />;
}

function Unavailable({ title, onRetry }: { title: string; onRetry: () => void }) {
  return <ArtifactState title={`${title} unavailable`} state="unavailable" onRetry={onRetry} />;
}
