import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Clock3, CloudOff, LoaderCircle } from "lucide-react";
import { Button, Card } from "@/components/ui/primitives";

export type RecoveryStateKey = "pending" | "processing" | "slow" | "unavailable" | "malformed" | "failed" | "restored";

const presentation = {
  pending: { icon: Clock3, title: "Queued for generation", body: "Your Kit is queued. It will continue when processing capacity is available; you can return to history safely.", tone: "info" },
  processing: { icon: LoaderCircle, title: "Generating your Kit", body: "Deterministic work runs first. Generated prose is validated before it becomes part of the ApplicationKit.", tone: "info" },
  slow: { icon: Clock3, title: "Still processing", body: "This is taking longer than usual. The Kit continues in the background; no estimate or percentage is available.", tone: "warning" },
  unavailable: { icon: CloudOff, title: "Local service unavailable", body: "The latest Kit state could not be retrieved. Check that the local API is running, then retry retrieval.", tone: "danger" },
  malformed: { icon: AlertCircle, title: "Couldn't read the Kit result", body: "The response was not in an expected shape. This is safe to retry; no generated content is shown as a substitute.", tone: "danger" },
  failed: { icon: AlertCircle, title: "Kit generation failed", body: "The failure was surfaced instead of being hidden. Create another Kit or return to history; internal processing details are not displayed here.", tone: "danger" },
  restored: { icon: CheckCircle2, title: "Connection restored", body: "The local API is reachable again and the latest Kit state was loaded.", tone: "positive" },
} as const;

export function RecoveryState({ state, actions, pulse = false }: { state: RecoveryStateKey; actions?: ReactNode; pulse?: boolean }) {
  const item = presentation[state];
  const Icon = item.icon;
  const iconClasses = item.tone === "danger" ? "border-danger-border bg-danger-bg text-danger" : item.tone === "warning" ? "border-warning-border bg-warning-bg text-warning" : item.tone === "positive" ? "border-positive-border bg-positive-bg text-positive" : "border-info-border bg-info-bg text-info";
  return <section className="mx-auto max-w-[620px] py-8 text-center" aria-live="polite" role="status"><Card><div className={`mx-auto grid size-16 place-items-center rounded-lg border ${iconClasses}`}><Icon aria-hidden="true" className={`size-8 ${pulse ? "motion-safe:animate-spin" : ""}`} /></div><h2 className="mt-4 text-lg font-semibold">{item.title}</h2><p className="mt-2 text-pretty text-sm leading-relaxed text-ink-secondary">{item.body}</p>{pulse && <div aria-hidden="true" className="mt-4 flex justify-center gap-1.5"><span className="size-2 animate-pulse rounded-pill bg-info" /><span className="size-2 animate-pulse rounded-pill bg-info [animation-delay:160ms]" /><span className="size-2 animate-pulse rounded-pill bg-info [animation-delay:320ms]" /></div>}{actions && <div className="mt-5 flex flex-wrap justify-center gap-3">{actions}</div>}</Card></section>;
}

export function RetryButton({ onClick }: { onClick: () => void }) { return <Button variant="primary" onClick={onClick}>Retry retrieval</Button>; }
