"use client";

import { ArtifactToolbar } from "@/components/product/artifact-toolbar";
import { NotRequestedArtifact, WithheldArtifact } from "@/components/product/artifact-states";
import { AnswersWorkspace, DocumentWorkspace } from "@/components/product/document-workspaces";
import { InterviewWorkspace } from "@/components/product/interview-workspace";
import { JobFitWorkspace } from "@/components/product/job-fit-workspace";
import { useKit } from "@/components/product/kit-context";
import { OutreachWorkspace } from "@/components/product/outreach-workspace";
import { Card } from "@/components/ui/primitives";
import type { ArtifactSlug } from "@/lib/navigation";
import { kitTarget, safeFilename } from "@/lib/product";

const titles: Record<ArtifactSlug, string> = {
  resume: "Resume",
  "cover-letter": "Cover letter",
  answers: "Application answers",
  "job-fit": "Job fit",
  "interview-prep": "Interview preparation",
  "linkedin-outreach": "LinkedIn outreach",
};

export function ArtifactRoute({ artifact }: { artifact: ArtifactSlug }) {
  const { kit } = useKit();
  if (!kit?.result) return null;
  const result = kit.result;
  const target = kitTarget(kit);
  const selected = artifact === "resume" ? kit.include_resume : artifact === "cover-letter" ? kit.include_cover_letter : artifact === "answers" ? kit.include_application_answers : artifact === "job-fit" ? kit.include_job_fit : artifact === "interview-prep" ? kit.include_interview_prep : kit.include_linkedin_outreach;
  if (!selected) return <NotRequestedArtifact title={titles[artifact]} />;

  if (artifact === "resume") {
    if (!result.resume) return <Unavailable title="Resume" />;
    if (result.resume.validation.fatal || result.resume.validation.status === "rejected") return <WithheldArtifact title="Resume" reason={result.resume.validation.warnings[0]} />;
    return <DocumentWorkspace kind="resume" artifact={result.resume} company={target.company} role={target.role} />;
  }
  if (artifact === "cover-letter") {
    if (!result.cover_letter) return <Unavailable title="Cover letter" />;
    if (result.cover_letter.validation.fatal || result.cover_letter.validation.status === "rejected") return <WithheldArtifact title="Cover letter" reason={result.cover_letter.validation.warnings[0]} />;
    return <DocumentWorkspace kind="cover-letter" artifact={result.cover_letter} company={target.company} role={target.role} />;
  }
  if (artifact === "answers") {
    if (!result.answers) return <Unavailable title="Application answers" />;
    if (result.answers.validation.fatal && !result.answers.items.length) return <WithheldArtifact title="Application answers" reason={result.answers.validation.warnings[0]} />;
    return <AnswersWorkspace artifact={result.answers} company={target.company} role={target.role} />;
  }
  if (artifact === "job-fit") {
    if (!result.job_fit) return <Unavailable title="Job fit" />;
    if (result.job_fit.withheld || result.job_fit.validation.fatal) return <WithheldArtifact title="Job fit" reason={result.job_fit.warnings[0]} />;
    return <JobFitWorkspace artifact={result.job_fit} company={target.company} role={target.role} />;
  }
  if (artifact === "interview-prep") {
    if (!result.interview_prep) return <Unavailable title="Interview preparation" />;
    if (result.interview_prep.withheld || result.interview_prep.validation.fatal) return <WithheldArtifact title="Interview preparation" reason={result.interview_prep.warnings[0]} />;
    return <InterviewWorkspace artifact={result.interview_prep} company={target.company} role={target.role} />;
  }
  if (!result.linkedin_outreach) return <Unavailable title="LinkedIn outreach" />;
  if (result.linkedin_outreach.withheld || result.linkedin_outreach.validation.fatal) return <WithheldArtifact title="LinkedIn outreach" reason={result.linkedin_outreach.warnings[0]} />;
  return <OutreachWorkspace artifact={result.linkedin_outreach} company={target.company} role={target.role} />;
}

function Unavailable({ title }: { title: string }) {
  const emptyValidation = { status: "generated", fatal: false, errors: [], warnings: [], repaired_claims: 0, rejected_claims: 0 };
  return <div><ArtifactToolbar title={title} validation={emptyValidation} claims={[]} text="" filename={safeFilename(title)} /><Card className="mx-auto max-w-[680px] text-center"><h2 className="text-lg font-semibold">Artifact unavailable</h2><p className="mt-2 text-sm text-ink-secondary">This artifact was selected, but the completed response did not include it. No substitute content is inferred.</p></Card></div>;
}
