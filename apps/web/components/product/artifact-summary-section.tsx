"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { ExpandableArtifact } from "@/components/product/expandable-artifact";
import { Button, Card, StatusLabel } from "@/components/ui/primitives";
import type { ArtifactPresentationState } from "@/lib/status";
import { artifactStatePresentation } from "@/lib/status";

type ArtifactSummarySectionProps = {
  artifact: string;
  title: string;
  state: ArtifactPresentationState;
  summary: string;
  primaryLabel?: string;
  onPrimary?: () => void;
  onRetry?: () => void;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  kitId: string;
  route: string;
  children?: React.ReactNode;
};

export function ArtifactSummarySection({ artifact, title, state, summary, primaryLabel, onPrimary, onRetry, expanded, onExpandedChange, kitId, route, children }: ArtifactSummarySectionProps) {
  const available = state !== "not-requested" && state !== "unavailable" && state !== "withheld";
  return <article id={artifact} className="k1-artifact-row">
    <Card className="shadow-none"><div className="flex min-h-[var(--artifact-row-min-h)] flex-wrap items-center gap-3"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{title}</h3><StatusLabel presentation={artifactStatePresentation[state]} /></div><p className="mt-1 text-sm text-ink-muted">{summary}</p></div>{available && primaryLabel && onPrimary && <Button size="sm" variant="primary" onClick={onPrimary}>{primaryLabel}</Button>}{available && children && <ExpandableArtifact artifact={artifact} expanded={expanded} onExpandedChange={onExpandedChange} label="Open">{children}<div className="mt-5 border-t border-border-subtle pt-4"><Link href={`/kits/${kitId}/${route}`} className="inline-flex min-h-11 items-center gap-2 rounded-control px-3 text-sm font-semibold text-accent hover:bg-accent-subtle"><ExternalLink aria-hidden="true" className="size-4" />{route === "interview-prep" ? "Open Study mode" : "Open full workspace"}</Link></div></ExpandableArtifact>}{!available && state === "unavailable" && onRetry && <Button size="sm" variant="secondary" onClick={onRetry}>Retry</Button>}</div></Card>
  </article>;
}
