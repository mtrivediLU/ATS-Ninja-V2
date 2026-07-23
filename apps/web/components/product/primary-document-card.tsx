"use client";

import Link from "next/link";
import { ExternalLink, Eye, ShieldCheck } from "lucide-react";
import { CompactTemplateSelector } from "@/components/product/compact-template-selector";
import { ExpandableArtifact } from "@/components/product/expandable-artifact";
import { useKit } from "@/components/product/kit-context";
import { QuickPdfDownload } from "@/components/product/quick-pdf-download";
import { useTemplateSelection } from "@/components/product/template-selection";
import { TemplatePreview } from "@/components/product/templates/template-preview";
import { Banner, Button, Card, StatusLabel } from "@/components/ui/primitives";
import { artifactPresentationState, trustCounts } from "@/lib/artifact-presentation";
import type { CoverLetterArtifact, ResumeArtifact } from "@/lib/api-types";
import { safeWithheldReason } from "@/lib/product";
import { artifactStatePresentation } from "@/lib/status";

type PrimaryDocumentCardProps = {
  artifact: "resume" | "cover-letter";
  value: ResumeArtifact | CoverLetterArtifact | null;
  requested: boolean;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
};

export function PrimaryDocumentCard({ artifact, value, requested, expanded, onExpandedChange }: PrimaryDocumentCardProps) {
  const { kit, openEvidence, refresh } = useKit();
  const { templateFor } = useTemplateSelection();
  const title = artifact === "resume" ? "Resume" : "Cover letter";
  if (!requested) return <UnavailableCard title={title} state="not-requested" />;
  if (!value) return <UnavailableCard title={title} state="unavailable" onRetry={() => void refresh()} />;
  const state = artifactPresentationState(value.validation, value.text);
  const counts = trustCounts(value.claims, value.validation);
  const withheld = state === "withheld";
  const template = templateFor(artifact);
  const structuredResume = artifact === "resume" ? (value as ResumeArtifact).document : undefined;
  const structuredLetter = artifact === "cover-letter" ? (value as CoverLetterArtifact).document : undefined;
  return <article className={`k1-document-card ${expanded ? "md:col-span-2" : ""}`} id={artifact}>
    <Card className="h-full">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{title}</h2><p className="mt-1 text-xs text-ink-muted">{withheld ? "Not delivered because a validation gate withheld it." : `Generated version · ${template === "classic" ? "Classic ATS" : "Modern ATS"} template`}</p></div><StatusLabel presentation={artifactStatePresentation[state]} /></div>
      {withheld && <Banner tone="danger" className="mt-4" title="Withheld for safety.">{safeWithheldReason(value.validation.errors, value.validation.warnings) ?? "This document could not be delivered safely. Review its evidence record before creating a new Kit."}</Banner>}
      <div className="mt-4 flex flex-wrap gap-2 text-xs font-semibold"><span className="rounded-pill border border-positive-border bg-positive-bg px-2 py-1 text-positive">{counts.supported} supported</span><span className="rounded-pill border border-warning-border bg-warning-bg px-2 py-1 text-warning">{counts.adjusted} adjusted</span><span className="rounded-pill border border-danger-border bg-danger-bg px-2 py-1 text-danger">{counts.removed} removed</span></div>
      {!withheld && <div className="mt-4 flex flex-wrap items-center gap-2"><CompactTemplateSelector artifact={artifact} /><QuickPdfDownload size="sm" variant="primary" kitId={kit!.id} artifact={artifact} template={template} text={value.text} label={`Download ${title} PDF`} /><ExpandableArtifact artifact={artifact} expanded={expanded} onExpandedChange={onExpandedChange} label="Preview"><TemplatePreview artifact={artifact} text={value.text} latex={value.latex} company={artifact === "resume" ? "Target company unavailable" : structuredLetter?.recipient_company || "Target company unavailable"} role={structuredLetter?.target_role || "Application kit"} edited={false} resumeDocument={structuredResume} coverLetterDocument={structuredLetter} onReturnToArtifact={() => onExpandedChange(false)} kitId={kit!.id} /></ExpandableArtifact></div>}
      <div className="mt-4 flex flex-wrap gap-2"><Button size="sm" variant="ghost" onClick={() => openEvidence()}><ShieldCheck aria-hidden="true" className="size-4" />Trust</Button><Link href={`/kits/${kit!.id}/${artifact}`} className="inline-flex min-h-11 items-center gap-2 rounded-control px-3 text-sm font-semibold text-accent hover:bg-accent-subtle"><ExternalLink aria-hidden="true" className="size-4" />Open full workspace</Link>{withheld && <Button size="sm" variant="secondary" onClick={() => openEvidence()}><Eye aria-hidden="true" className="size-4" />Why withheld?</Button>}</div>
    </Card>
  </article>;
}

function UnavailableCard({ title, state, onRetry }: { title: string; state: "not-requested" | "unavailable"; onRetry?: () => void }) {
  return <article className="k1-document-card"><Card className="border-dashed shadow-none"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">{title}</h2><p className="mt-1 text-sm text-ink-muted">{state === "not-requested" ? "Not requested for this Kit." : "The selected artifact was not returned."}</p></div><StatusLabel presentation={artifactStatePresentation[state]} /></div>{onRetry && <Button size="sm" className="mt-4" onClick={onRetry}>Retry retrieval</Button>}</Card></article>;
}
