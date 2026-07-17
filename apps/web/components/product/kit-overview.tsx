"use client";

import Link from "next/link";
import { AlertTriangle, ArrowRight, CheckCircle2, CircleMinus, ShieldCheck } from "lucide-react";
import { useKit } from "@/components/product/kit-context";
import { Banner, Card, StatusLabel, buttonClassName } from "@/components/ui/primitives";
import { formatDate, kitTarget } from "@/lib/product";
import { kitStatusPresentation, notRequestedPresentation, withheldPresentation } from "@/lib/status";

export function KitOverview() {
  const { kit, openEvidence } = useKit();
  if (!kit?.result) return null;
  const result = kit.result;
  const target = kitTarget(kit);
  const artifacts = [
    { slug: "resume", label: "Resume", selected: kit.include_resume, value: result.resume },
    { slug: "cover-letter", label: "Cover letter", selected: kit.include_cover_letter, value: result.cover_letter },
    { slug: "answers", label: "Application answers", selected: kit.include_application_answers, value: result.answers },
    { slug: "job-fit", label: "Job fit", selected: kit.include_job_fit, value: result.job_fit },
    { slug: "interview-prep", label: "Interview preparation", selected: kit.include_interview_prep, value: result.interview_prep },
    { slug: "linkedin-outreach", label: "LinkedIn outreach", selected: kit.include_linkedin_outreach, value: result.linkedin_outreach },
  ];
  const claims = artifacts.flatMap((artifact) => artifact.value?.claims ?? []);

  return (
    <div className="space-y-5">
      {result.schema_version !== "application-kit/v4" && <Banner tone="warning" title="Older or unknown schema.">This Kit is displayed through the compatibility boundary. Some D1 fields may be unavailable.</Banner>}
      {result.validation.warning_count > 0 && <Banner tone="warning" title={`${result.validation.warning_count} validation warning${result.validation.warning_count === 1 ? "" : "s"}.`}>Review repaired and withheld states before using generated content.</Banner>}
      <div className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">ApplicationKit overview</p><h2 className="mt-1 text-xl font-bold">{target.role}</h2><p className="text-ink-secondary">{target.company}</p></div><StatusLabel presentation={kitStatusPresentation[kit.status]} /></div>
          <dl className="mt-5 grid gap-4 border-t border-border-subtle pt-4 sm:grid-cols-2"><Metric label="Schema" value={result.schema_version} mono /><Metric label="Created" value={formatDate(kit.created_at)} /><Metric label="Generation" value={result.generation.generation_mode} /><Metric label="Claims traced" value={String(claims.length)} /></dl>
        </Card>
        <Card>
          <h2 className="text-md font-semibold">Fit summary</h2>
          {result.job_fit ? <dl className="mt-4 grid grid-cols-2 gap-4"><Metric label="Fit band" value={result.job_fit.fit_band} /><Metric label="Requirement coverage" value={`${result.job_fit.requirement_coverage_score}`} mono /><Metric label="ATS keyword score" value={`${result.job_fit.ats_keyword_score}`} mono /><Metric label="Must-have gaps" value={`${result.job_fit.must_have_gaps.length}`} /></dl> : <p className="mt-3 text-sm text-ink-muted">Job Fit was not requested or was unavailable.</p>}
        </Card>
      </div>

      <section aria-labelledby="artifacts-heading"><div className="mb-3 flex items-center justify-between gap-3"><h2 id="artifacts-heading" className="text-md font-semibold">Artifacts</h2><button type="button" onClick={() => openEvidence()} className="inline-flex min-h-11 items-center gap-2 rounded-control px-2 text-sm font-semibold text-accent hover:bg-accent-subtle"><ShieldCheck aria-hidden="true" className="size-[18px]" />Open evidence</button></div><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{artifacts.map((artifact) => {
        const withheld = artifact.value && "withheld" in artifact.value && artifact.value.withheld;
        const status = !artifact.selected ? notRequestedPresentation : withheld ? withheldPresentation : artifact.value ? { label: "Generated", accessibleLabel: `${artifact.label}: Generated`, tone: "positive" as const, icon: CheckCircle2 } : { label: "Unavailable", accessibleLabel: `${artifact.label}: Unavailable`, tone: "neutral" as const, icon: CircleMinus };
        return <Card key={artifact.slug} className="flex flex-col shadow-none"><div className="flex items-start justify-between gap-3"><h3 className="font-semibold">{artifact.label}</h3><StatusLabel presentation={status} /></div><p className="mt-2 flex-1 text-sm text-ink-muted">{artifact.value?.validation.warnings[0] ?? (!artifact.selected ? "Not selected for this Kit." : artifact.value ? "Available in this completed Kit." : "The selected artifact was not returned.")}</p>{artifact.value && <Link href={`/kits/${kit.id}/${artifact.slug}`} className={`${buttonClassName("secondary", "sm")} mt-4 self-start`}>Open<ArrowRight aria-hidden="true" className="size-4" /></Link>}</Card>;
      })}</div></section>

      {result.job_fit?.must_have_gaps.length ? <Banner tone="warning" title="Must-have gaps remain visible."><AlertTriangle aria-hidden="true" className="mr-1 inline size-4" />{result.job_fit.must_have_gaps.join(" · ")}</Banner> : null}
      {result.job_fit && <div className="grid gap-4 lg:grid-cols-2"><ListCard title="Important strengths" values={result.job_fit.strongest_matches} /><ListCard title="Genuine gaps" values={result.job_fit.genuine_gaps} danger /></div>}
    </div>
  );
}

function Metric({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) { return <div><dt className="text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">{label}</dt><dd className={`mt-1 capitalize ${mono ? "font-mono text-sm" : "font-medium"}`}>{value}</dd></div>; }
function ListCard({ title, values, danger = false }: { title: string; values: string[]; danger?: boolean }) { return <Card><h3 className="font-semibold">{title}</h3>{values.length ? <ul className="mt-3 space-y-2">{values.map((value) => <li key={value} className="flex gap-2 text-sm"><span aria-hidden="true" className={`mt-2 size-1.5 shrink-0 rounded-pill ${danger ? "bg-danger" : "bg-positive"}`} />{value}</li>)}</ul> : <p className="mt-2 text-sm text-ink-muted">None returned.</p>}</Card>; }
