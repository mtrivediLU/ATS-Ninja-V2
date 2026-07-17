"use client";

import { ArtifactState, NotRequestedArtifact, WithheldArtifact } from "@/components/product/artifact-states";
import { AnswersWorkspace, DocumentWorkspace } from "@/components/product/document-workspaces";
import { InterviewWorkspace } from "@/components/product/interview-workspace";
import { JobFitWorkspace } from "@/components/product/job-fit-workspace";
import { useKit } from "@/components/product/kit-context";
import { OutreachWorkspace } from "@/components/product/outreach-workspace";
import type { ArtifactSlug } from "@/lib/navigation";
import { kitTarget } from "@/lib/product";

const titles: Record<ArtifactSlug, string> = {
  resume: "Resume",
  "cover-letter": "Cover letter",
  answers: "Application answers",
  "job-fit": "Job fit",
  "interview-prep": "Interview preparation",
  "linkedin-outreach": "LinkedIn outreach",
};

export function ArtifactRoute({ artifact }: { artifact: ArtifactSlug }) {
  const { kit, refresh } = useKit();
  if (!kit?.result) return null;
  const result = kit.result;
  const target = kitTarget(kit);
  const selected = artifact === "resume" ? kit.include_resume : artifact === "cover-letter" ? kit.include_cover_letter : artifact === "answers" ? kit.include_application_answers : artifact === "job-fit" ? kit.include_job_fit : artifact === "interview-prep" ? kit.include_interview_prep : kit.include_linkedin_outreach;
  if (!selected) return <NotRequestedArtifact title={titles[artifact]} />;

  if (artifact === "resume") {
    if (!result.resume) return <Unavailable title="Resume" onRetry={() => void refresh()} />;
    if (result.resume.validation.fatal || result.resume.validation.status === "rejected") return <WithheldArtifact title="Resume" reason={result.resume.validation.warnings[0]} />;
    return <DocumentWorkspace kind="resume" artifact={result.resume} company={target.company} role={target.role} />;
  }
  if (artifact === "cover-letter") {
    if (!result.cover_letter) return <Unavailable title="Cover letter" onRetry={() => void refresh()} />;
    if (result.cover_letter.validation.fatal || result.cover_letter.validation.status === "rejected") return <WithheldArtifact title="Cover letter" reason={result.cover_letter.validation.warnings[0]} />;
    return <DocumentWorkspace kind="cover-letter" artifact={result.cover_letter} company={target.company} role={target.role} />;
  }
  if (artifact === "answers") {
    if (!result.answers) return <Unavailable title="Application answers" onRetry={() => void refresh()} />;
    if (result.answers.validation.fatal && !result.answers.items.length) return <WithheldArtifact title="Application answers" reason={result.answers.validation.warnings[0]} />;
    return <AnswersWorkspace artifact={result.answers} company={target.company} role={target.role} />;
  }
  if (artifact === "job-fit") {
    if (!result.job_fit) return <Unavailable title="Job fit" onRetry={() => void refresh()} />;
    if (result.job_fit.withheld || result.job_fit.validation.fatal) return <WithheldArtifact title="Job fit" reason={result.job_fit.warnings[0]} />;
    return <JobFitWorkspace artifact={result.job_fit} company={target.company} role={target.role} />;
  }
  if (artifact === "interview-prep") {
    if (!result.interview_prep) return <Unavailable title="Interview preparation" onRetry={() => void refresh()} />;
    if (result.interview_prep.withheld || result.interview_prep.validation.fatal) return <WithheldArtifact title="Interview preparation" reason={result.interview_prep.warnings[0]} />;
    return <InterviewWorkspace artifact={result.interview_prep} company={target.company} role={target.role} />;
  }
  if (!result.linkedin_outreach) return <Unavailable title="LinkedIn outreach" onRetry={() => void refresh()} />;
  if (result.linkedin_outreach.withheld || result.linkedin_outreach.validation.fatal) return <WithheldArtifact title="LinkedIn outreach" reason={result.linkedin_outreach.warnings[0]} />;
  return <OutreachWorkspace artifact={result.linkedin_outreach} company={target.company} role={target.role} />;
}

function Unavailable({ title, onRetry }: { title: string; onRetry: () => void }) {
  return <ArtifactState title={`${title} unavailable`} state="unavailable" onRetry={onRetry} />;
}
