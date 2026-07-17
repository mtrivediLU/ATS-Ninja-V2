"use client";

import { useState } from "react";
import { Check, Plus, WandSparkles } from "lucide-react";
import { Banner, Button, Card, Checkbox, Field, Section, Switch, Textarea } from "@/components/ui/primitives";

const outputs = ["Resume", "Cover letter", "Application answers", "Job fit", "Interview prep", "LinkedIn outreach"];

export function NewKitFoundation() {
  const [selected, setSelected] = useState(() => new Set(["Resume", "Cover letter", "Job fit"]));
  const [notice, setNotice] = useState(false);

  function toggle(label: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <Banner tone="neutral" title="D0 foundation only.">
        These controls demonstrate layout and states with synthetic placeholders. They do not submit, upload, poll, score, or call the API.
      </Banner>

      <section className="rounded-lg border border-accent-border bg-accent-subtle px-5 py-6 sm:px-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="max-w-2xl">
            <p className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-positive">First use</p>
            <h2 className="mt-1 text-xl font-bold leading-tight tracking-[-0.01em]">Start a truth-grounded application kit</h2>
            <p className="mt-2 text-pretty text-base text-ink-secondary">The production workflow arrives in D1. This foundation reserves the approved input, output-selection, processing, and evidence surfaces.</p>
          </div>
          <Button variant="primary" onClick={() => document.getElementById("resume-placeholder")?.focus()}>
            <Plus aria-hidden="true" className="size-[17px]" /> Start placeholder
          </Button>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Field label="Resume" htmlFor="resume-placeholder" hint="Plain-text placeholder. PDF upload is out of scope for D0.">
          <Textarea id="resume-placeholder" aria-describedby="resume-placeholder-description" placeholder="Paste resume text… (not stored or submitted)" />
        </Field>
        <Field label="Job description" htmlFor="jd-placeholder" hint="Synthetic layout only; no requirements are extracted in the browser.">
          <Textarea id="jd-placeholder" aria-describedby="jd-placeholder-description" placeholder="Paste the target job description… (not submitted)" />
        </Field>
      </div>

      <Section title="Outputs to generate" description="Presentation-only selection state; no API contract is invoked.">
        <div className="flex flex-wrap gap-2">
          {outputs.map((output) => {
            const active = selected.has(output);
            return (
              <button
                key={output}
                type="button"
                aria-pressed={active}
                onClick={() => toggle(output)}
                className="inline-flex min-h-11 items-center gap-2 rounded-pill border border-border-strong bg-surface px-3 text-sm text-ink-secondary transition-colors hover:bg-surface-subtle aria-pressed:border-accent-border aria-pressed:bg-accent-subtle aria-pressed:font-semibold aria-pressed:text-positive sm:min-h-10"
              >
                {active && <Check aria-hidden="true" className="size-4" />}
                {output}
              </button>
            );
          })}
        </div>
      </Section>

      <Card>
        <h2 className="text-base font-semibold">Foundation options</h2>
        <div className="mt-3 grid gap-2">
          <Switch id="evidence-default" label="Include evidence trace with every claim" defaultChecked />
          <Switch id="deterministic-default" label="Prefer deterministic-only generation" />
          <Checkbox id="confirm-synthetic" label="I understand this D0 form is not connected" defaultChecked />
        </div>
      </Card>

      {notice && <Banner tone="info" title="Not submitted.">D0 intentionally stops before real Kit creation and polling.</Banner>}

      <div className="flex flex-wrap gap-3">
        <Button variant="primary" onClick={() => setNotice(true)}>
          <WandSparkles aria-hidden="true" className="size-[17px]" /> Demonstrate generate action
        </Button>
        <Button variant="ghost" onClick={() => setNotice(false)}>Clear demonstration</Button>
      </div>
    </div>
  );
}
