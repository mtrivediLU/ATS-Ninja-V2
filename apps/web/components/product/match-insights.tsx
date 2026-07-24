import Link from "next/link";

import type { AtsMatchScore, MatchReport } from "@/lib/api-types";
import { Badge, Banner, Card } from "@/components/ui/primitives";

/**
 * The v5 honest-scoring panel. Renders the three deliberately distinct scores
 * (original keyword match, tailored keyword match, evidence-based alignment),
 * the fit category, confidence with reasons, strengths, gaps, and the estimate
 * disclaimer. Never a single unexplained "ATS score"; never a percentage-shaped
 * interview probability.
 */

const FIT_LABEL: Record<string, string> = {
  strong_fit: "Strong fit",
  good_fit: "Good fit",
  partial_fit: "Partial fit",
  stretch_role: "Stretch role",
  low_alignment: "Low alignment",
};

const FIT_TONE: Record<string, "positive" | "warning" | "danger" | "neutral"> = {
  strong_fit: "positive",
  good_fit: "positive",
  partial_fit: "warning",
  stretch_role: "warning",
  low_alignment: "danger",
};

const CONFIDENCE_TONE: Record<string, "positive" | "warning" | "danger"> = {
  high: "positive",
  medium: "warning",
  low: "danger",
};

export function MatchInsights({ report }: { report: MatchReport }) {
  const fitLabel = FIT_LABEL[report.fit_category] ?? report.fit_category;
  const fitTone = FIT_TONE[report.fit_category] ?? "neutral";

  return (
    <section className="mt-6" aria-labelledby="match-insights-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="match-insights-heading" className="text-md font-semibold">
          Match insights
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={fitTone}>{fitLabel}</Badge>
          <span className="inline-flex items-center gap-1.5 text-xs text-ink-muted">
            <Badge tone={CONFIDENCE_TONE[report.confidence]}>{report.confidence} confidence</Badge>
          </span>
          <Link href="/scoring" className="text-xs font-semibold text-accent underline-offset-2 hover:underline">
            How scoring works
          </Link>
        </div>
      </div>

      <p className="mt-2 text-sm text-ink-secondary">{report.kit_summary}</p>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <ScoreMeter
          label="Original resume keyword match"
          description="Your submitted resume against the job's keywords."
          score={report.original_ats_match}
        />
        <ScoreMeter
          label="Tailored resume keyword match"
          description="The final, grounded resume against the same keywords."
          score={report.tailored_ats_match}
        />
        <AlignmentMeter label="Evidence-based role alignment" score={report.alignment_score} />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <TagList title="Top supported strengths" values={report.strongest_matches} tone="positive" />
        <TagList title="Must-have gaps" values={report.must_have_gaps} tone="danger" emptyLabel="No must-have gaps." />
      </div>

      {report.keywords_surfaced_by_tailoring.length > 0 && (
        <p className="mt-3 text-sm text-ink-secondary">
          <span className="font-semibold">Surfaced by tailoring:</span>{" "}
          {report.keywords_surfaced_by_tailoring.join(", ")}
        </p>
      )}

      <Card className="mt-4 shadow-none">
        <h3 className="text-sm font-semibold">Score confidence</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-secondary">
          {report.confidence_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </Card>

      <Card className="mt-4 shadow-none">
        <h3 className="text-sm font-semibold">Recommendation</h3>
        <p className="mt-2 text-sm text-ink-secondary">{report.recommendation}</p>
      </Card>

      <Banner tone="neutral" className="mt-4" title="These scores are estimates.">
        {report.disclaimer}
      </Banner>
    </section>
  );
}

function ScoreMeter({
  label,
  description,
  score,
}: {
  label: string;
  description: string;
  score: AtsMatchScore | null;
}) {
  if (score === null) {
    return (
      <Card className="shadow-none">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">{label}</p>
        <p className="mt-2 font-mono text-2xl font-semibold text-ink-muted">n/a</p>
        <p className="mt-1 text-xs text-ink-muted">Not produced for this kit.</p>
      </Card>
    );
  }
  const rounded = Math.round(score.score);
  return (
    <Card className="shadow-none">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">{label}</p>
      <p
        className="mt-2 font-mono text-2xl font-semibold"
        aria-label={`${label}: ${rounded} out of 100`}
      >
        {rounded}
        <span className="text-sm text-ink-muted"> / 100</span>
      </p>
      <Meter value={rounded} label={label} />
      <p className="mt-2 text-xs text-ink-muted">{description}</p>
      <p className="mt-1 text-[11px] text-ink-muted">
        {score.matched_keywords.length} of {score.total_keywords} keywords matched
      </p>
    </Card>
  );
}

function AlignmentMeter({ label, score }: { label: string; score: number }) {
  const rounded = Math.round(score);
  return (
    <Card className="shadow-none">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">{label}</p>
      <p className="mt-2 font-mono text-2xl font-semibold" aria-label={`${label}: ${rounded} out of 100`}>
        {rounded}
        <span className="text-sm text-ink-muted"> / 100</span>
      </p>
      <Meter value={rounded} label={label} />
      <p className="mt-2 text-xs text-ink-muted">Reproducible requirement-coverage index, not a probability.</p>
    </Card>
  );
}

function Meter({ value, label }: { value: number; label: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      className="mt-2 h-2 w-full overflow-hidden rounded-pill bg-surface-raised"
      role="meter"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className="h-full rounded-pill bg-accent" style={{ width: `${clamped}%` }} />
    </div>
  );
}

function TagList({
  title,
  values,
  tone,
  emptyLabel = "None returned.",
}: {
  title: string;
  values: string[];
  tone: "positive" | "danger";
  emptyLabel?: string;
}) {
  const classes =
    tone === "positive"
      ? "border-positive-border bg-positive-bg text-positive"
      : "border-danger-border bg-danger-bg text-danger";
  return (
    <Card className="shadow-none">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="mt-2 flex flex-wrap gap-2">
        {values.length ? (
          values.map((value) => (
            <span key={value} className={`rounded-pill border px-2.5 py-1 text-sm ${classes}`}>
              {value}
            </span>
          ))
        ) : (
          <span className="text-sm text-ink-muted">{emptyLabel}</span>
        )}
      </div>
    </Card>
  );
}
