"use client";

import { Check, Scissors, ShieldAlert, TriangleAlert } from "lucide-react";
import { useKit } from "@/components/product/kit-context";
import { Button, Card } from "@/components/ui/primitives";
import { trustCounts } from "@/lib/artifact-presentation";
import type { ArtifactValidation } from "@/lib/api-types";

export function KitTrustStrip() {
  const { kit, claims, openEvidence, setEvidenceFilters } = useKit();
  if (!kit?.result) return null;
  const validation: ArtifactValidation = {
    status: kit.result.validation.passed ? "passed" : "notes",
    fatal: kit.result.validation.fatal,
    errors: kit.result.validation.errors,
    warnings: kit.result.validation.warnings,
    repaired_claims: 0,
    rejected_claims: 0,
  };
  const counts = trustCounts(claims, validation);
  function reviewWarnings() {
    setEvidenceFilters({ status: counts.withheld || counts.removed ? "withheld" : "all" });
    openEvidence();
  }
  return <section aria-labelledby="kit-trust-heading">
    <Card className="flex flex-wrap items-center gap-3 py-3 shadow-none">
      <div className="min-w-0 flex-1"><h2 id="kit-trust-heading" className="text-sm font-semibold">Kit trust</h2><p className="text-xs text-ink-muted">Persisted evidence and validation records — not a confidence score.</p></div>
      <div className="flex flex-wrap gap-2 text-xs font-semibold">
        <Count label="Supported" count={counts.supported} icon={Check} tone="text-positive" />
        <Count label="Adjusted" count={counts.adjusted} icon={TriangleAlert} tone="text-warning" />
        <Count label="Removed" count={counts.removed} icon={Scissors} tone="text-danger" />
        <Count label="Withheld" count={counts.withheld} icon={ShieldAlert} tone="text-danger" />
      </div>
      <Button size="sm" variant="secondary" onClick={reviewWarnings}><TriangleAlert aria-hidden="true" className="size-4" />Review {counts.warnings} warning{counts.warnings === 1 ? "" : "s"}</Button>
    </Card>
  </section>;
}

function Count({ label, count, icon: Icon, tone }: { label: string; count: number; icon: typeof Check; tone: string }) {
  return <span className={`inline-flex items-center gap-1 rounded-pill border border-border bg-surface-subtle px-2 py-1 ${tone}`}><Icon aria-hidden="true" className="size-3.5" />{count} {label.toLowerCase()}</span>;
}
