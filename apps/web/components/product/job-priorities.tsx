import type { MatchReport } from "@/lib/api-types";

/**
 * "What matters most for this job" — 4-6 natural-language bullets sourced
 * from the engine's JD analysis (`matchReport.job_priorities[]`). Describes
 * what the employer is asking for; never a requirement table, never a
 * per-requirement evidence label (that lives in the advanced area only).
 */
export function JobPriorities({ report }: { report: MatchReport }) {
  const priorities = report.job_priorities;
  return (
    <section aria-labelledby="job-priorities-heading" className="mt-6">
      <h2 id="job-priorities-heading" className="text-md font-semibold">
        What matters most for this job
      </h2>
      {priorities.length === 0 ? (
        <p className="mt-2 text-sm text-ink-secondary">Job priorities were not detected for this posting.</p>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {priorities.map((priority) => (
            <li key={priority.theme} className="flex gap-2.5 text-sm text-ink-secondary">
              <span aria-hidden="true" className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" />
              <p>
                <span className="font-semibold text-ink">{priority.theme}.</span> {priority.detail}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
