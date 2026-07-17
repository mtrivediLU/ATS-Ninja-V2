import { ArrowLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import { Button, Card, StatusLabel } from "@/components/ui/primitives";
import { artifactStatePresentation, type ArtifactPresentationState } from "@/lib/status";

const copy: Record<ArtifactPresentationState, string> = {
  generated: "The generated artifact is available with its server-provided trace.",
  warning: "The artifact is available with validation notes to review.",
  withheld: "The engine withheld this artifact rather than allow a truth-critical or structural validation failure through.",
  "not-requested": "This is an intentional absence from the persisted selection, not a generation failure.",
  unavailable: "This artifact was selected, but the completed response did not include it. No substitute content is inferred.",
  failed: "This artifact could not be generated. The failure is surfaced without internal error detail.",
  empty: "The API returned an empty artifact. No content is invented in the browser.",
  edited: "This local version differs from generation and has not been revalidated.",
  "old-schema": "This Kit was created under an older contract and is presented through the compatibility boundary.",
  partial: "Some requested content is available while another portion is missing.",
};

export function ArtifactState({ title, state, reason, onRetry }: { title: string; state: ArtifactPresentationState; reason?: string; onRetry?: () => void }) {
  const presentation = artifactStatePresentation[state];
  const Icon = presentation.icon;
  return <Card className={`mx-auto max-w-[680px] text-center ${state === "unavailable" || state === "empty" ? "border-dashed" : ""}`}><div className={`mx-auto grid size-14 place-items-center rounded-lg border ${presentation.tone === "danger" ? "border-danger-border bg-danger-bg text-danger" : presentation.tone === "unavailable" ? "border-unavailable-border border-dashed bg-unavailable-bg text-unavailable" : "border-border bg-surface-subtle text-ink-muted"}`}><Icon aria-hidden="true" className="size-7" /></div><div className="mt-4"><StatusLabel presentation={presentation} /></div><h2 className="mt-3 text-lg font-semibold">{title}</h2><p className="mt-2 text-sm text-ink-secondary">{reason || copy[state]}</p><div className="mt-5 flex flex-wrap justify-center gap-3">{onRetry && <Button variant="primary" onClick={onRetry}><RefreshCw aria-hidden="true" className="size-4" />Retry retrieval</Button>}<Link href="/history" className="inline-flex min-h-11 items-center gap-2 rounded-control border border-border-strong bg-surface px-4 py-2 font-semibold text-ink hover:bg-surface-subtle"><ArrowLeft aria-hidden="true" className="size-4" />Return to history</Link></div></Card>;
}

export function NotRequestedArtifact({ title }: { title: string }) { return <ArtifactState title={`${title} was not requested`} state="not-requested" />; }
export function WithheldArtifact({ title, reason }: { title: string; reason?: string }) { return <ArtifactState title={`${title} was withheld`} state="withheld" reason={reason} />; }
