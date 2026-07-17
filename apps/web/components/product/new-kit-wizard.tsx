"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Check, ShieldCheck, WandSparkles } from "lucide-react";
import { createKit } from "@/lib/api-client";
import type { KitCreateInput, OutreachAudience, OutreachContextInput, OutreachIntent } from "@/lib/api-types";
import { Banner, Button, Card, Field, Input, Select, Textarea } from "@/components/ui/primitives";

type OutputKey = "resume" | "cover" | "answers" | "jobFit" | "interview" | "outreach";
type Errors = Partial<Record<"resume" | "job" | "outputs" | "questions" | "submit", string>>;

const outputDefinitions: Array<{ key: OutputKey; label: string; description: string }> = [
  { key: "resume", label: "Resume", description: "ATS-tailored plain text and LaTeX grounded in your source resume." },
  { key: "cover", label: "Cover letter", description: "A target-specific letter using only supported candidate evidence." },
  { key: "answers", label: "Application answers", description: "Question-by-question grounded screening answers." },
  { key: "jobFit", label: "Job fit", description: "Requirement coverage, fit band, strengths, and genuine gaps." },
  { key: "interview", label: "Interview preparation", description: "Questions, answer guides, STAR candidates, and honest gap preparation." },
  { key: "outreach", label: "LinkedIn outreach", description: "Draft-only recruiter, hiring-manager, follow-up, and networking messages." },
];

const initialOutputs: Record<OutputKey, boolean> = { resume: true, cover: true, answers: false, jobFit: true, interview: true, outreach: false };

export function NewKitWizard() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [resume, setResume] = useState("");
  const [job, setJob] = useState("");
  const [questions, setQuestions] = useState("");
  const [outputs, setOutputs] = useState(initialOutputs);
  const [outreach, setOutreach] = useState<OutreachContextInput>({});
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const selected = useMemo(() => outputDefinitions.filter((output) => outputs[output.key]), [outputs]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  function validateInputs(): boolean {
    const next: Errors = {};
    if (!resume.trim()) next.resume = "Paste your resume text to continue.";
    if (job.trim().length < 20) next.job = "Paste a job description of at least 20 characters.";
    setErrors(next);
    return !Object.keys(next).length;
  }

  function validateOutputs(): boolean {
    const next: Errors = {};
    if (!selected.length) next.outputs = "Select at least one output.";
    if (outputs.answers && !questions.trim()) next.questions = "Add at least one application question or deselect Application answers.";
    setErrors(next);
    return !Object.keys(next).length;
  }

  function toggleOutput(key: OutputKey) {
    setOutputs((current) => ({ ...current, [key]: !current[key] }));
    setErrors((current) => ({ ...current, outputs: undefined, questions: undefined }));
  }

  function updateOutreach<K extends keyof OutreachContextInput>(key: K, value: OutreachContextInput[K]) {
    setOutreach((current) => ({ ...current, [key]: value }));
  }

  async function submit() {
    if (submitting || !validateOutputs()) return;
    setSubmitting(true);
    setErrors({});
    const controller = new AbortController();
    controllerRef.current = controller;
    const context = Object.fromEntries(
      Object.entries(outreach).filter(([, value]) => value !== "" && value !== undefined),
    ) as OutreachContextInput;
    const payload: KitCreateInput = {
      resume_text: resume.trim(),
      job_description: job.trim(),
      requested_mode: "",
      questions_text: outputs.answers ? questions.trim() : "",
      include_resume: outputs.resume,
      include_cover_letter: outputs.cover,
      include_application_answers: outputs.answers,
      include_job_fit: outputs.jobFit,
      include_interview_prep: outputs.interview,
      include_linkedin_outreach: outputs.outreach,
      ...(outputs.outreach && Object.keys(context).length ? { outreach_context: context } : {}),
    };
    try {
      const kit = await createKit(payload, controller.signal);
      router.push(`/kits/${kit.id}/resume`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "The Kit could not be submitted.";
      setErrors({ submit: message });
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-[880px] space-y-6">
      <ol className="flex flex-wrap items-center gap-2" aria-label="New Kit progress">
        {["Add inputs", "Choose outputs", "Review & generate"].map((label, index) => {
          const number = index + 1;
          const state = number < step ? "done" : number === step ? "active" : "pending";
          return <li key={label} aria-current={state === "active" ? "step" : undefined} className={`flex items-center gap-2 text-sm ${state === "active" ? "font-semibold text-ink" : "text-ink-muted"}`}><span className={`grid size-7 place-items-center rounded-pill border text-xs ${state === "done" ? "border-accent bg-accent text-on-accent" : state === "active" ? "border-accent text-accent" : "border-border-strong"}`}>{state === "done" ? <Check aria-hidden="true" className="size-4" /> : number}</span><span className="hidden sm:inline">{label}</span></li>;
        })}
      </ol>

      {step === 1 && (
        <div className="space-y-5">
          <Banner tone="info" title="Paste-only in D1.">The API accepts plain resume text. PDF and DOCX upload are omitted until a real ingestion endpoint exists.</Banner>
          <div className="grid gap-5 lg:grid-cols-2">
            <Field label="Resume text" htmlFor="resume-text" hint={errors.resume ?? `${resume.length.toLocaleString()} characters · not stored in browser storage`}>
              <Textarea id="resume-text" value={resume} onChange={(event) => { setResume(event.target.value); setErrors((current) => ({ ...current, resume: undefined })); }} aria-invalid={Boolean(errors.resume)} aria-describedby="resume-text-description" placeholder="Paste your resume text…" className="min-h-72" />
            </Field>
            <Field label="Job description" htmlFor="job-description" hint={errors.job ?? `${job.length.toLocaleString()} characters`}>
              <Textarea id="job-description" value={job} onChange={(event) => { setJob(event.target.value); setErrors((current) => ({ ...current, job: undefined })); }} aria-invalid={Boolean(errors.job)} aria-describedby="job-description-description" placeholder="Paste the target job description…" className="min-h-72" />
            </Field>
          </div>
          <div className="flex flex-col-reverse gap-3 border-t border-border-subtle pt-4 sm:flex-row sm:justify-between"><Button variant="ghost" onClick={() => router.push("/")}>Cancel</Button><Button variant="primary" onClick={() => { if (validateInputs()) setStep(2); }}>Continue<ArrowRight aria-hidden="true" className="size-[17px]" /></Button></div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-5">
          <div><h2 className="text-md font-semibold">Choose outputs independently</h2><p className="mt-1 text-sm text-ink-muted">Only selected artifacts are generated and persisted with this Kit.</p></div>
          {errors.outputs && <Banner tone="danger" title="Selection required.">{errors.outputs}</Banner>}
          <div className="space-y-2">
            {outputDefinitions.map((output) => (
              <button key={output.key} type="button" aria-pressed={outputs[output.key]} onClick={() => toggleOutput(output.key)} className="flex min-h-14 w-full items-start gap-3 rounded-md border border-border bg-surface px-4 py-3 text-left aria-pressed:border-accent-border aria-pressed:bg-accent-subtle">
                <span aria-hidden="true" className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-sm border ${outputs[output.key] ? "border-accent bg-accent text-on-accent" : "border-border-strong"}`}>{outputs[output.key] && <Check className="size-3.5" />}</span>
                <span><span className="block font-semibold">{output.label}</span><span className="block text-sm text-ink-muted">{output.description}</span></span>
              </button>
            ))}
          </div>
          {outputs.answers && <Field label="Application questions" htmlFor="application-questions" hint={errors.questions ?? "One question per line works best; no answers are generated without questions."}><Textarea id="application-questions" value={questions} onChange={(event) => { setQuestions(event.target.value); setErrors((current) => ({ ...current, questions: undefined })); }} aria-invalid={Boolean(errors.questions)} aria-describedby="application-questions-description" placeholder="Why are you interested in this role?" /></Field>}
          {outputs.outreach && <OutreachFields value={outreach} update={updateOutreach} />}
          <div className="flex flex-col-reverse gap-3 border-t border-border-subtle pt-4 sm:flex-row sm:justify-between"><Button variant="ghost" onClick={() => setStep(1)}><ArrowLeft aria-hidden="true" className="size-[17px]" />Back</Button><Button variant="primary" onClick={() => { if (validateOutputs()) setStep(3); }}>Continue<ArrowRight aria-hidden="true" className="size-[17px]" /></Button></div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-5">
          <Card><h2 className="text-md font-semibold">Review</h2><dl className="mt-3 divide-y divide-border-subtle text-sm"><ReviewRow label="Resume" value={`${resume.length.toLocaleString()} characters`} /><ReviewRow label="Job description" value={`${job.length.toLocaleString()} characters`} /><ReviewRow label="Questions" value={outputs.answers ? `${questions.split(/\n+/).filter(Boolean).length} supplied` : "Not requested"} /><ReviewRow label="Outputs" value={selected.map((output) => output.label).join(", ")} /><ReviewRow label="Generation" value="Deterministic-first · provider optional · validated" /></dl></Card>
          <Banner tone="info" title="Truth-grounding is mandatory."><ShieldCheck aria-hidden="true" className="mr-1 inline size-4" />Unsupported claims are repaired or the affected artifact is withheld. They are never fabricated for ATS alignment.</Banner>
          {errors.submit && <Banner tone="danger" title="Submission failed.">{errors.submit}</Banner>}
          <div className="flex flex-col-reverse gap-3 border-t border-border-subtle pt-4 sm:flex-row sm:justify-between"><Button variant="ghost" disabled={submitting} onClick={() => setStep(2)}><ArrowLeft aria-hidden="true" className="size-[17px]" />Back</Button><Button variant="primary" disabled={submitting} onClick={() => void submit()}><WandSparkles aria-hidden="true" className="size-[17px]" />{submitting ? "Submitting…" : "Generate kit"}</Button></div>
        </div>
      )}
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return <div className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between sm:gap-5"><dt className="text-ink-muted">{label}</dt><dd className="text-pretty font-medium sm:text-right">{value}</dd></div>;
}

function OutreachFields({ value, update }: { value: OutreachContextInput; update: <K extends keyof OutreachContextInput>(key: K, value: OutreachContextInput[K]) => void }) {
  return (
    <section className="space-y-4 rounded-lg border border-border bg-surface p-5" aria-labelledby="outreach-context-title">
      <div><h3 id="outreach-context-title" className="font-semibold">LinkedIn outreach context</h3><p className="mt-1 text-sm text-ink-muted">Optional facts supplied here are target or relationship context—not candidate evidence. Drafts are never sent.</p></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Recipient name" htmlFor="recipient-name"><Input id="recipient-name" value={value.recipient_name ?? ""} onChange={(event) => update("recipient_name", event.target.value)} /></Field>
        <Field label="Recipient title" htmlFor="recipient-title"><Input id="recipient-title" value={value.recipient_title ?? ""} onChange={(event) => update("recipient_title", event.target.value)} /></Field>
        <Field label="Recipient company" htmlFor="recipient-company"><Input id="recipient-company" value={value.recipient_company ?? ""} onChange={(event) => update("recipient_company", event.target.value)} /></Field>
        <Field label="Audience" htmlFor="outreach-audience"><Select id="outreach-audience" value={value.audience ?? ""} onChange={(event) => update("audience", event.target.value ? event.target.value as OutreachAudience : undefined)}><option value="">Choose audience</option><option value="recruiter">Recruiter</option><option value="hiring_manager">Hiring manager</option><option value="employee">Employee</option><option value="teammate">Potential teammate</option><option value="alumni">Alumni</option><option value="professional_contact">Professional contact</option></Select></Field>
        <Field label="Intent" htmlFor="outreach-intent"><Select id="outreach-intent" value={value.requested_intent ?? ""} onChange={(event) => update("requested_intent", event.target.value ? event.target.value as OutreachIntent : undefined)}><option value="">Choose intent</option><option value="connect">Connect</option><option value="direct_message">Direct message</option><option value="follow_up">Follow up</option><option value="informational">Informational</option><option value="referral_request">Referral request</option><option value="shared_affiliation">Shared affiliation</option></Select></Field>
        <Field label="Application status" htmlFor="application-status"><Input id="application-status" value={value.application_status ?? ""} onChange={(event) => update("application_status", event.target.value)} /></Field>
      </div>
      <details className="rounded-md border border-border-subtle bg-surface-subtle p-4"><summary className="min-h-11 cursor-pointer font-semibold">More optional relationship context</summary><div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Application date" htmlFor="application-date"><Input id="application-date" type="date" value={value.application_date ?? ""} onChange={(event) => update("application_date", event.target.value)} /></Field>
        <Field label="Referral contact" htmlFor="referral-contact"><Input id="referral-contact" value={value.referral_contact_name ?? ""} onChange={(event) => update("referral_contact_name", event.target.value)} /></Field>
        <Field label="Shared affiliation" htmlFor="shared-affiliation"><Input id="shared-affiliation" value={value.shared_affiliation ?? ""} onChange={(event) => update("shared_affiliation", event.target.value)} /></Field>
        <Field label="Mutual connection" htmlFor="mutual-connection"><Input id="mutual-connection" value={value.mutual_connection ?? ""} onChange={(event) => update("mutual_connection", event.target.value)} /></Field>
        <Field label="Prior meeting" htmlFor="prior-meeting"><Input id="prior-meeting" value={value.prior_meeting ?? ""} onChange={(event) => update("prior_meeting", event.target.value)} /></Field>
        <Field label="Prior conversation" htmlFor="prior-conversation"><Input id="prior-conversation" value={value.prior_conversation ?? ""} onChange={(event) => update("prior_conversation", event.target.value)} /></Field>
        <Field label="Portfolio URL" htmlFor="portfolio-url"><Input id="portfolio-url" type="url" value={value.portfolio_url ?? ""} onChange={(event) => update("portfolio_url", event.target.value)} /></Field>
        <Field label="Personalization note" htmlFor="personalization-note"><Input id="personalization-note" value={value.personalization_note ?? ""} onChange={(event) => update("personalization_note", event.target.value)} /></Field>
      </div><label className="mt-4 flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" checked={value.has_applied ?? false} onChange={(event) => update("has_applied", event.target.checked)} className="size-5 accent-accent" />I have applied for this role</label></details>
    </section>
  );
}
