import { CheckCircle2, Info } from "lucide-react";
import type { MatchReport } from "@/lib/api-types";
import { Card } from "@/components/ui/primitives";

const MAX_STRENGTHS = 5;
const MAX_GAPS = 4;

/**
 * "Where you fit" — exactly two panels (strengths / gaps) and no others.
 * Gaps are honest: only what the resume did not show, never a judgment about
 * the candidate's ability.
 */
export function FitPanels({ report }: { report: MatchReport }) {
  const strengths = report.strongest_matches.slice(0, MAX_STRENGTHS);
  // Must-have gaps are the most important to see first; back-fill with other
  // genuine gaps up to the display limit, without duplicating any keyword.
  const gaps = [...report.must_have_gaps, ...report.genuine_gaps.filter((gap) => !report.must_have_gaps.includes(gap))].slice(
    0,
    MAX_GAPS,
  );

  return (
    <section aria-labelledby="fit-panels-heading" className="mt-6">
      <h2 id="fit-panels-heading" className="text-md font-semibold">
        Where you fit
      </h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <FitPanel title="Your strengths" tone="positive" items={strengths} emptyLabel="No strong matches were identified for this job." />
        <FitPanel title="Gaps to be aware of" tone="warning" items={gaps} emptyLabel="No genuine gaps were identified for this job." />
      </div>
      <p className="mt-3 text-xs text-ink-muted">
        Gaps reflect what was documented in your résumé, not your ability to learn or perform the work.
      </p>
    </section>
  );
}

function FitPanel({
  title,
  tone,
  items,
  emptyLabel,
}: {
  title: string;
  tone: "positive" | "warning";
  items: string[];
  emptyLabel: string;
}) {
  const Icon = tone === "positive" ? CheckCircle2 : Info;
  const accentClass = tone === "positive" ? "border-t-positive" : "border-t-warning";
  const iconClass = tone === "positive" ? "text-positive" : "text-warning";
  return (
    <Card className={`shadow-none border-t-[3px] ${accentClass}`}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-ink-muted">{emptyLabel}</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {items.map((item) => (
            <li key={item} className="flex items-start gap-2 text-sm text-ink-secondary">
              <Icon aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${iconClass}`} />
              {item}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
