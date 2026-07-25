"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import type { MatchReport } from "@/lib/api-types";
import { Button } from "@/components/ui/primitives";

const VISIBLE_LIMIT = 8;

/**
 * Compact, evidence-backed "keywords added" chip row. Sourced from the
 * engine's `keywords_surfaced_by_tailoring` — the keyword was absent from the
 * original resume's credited matches, is now genuinely matched in the
 * tailored resume, and (like every credited keyword) only counts when the
 * candidate's own parsed evidence supports it. The browser never derives this
 * distinction itself.
 */
export function KeywordsAdded({ report, onSeeWhereTheseAppear }: { report: MatchReport; onSeeWhereTheseAppear?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const added = report.keywords_surfaced_by_tailoring;
  const visible = expanded ? added : added.slice(0, VISIBLE_LIMIT);
  const overflow = added.length - visible.length;

  return (
    <section aria-labelledby="keywords-added-heading" className="mt-6">
      <h2 id="keywords-added-heading" className="text-md font-semibold">
        Keywords added to strengthen your match
      </h2>
      {added.length === 0 ? (
        <p className="mt-2 text-sm text-ink-secondary">No new evidence-backed keywords were added.</p>
      ) : (
        <>
          <ul className="mt-3 flex flex-wrap gap-2">
            {visible.map((keyword) => (
              <li
                key={keyword}
                className="inline-flex items-center gap-1.5 rounded-pill border border-positive-border bg-positive-bg px-2.5 py-1 text-sm text-positive"
              >
                <Sparkles aria-hidden="true" className="size-3.5" />
                {keyword}
              </li>
            ))}
            {overflow > 0 && (
              <li>
                <Button size="sm" variant="ghost" onClick={() => setExpanded(true)}>
                  +{overflow} more
                </Button>
              </li>
            )}
          </ul>
          <p className="mt-2 text-sm text-ink-secondary">Only keywords supported by your existing experience were added.</p>
          {onSeeWhereTheseAppear && (
            <Button size="sm" variant="ghost" className="mt-1 px-0" onClick={onSeeWhereTheseAppear}>
              See where these appear
            </Button>
          )}
        </>
      )}
    </section>
  );
}
