/**
 * Pure presentation logic for the results-first page (`ResultsHeader`,
 * `ScoreComparison`). Kept out of the `.tsx` components so it is directly
 * unit-testable with the plain Node test runner (which strips `.ts` types but
 * cannot parse JSX in `.tsx`).
 */

export function buildHeadline({
  name,
  role,
  company,
  hasRole,
  hasCompany,
  lifecycle = "completed",
  targetConfirmed = true,
}: {
  name: string;
  role: string;
  company: string;
  hasRole: boolean;
  hasCompany: boolean;
  lifecycle?: "completed" | "partially_completed" | "needs_input_review" | "failed";
  targetConfirmed?: boolean;
}): string {
  if (!targetConfirmed) return "Review the detected role and organization for this Application Kit.";
  const greeting = name ? `Hi ${name}, your` : "Your";
  if (!hasRole && !hasCompany) return `${greeting} Application Kit is ready.`;
  const subject = hasRole && hasCompany ? `Application Kit for the ${role} position at ${company}` : hasRole ? `Application Kit for the ${role} position` : `Application Kit for this position at ${company}`;
  if (lifecycle === "partially_completed") return `${greeting} ${subject} was partially delivered.`;
  if (lifecycle === "needs_input_review") return `${greeting} ${subject} needs input review.`;
  if (lifecycle === "failed") return `${greeting} ${subject} could not be delivered.`;
  return `${greeting} ${subject} is ready. All the best!`;
}

export type ScoreComparisonState = {
  original: number;
  tailored: number | null;
  deliveredLabel: string;
  delta: number | null;
  srSummary: string;
  deltaLabel: string | null;
  noteLabel: string | null;
};

/**
 * Pure derivation of the score-comparison state: the honest delta label, the
 * accessible summary sentence, and the note shown for the flat/lower/
 * unavailable cases. Never invents an improvement — a flat or lower tailored
 * score is stated plainly, and an absent tailored score is never treated as
 * zero.
 */
export function scoreComparisonState(
  original: number,
  tailored: number | null,
  deliveredAsFallback = false,
): ScoreComparisonState {
  const delta = tailored === null ? null : tailored - original;
  const deliveredLabel = deliveredAsFallback ? "Delivered résumé match" : "Tailored résumé";

  const srSummary =
    tailored === null
      ? `Original resume keyword match: ${original} out of 100. A tailored resume was not produced for this kit.`
      : `Original resume keyword match: ${original} out of 100. ${deliveredAsFallback ? "Delivered resume" : "Tailored resume"} keyword match: ${tailored} out of 100. ${
          delta === 0 ? "No score change." : delta && delta > 0 ? `Improved by ${delta} points.` : `Lower by ${Math.abs(delta ?? 0)} points.`
        }`;

  const deltaLabel =
    delta === null
      ? null
      : delta === 0
        ? deliveredAsFallback
          ? "0 · No safe evidence-backed improvement was accepted."
          : "0 · No score change."
        : delta > 0
          ? deliveredAsFallback
            ? `+${delta} points in the delivered evidence-backed résumé`
            : `+${delta} points after evidence-backed tailoring`
          : `${delta} points — unsupported content removed`;

  const noteLabel =
    tailored === null
      ? "A tailored resume was not produced for this kit, so only the original match is shown."
      : deliveredAsFallback
        ? "This is the authoritative ATS v2 score for the source-preserving résumé that was delivered."
      : delta !== null && delta < 0
        ? "The tailored match reflects grounding removing content your resume did not support, so this resume is more accurate, not weaker."
        : null;

  return { original, tailored, deliveredLabel, delta, srSummary, deltaLabel, noteLabel };
}
