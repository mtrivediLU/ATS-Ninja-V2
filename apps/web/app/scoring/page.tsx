import type { Metadata } from "next";

import { Banner, Card } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "How scoring works" };

export default function ScoringPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">How scoring works</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          ATS-Ninja reports three separate scores plus an honest fit category. They are deterministic
          estimates from keyword and evidence analysis, never a prediction of any employer&apos;s decision.
        </p>
      </div>

      <Card>
        <h2 className="text-md font-semibold">The three scores</h2>
        <dl className="mt-3 space-y-3 text-sm">
          <div>
            <dt className="font-semibold">Original resume keyword match</dt>
            <dd className="text-ink-secondary">
              Your submitted resume measured against a unified set of keywords drawn only from the job
              description. A keyword counts once (frequency never helps) and only when your parsed evidence
              genuinely supports it.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Tailored resume keyword match</dt>
            <dd className="text-ink-secondary">
              The same measurement against the final, grounded resume. Only content that survives the
              truth-grounding pipeline earns credit, so this can be lower than the original when unsupported
              claims were removed. That means the resume is more accurate, not weaker.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Evidence-based role alignment</dt>
            <dd className="text-ink-secondary">
              A reproducible requirement-coverage index built from the evidence matrix (proven, adjacent,
              working-knowledge, or gap for each requirement). It is not a probability or a guarantee.
            </dd>
          </div>
        </dl>
      </Card>

      <Card>
        <h2 className="text-md font-semibold">Confidence and fit categories</h2>
        <p className="mt-2 text-sm text-ink-secondary">
          Score confidence (high, medium, low) reflects how clean the inputs were: whether a real target
          title was found, how many requirements were detected, and how well your resume parsed. The fit
          category is one of strong fit, good fit, partial fit, stretch role, or low alignment, derived from
          role alignment and the number of must-have gaps. Two or more must-have gaps never classify better
          than a stretch role.
        </p>
      </Card>

      <Card>
        <h2 className="text-md font-semibold">Why we never invent skills</h2>
        <p className="mt-2 text-sm text-ink-secondary">
          A missing skill is never inserted into your resume to raise a score. Pasting the job description
          into your resume, repeating keywords, or padding prose cannot raise any score, because credit is
          gated on your own parsed evidence. Unsupported claims are removed before delivery.
        </p>
      </Card>

      <Card>
        <h2 className="text-md font-semibold">Why grounding removals cannot be restored</h2>
        <p className="mt-2 text-sm text-ink-secondary">
          When the pipeline removes an unsupported claim, that removal is recorded in the change ledger and
          marked permanent. You can accept or reject ordinary tailoring changes, but a truth-grounding
          removal can never be brought back, so a fabricated fact can never re-enter a delivered document.
        </p>
      </Card>

      <Banner tone="neutral" title="Estimates, not decisions.">
        Every number here is a deterministic estimate from keyword and evidence analysis, not a prediction of
        any employer&apos;s decision.
      </Banner>
    </div>
  );
}
