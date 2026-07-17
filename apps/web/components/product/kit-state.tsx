"use client";

import Link from "next/link";
import { AlertCircle, ArrowLeft, RefreshCw } from "lucide-react";
import { useKit } from "@/components/product/kit-context";
import { Banner, Button, Card, ProcessingState, type ProcessingStep, buttonClassName } from "@/components/ui/primitives";
import { kitStatusPresentation } from "@/lib/status";

const processingSteps: ProcessingStep[] = [
  { label: "Parse resume and job description", state: "done" },
  { label: "Extract candidate evidence", state: "done" },
  { label: "Match and score requirements deterministically", state: "active" },
  { label: "Generate validated prose", state: "pending" },
  { label: "Ground claims against evidence", state: "pending" },
  { label: "Validate and assemble ApplicationKit", state: "pending" },
];

export function KitStateBoundary({ children }: { children: React.ReactNode }) {
  const { kit, loading, error, delayed, refresh } = useKit();
  if (loading && !kit) return <LoadingKit />;
  if (error && !kit) return <ApiFailure message={error.message} onRetry={() => void refresh()} />;
  if (!kit) return <ApiFailure message="The Kit response was unavailable." onRetry={() => void refresh()} />;
  if (kit.status === "pending" || kit.status === "processing") return <ProcessingKit delayed={delayed} status={kit.status} />;
  if (kit.status === "failed") return <FailedKit message={kit.error} />;
  if (!kit.result) return <ApiFailure message="The completed Kit did not contain an ApplicationKit result." onRetry={() => void refresh()} />;
  return <>{children}</>;
}

function LoadingKit() {
  return <div aria-live="polite" aria-busy="true" className="mx-auto max-w-[580px] py-10"><Card><div className="h-3 w-2/5 animate-pulse rounded-sm bg-border-subtle" /><div className="mt-3 h-3 animate-pulse rounded-sm bg-border-subtle" /><div className="mt-2 h-3 w-4/5 animate-pulse rounded-sm bg-border-subtle" /><p className="sr-only">Loading Kit status.</p></Card></div>;
}

function ProcessingKit({ delayed, status }: { delayed: boolean; status: "pending" | "processing" }) {
  return (
    <div aria-live="polite" className="space-y-4">
      <Banner tone="neutral" title={`${status === "pending" ? "Pending" : "Processing"}.`}>Status is read from the API. The step list explains the deterministic-first pipeline; it is not per-step telemetry.</Banner>
      <div className="h-1.5 overflow-hidden rounded-pill bg-surface-raised" aria-hidden="true"><div className="h-full w-1/3 animate-pulse rounded-pill bg-accent" /></div>
      <ProcessingState slow={delayed} title="Assembling a truth-grounded kit" description="The page polls safely until the server reports completed or failed. Leaving this page does not cancel server-side processing." steps={processingSteps} />
      <div className="flex justify-center"><Link href="/history" className={buttonClassName("secondary")}><ArrowLeft aria-hidden="true" className="size-[17px]" />View history</Link></div>
    </div>
  );
}

function FailedKit({ message }: { message: string | null }) {
  return <div className="mx-auto max-w-[620px] py-8"><Card className="text-center"><div className="mx-auto grid size-16 place-items-center rounded-lg border border-danger-border bg-danger-bg text-danger"><AlertCircle aria-hidden="true" className="size-8" /></div><h2 className="mt-4 text-lg font-semibold">Kit generation failed</h2><p className="mt-2 text-pretty text-ink-secondary">{message || "The worker reported a client-safe generation failure. No raw exception detail is shown."}</p><div className="mt-5 flex flex-wrap justify-center gap-3"><span className="inline-flex">{statusBadge()}</span><Link href="/kits/new" className={buttonClassName("primary")}><RefreshCw aria-hidden="true" className="size-[17px]" />Start a new Kit</Link><Link href="/history" className={buttonClassName()}>Return to history</Link></div></Card></div>;
}

function ApiFailure({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="mx-auto max-w-[620px] py-8"><Card className="text-center"><div className="mx-auto grid size-16 place-items-center rounded-lg border border-danger-border bg-danger-bg text-danger"><AlertCircle aria-hidden="true" className="size-8" /></div><h2 className="mt-4 text-lg font-semibold">Kit unavailable</h2><p className="mt-2 text-pretty text-ink-secondary">{message}</p><div className="mt-5 flex flex-wrap justify-center gap-3"><Button variant="primary" onClick={onRetry}><RefreshCw aria-hidden="true" className="size-[17px]" />Try again</Button><Link href="/history" className={buttonClassName()}>Return to history</Link></div></Card></div>;
}

function statusBadge() {
  const presentation = kitStatusPresentation.failed;
  const Icon = presentation.icon;
  return <span className="inline-flex items-center gap-1.5 rounded-pill border border-danger-border bg-danger-bg px-2.5 py-1 text-xs font-semibold text-danger"><Icon aria-hidden="true" className="size-3.5" />Failed</span>;
}
