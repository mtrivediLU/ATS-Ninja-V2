"use client";

import { ArrowRight, Check, Scissors, ShieldAlert, TriangleAlert } from "lucide-react";
import { Banner, Button, Card, StatusLabel } from "@/components/ui/primitives";
import type { ArtifactValidation, Claim } from "@/lib/api-types";
import { artifactPresentationState, trustCounts } from "@/lib/artifact-presentation";
import { artifactStatePresentation } from "@/lib/status";

type TrustSummaryProps = {
  title: string;
  claims: Claim[];
  validation: ArtifactValidation;
  text: string;
  onOpenContent: () => void;
  manuallyEdited?: boolean;
  readinessLabel?: string;
  explanation?: string;
};

export function TrustSummary({
  title,
  claims,
  validation,
  text,
  onOpenContent,
  manuallyEdited = false,
  readinessLabel,
  explanation,
}: TrustSummaryProps) {
  const counts = trustCounts(claims, validation);
  const state = artifactPresentationState(validation, text, manuallyEdited);
  const traceable = counts.total > 0;
  const covered = counts.supported + counts.adjusted;
  const coverage = traceable ? Math.round((covered / counts.total) * 100) : null;
  const removedPercent = traceable ? Math.round((counts.removed / counts.total) * 100) : 0;
  const withheldPercent = traceable ? Math.round((counts.withheld / counts.total) * 100) : 0;
  const label = readinessLabel ?? readinessCopy(state, counts);
  const body = explanation ?? summaryCopy(state, counts, traceable);

  return (
    <section aria-labelledby={`${title.toLowerCase().replaceAll(" ", "-")}-trust`} className="mx-auto mt-5 max-w-[920px]">
      <Card className="overflow-hidden p-0 shadow-sm">
        <header className="flex flex-wrap items-center gap-3 border-b border-border-subtle px-5 py-4">
          <div className="grid size-9 place-items-center rounded-md border border-accent-border bg-accent-subtle text-accent"><Check aria-hidden="true" className="size-5" /></div>
          <div className="min-w-0 flex-1"><h2 id={`${title.toLowerCase().replaceAll(" ", "-")}-trust`} className="font-semibold">Trust summary — {title}</h2><p className="text-xs text-ink-muted">Engine trace and validation records, presented without a confidence score.</p></div>
          <StatusLabel presentation={artifactStatePresentation[state]} />
        </header>
        <div className="space-y-5 px-5 py-5">
          {manuallyEdited && <Banner tone="warning" title="Edited since generation.">Manual edits are local only and have not been revalidated against candidate evidence.</Banner>}
          <div>
            <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-semibold">Readiness</h3><span className="font-mono text-sm text-ink-secondary">{label}</span></div>
            {traceable ? <><div className="mt-2 flex h-2 overflow-hidden rounded-pill bg-[var(--readiness-track)]" aria-label={`Evidence trace distribution: ${coverage}% supported or adjusted, ${removedPercent}% removed, ${withheldPercent}% withheld`}><span className="bg-positive" style={{ width: `${coverage}%` }} /><span className="bg-danger" style={{ width: `${removedPercent + withheldPercent}%` }} /></div><p className="mt-2 text-xs text-ink-muted">Evidence trace distribution: {coverage}% supported or adjusted · {removedPercent}% removed · {withheldPercent}% withheld. This is not an engine score.</p></> : <p className="mt-2 text-sm text-ink-muted">No claim trace was returned for this artifact. Validation state is shown directly above.</p>}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Count label="Supported" count={counts.supported} icon={Check} tone="positive" />
            <Count label="Adjusted" count={counts.adjusted} icon={TriangleAlert} tone="warning" />
            <Count label="Removed" count={counts.removed} icon={Scissors} tone="danger" />
            <Count label="Withheld" count={counts.withheld} icon={ShieldAlert} tone="danger" />
            <Count label="Warnings" count={counts.warnings} icon={TriangleAlert} tone="warning" />
          </div>
          <p className="text-pretty text-sm leading-relaxed text-ink-secondary">{body}</p>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-accent-border bg-accent-subtle px-4 py-3"><p className="min-w-0 flex-1 text-sm text-positive"><strong>Next:</strong> Review the generated content and open an evidence trace where you need more context.</p><Button variant="primary" size="sm" onClick={onOpenContent}>Open content<ArrowRight aria-hidden="true" className="size-4" /></Button></div>
        </div>
      </Card>
    </section>
  );
}

function Count({ label, count, icon: Icon, tone }: { label: string; count: number; icon: typeof Check; tone: "positive" | "warning" | "danger" }) {
  const colors = tone === "positive" ? "text-positive" : tone === "warning" ? "text-warning" : "text-danger";
  return <div className="rounded-md border border-border-subtle bg-surface px-3 py-3"><p className={`font-mono text-xl font-semibold ${colors}`}>{count}</p><p className="mt-1 flex items-center gap-1.5 text-xs text-ink-muted"><Icon aria-hidden="true" className="size-3.5" />{label}</p></div>;
}

function readinessCopy(state: ReturnType<typeof artifactPresentationState>, counts: ReturnType<typeof trustCounts>): string {
  if (state === "withheld") return "Withheld — review the reason";
  if (state === "empty") return "No generated content";
  if (state === "edited") return "Edited locally — not revalidated";
  if (counts.withheld > 0) return `${counts.withheld} claim${counts.withheld === 1 ? "" : "s"} withheld`;
  if (counts.removed > 0 || counts.adjusted > 0 || counts.warnings > 0) return "Ready with notes";
  return "Generated";
}

function summaryCopy(state: ReturnType<typeof artifactPresentationState>, counts: ReturnType<typeof trustCounts>, traceable: boolean): string {
  if (state === "withheld") return "The engine withheld this artifact rather than allow a truth-critical or structural failure through. Review the available explanation before changing the source material or creating a new Kit.";
  if (!traceable) return "This artifact contains no candidate-claim trace records. Its delivery state reflects the persisted validation result, not a browser-generated assessment.";
  if (counts.removed > 0 || counts.adjusted > 0 || counts.withheld > 0) return "The engine kept the trace visible: unsupported content was removed or withheld, and any adjusted wording is called out so it is not mistaken for an unqualified claim.";
  return "The claim records returned with this artifact are supported by bounded candidate evidence. Generated content is still distinct from any later manual edit.";
}
