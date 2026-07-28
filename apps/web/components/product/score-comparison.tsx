import type { DocumentState, MatchReport } from "@/lib/api-types";
import { Card } from "@/components/ui/primitives";
import { scoreComparisonState } from "@/lib/results-presentation";

/**
 * The compact original-vs-tailored ATS keyword-match comparison. Distinct from
 * the fuller `MatchInsights` panel (moved into the advanced details area): this
 * is the two-panel-plus-delta summary a candidate needs at a glance. Never
 * invents an improvement — a flat or lower tailored score is stated plainly.
 */
export function ScoreComparison({ report, resumeState }: { report: MatchReport; resumeState?: DocumentState }) {
  const state = scoreComparisonState(
    Math.round(report.original_ats_match.score),
    report.tailored_ats_match ? Math.round(report.tailored_ats_match.score) : null,
    resumeState === "generated_with_fallback",
  );

  return (
    <section aria-labelledby="score-comparison-heading" className="mt-6">
      <h2 id="score-comparison-heading" className="text-md font-semibold">
        Your ATS keyword match
      </h2>
      <p className="mt-1 text-sm text-ink-secondary">
        Both résumés were evaluated against the same job-specific keyword set.
      </p>
      <span className="sr-only" role="status">
        {state.srSummary}
      </span>
      <div aria-hidden="true" className="mt-3 grid gap-3 sm:grid-cols-2">
        <ScorePanel label="Original résumé" score={state.original} />
        <ScorePanel label={state.deliveredLabel} score={state.tailored} tinted />
      </div>
      {state.deltaLabel && (
        <p aria-hidden="true" className="mt-3 text-sm font-semibold text-ink">
          {state.deltaLabel}
        </p>
      )}
      {state.noteLabel && (
        <p aria-hidden="true" className="mt-1 text-xs text-ink-muted">
          {state.noteLabel}
        </p>
      )}
      <p className="mt-3 text-xs text-ink-muted">{report.disclaimer}</p>
    </section>
  );
}

function ScorePanel({ label, score, tinted = false }: { label: string; score: number | null; tinted?: boolean }) {
  return (
    <Card className={`shadow-none ${tinted ? "border-accent/40 bg-accent-subtle" : ""}`}>
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-ink-muted">{label}</p>
      {score === null ? (
        <p className="mt-2 font-mono text-2xl font-semibold text-ink-muted">n/a</p>
      ) : (
        <p className="mt-2 font-mono text-2xl font-semibold">
          {score}
          <span className="text-sm text-ink-muted"> / 100</span>
        </p>
      )}
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-pill bg-surface-raised">
        <div className="h-full rounded-pill bg-accent" style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }} />
      </div>
      <p className="mt-2 text-[11px] text-ink-muted">ATS keyword match against this job description.</p>
    </Card>
  );
}
