"use client";

import { Copy, RefreshCw, ShieldCheck } from "lucide-react";
import { ArtifactToolbar } from "@/components/product/artifact-toolbar";
import { useFeedback } from "@/components/product/feedback";
import { Banner, Button, Card, Tooltip } from "@/components/ui/primitives";
import type { LinkedInOutreachArtifact, OutreachContextRef, OutreachDraft } from "@/lib/api-types";
import { copyText, safeFilename } from "@/lib/product";

export function OutreachWorkspace({ artifact, company, role }: { artifact: LinkedInOutreachArtifact; company: string; role: string }) {
  const exportText = outreachText(artifact);
  return <div>
    <ArtifactToolbar title="LinkedIn outreach" validation={artifact.validation} claims={artifact.claims} text={exportText} filename={safeFilename(company, role, "linkedin-outreach")} />
    <Banner tone="info" title="Drafts only.">ATS-Ninja never sends messages, accesses LinkedIn, fetches public limits, or implies a relationship that was not supplied.</Banner>
    {artifact.strategy_summary && <Card className="mt-4 shadow-none"><h2 className="font-semibold">Outreach strategy</h2><p className="mt-2 text-sm text-ink-secondary">{artifact.strategy_summary}</p></Card>}
    {!artifact.relationship_validation.passed && <Banner tone="warning" className="mt-4" title="Relationship validation required.">One or more drafts were repaired or withheld to avoid implying unsupported context.</Banner>}
    {artifact.drafts.length ? <div className="mt-5 grid gap-4 xl:grid-cols-2">{artifact.drafts.map((draft) => <DraftCard key={draft.id} draft={draft} />)}</div> : <Card className="mt-5 text-center"><h2 className="text-lg font-semibold">No outreach drafts</h2><p className="mt-2 text-sm text-ink-secondary">The backend returned an empty outreach artifact.</p></Card>}
  </div>;
}

function DraftCard({ draft }: { draft: OutreachDraft }) {
  const { notify } = useFeedback();
  const percent = draft.character_limit > 0 ? Math.min(100, Math.round((draft.character_count / draft.character_limit) * 100)) : 0;
  const over = draft.character_limit > 0 && draft.character_count > draft.character_limit;
  async function copy() { try { await copyText(draft.text); notify(`${draft.audience.replaceAll("_", " ")} draft copied.`); } catch { notify("Copy failed. Your browser may have blocked clipboard access.", "error"); } }
  return <Card className="flex flex-col shadow-none"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold capitalize">{draft.audience.replaceAll("_", " ")}</h2><p className="text-xs capitalize text-ink-muted">{draft.intent.replaceAll("_", " ")} · {draft.format.replaceAll("_", " ")}</p></div><span className="rounded-pill border border-neutral-border bg-neutral-bg px-2.5 py-1 text-xs font-semibold text-neutral">Draft</span></div><p className="mt-4 flex-1 whitespace-pre-wrap rounded-md border border-border-subtle bg-surface-subtle p-4 text-sm leading-relaxed">{draft.text}</p><div className={`mt-3 flex items-center gap-3 font-mono text-xs ${over ? "text-danger" : "text-ink-muted"}`}><span>{draft.character_count}/{draft.character_limit || "—"}</span><span className="h-1.5 flex-1 overflow-hidden rounded-pill bg-surface-raised"><span className={`block h-full ${over ? "bg-danger" : "bg-accent"}`} style={{ width: `${percent}%` }} /></span><span>characters</span></div>{draft.personalization_fields.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{draft.personalization_fields.map((field) => <span key={field} className="rounded-sm border border-accent-border bg-accent-subtle px-2 py-1 font-mono text-xs text-positive">{field}</span>)}</div>}<ContextList title="Target context" items={draft.target_context} /><ContextList title="Relationship context" items={draft.relationship_context} />{draft.evidence.length > 0 && <p className="mt-3 inline-flex items-center gap-2 text-xs text-ink-muted"><ShieldCheck aria-hidden="true" className="size-4 text-positive" />{draft.evidence.length} bounded candidate evidence reference{draft.evidence.length === 1 ? "" : "s"}</p>}{draft.call_to_action && <p className="mt-2 text-xs text-ink-muted">CTA: {draft.call_to_action}</p>}<div className="mt-4 flex flex-wrap gap-2"><Button size="sm" onClick={() => void copy()}><Copy aria-hidden="true" className="size-4" />Copy</Button><Tooltip label="No per-draft regeneration endpoint exists"><Button size="sm" disabled aria-disabled="true"><RefreshCw aria-hidden="true" className="size-4" />Regenerate</Button></Tooltip></div></Card>;
}

function ContextList({ title, items }: { title: string; items: OutreachContextRef[] }) { if (!items.length) return null; return <div className="mt-3"><p className="text-xs font-semibold text-ink-muted">{title}</p><ul className="mt-1 space-y-1 text-xs text-ink-secondary">{items.map((item, index) => <li key={`${item.kind}-${item.field}-${index}`}><span className="font-mono">{item.field}</span>: {item.excerpt}</li>)}</ul></div>; }
function outreachText(artifact: LinkedInOutreachArtifact): string { return ["LINKEDIN OUTREACH DRAFTS — NOT SENT", "", artifact.strategy_summary, ...artifact.drafts.flatMap((draft) => ["", `${draft.audience} · ${draft.intent} · ${draft.format}`, draft.text, `${draft.character_count}/${draft.character_limit} characters`, `CTA: ${draft.call_to_action}`])].join("\n"); }
