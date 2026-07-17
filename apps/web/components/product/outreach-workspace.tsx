"use client";

import { useState } from "react";
import { Copy, PencilLine, RotateCcw } from "lucide-react";
import { ArtifactToolbar } from "@/components/product/artifact-toolbar";
import { CompareView } from "@/components/product/compare-view";
import { useFeedback } from "@/components/product/feedback";
import { TrustSummary } from "@/components/product/trust-summary";
import { useArtifactView } from "@/components/product/use-artifact-view";
import { useLocalTextEditor, useUnsavedChangeProtection } from "@/components/product/use-local-text-editor";
import { Dialog } from "@/components/ui/dialog";
import { Banner, Button, Card, Field, Textarea } from "@/components/ui/primitives";
import type { LinkedInOutreachArtifact, OutreachContextRef, OutreachDraft } from "@/lib/api-types";
import { copyText, safeFilename } from "@/lib/product";

export function OutreachWorkspace({ artifact, company, role }: { artifact: LinkedInOutreachArtifact; company: string; role: string }) {
  const [view, setView] = useArtifactView();
  const exportText = outreachText(artifact);
  return <div>
    <ArtifactToolbar title="LinkedIn outreach" validation={artifact.validation} claims={artifact.claims} text={exportText} filename={safeFilename(company, role, "linkedin-outreach")} view={view} onViewChange={setView} />
    {view === "trust" ? <TrustSummary title="LinkedIn outreach" claims={artifact.claims} validation={artifact.validation} text={exportText} readinessLabel={artifact.drafts.length ? "Drafts ready — not sent" : "No drafts returned"} explanation="These are local, draft-only messages. ATS-Ninja has no LinkedIn connection and cannot send, discover recipients, or invent a relationship." onOpenContent={() => setView("content")} /> : <>
      <Banner tone="info" className="mt-5" title="Drafts only.">ATS-Ninja never sends messages, accesses LinkedIn, fetches public limits, or implies a relationship that was not supplied.</Banner>
      {artifact.strategy_summary && <Card className="mt-4 shadow-none"><h2 className="font-semibold">Outreach strategy</h2><p className="mt-2 text-sm text-ink-secondary">{artifact.strategy_summary}</p></Card>}
      {!artifact.relationship_validation.passed && <Banner tone="warning" className="mt-4" title="Relationship validation notes.">One or more drafts were repaired or withheld to avoid implying unsupported context. Review each draft’s validation notes before using it.</Banner>}
      {artifact.drafts.length ? <div className="mt-5 grid gap-4 xl:grid-cols-2">{artifact.drafts.map((draft) => <DraftCard key={draft.id} draft={draft} />)}</div> : <Card className="mt-5 text-center"><h2 className="text-lg font-semibold">No outreach drafts</h2><p className="mt-2 text-sm text-ink-secondary">The backend returned an empty outreach artifact.</p></Card>}
    </>}
  </div>;
}

function DraftCard({ draft }: { draft: OutreachDraft }) {
  const { notify } = useFeedback();
  const editor = useLocalTextEditor(draft.text);
  const [compare, setCompare] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  useUnsavedChangeProtection(editor.dirty);
  const text = editor.editing ? editor.draft : editor.applied;
  const count = text.length;
  const percent = draft.character_limit > 0 ? Math.min(100, Math.round((count / draft.character_limit) * 100)) : 0;
  const over = draft.character_limit > 0 && count > draft.character_limit;
  async function copy() { try { await copyText(text); notify(`${draft.audience.replaceAll("_", " ")} draft copied from the ${editor.edited || editor.editing ? "local edited" : "generated"} version.`); } catch { notify("Couldn't access the clipboard. Select and copy the draft manually.", "error"); } }
  function apply() { if (!editor.apply()) { notify("Can't apply an empty outreach draft.", "error"); return; } notify("Applied locally — this outreach draft is not revalidated.", "warning"); }

  return <Card className="flex flex-col shadow-none"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold capitalize">{draft.audience.replaceAll("_", " ")}</h2><p className="text-xs capitalize text-ink-muted">{draft.intent.replaceAll("_", " ")} · {draft.format.replaceAll("_", " ")}</p></div><span className="rounded-pill border border-neutral-border bg-neutral-bg px-2.5 py-1 text-xs font-semibold text-neutral">Draft — not sent</span></div>
    {editor.edited && !editor.editing && <Banner tone="warning" className="mt-4" title="Edited — not revalidated.">This local draft is not sent to the backend and disappears on reload.</Banner>}
    {editor.editing ? <div className="mt-4"><Banner tone="warning" title="Editing locally.">Manual edits are not revalidated, saved to a server, or sent through LinkedIn.</Banner><Field label="Local outreach draft" htmlFor={`draft-${draft.id}`} hint={editor.dirty ? "Unsaved local changes" : "No unsaved local changes"} className="mt-3"><Textarea id={`draft-${draft.id}`} value={editor.draft} onChange={(event) => editor.setDraft(event.target.value)} className="min-h-48" /></Field></div> : <p className="mt-4 flex-1 whitespace-pre-wrap rounded-md border border-border-subtle bg-surface-subtle p-4 text-sm leading-relaxed">{editor.applied}</p>}
    <div className={`mt-3 flex items-center gap-3 font-mono text-xs ${over ? "text-danger" : "text-ink-muted"}`}><span>{count}/{draft.character_limit || "—"}</span><span className="h-1.5 flex-1 overflow-hidden rounded-pill bg-[var(--readiness-track)]"><span className={`block h-full ${over ? "bg-danger" : "bg-accent"}`} style={{ width: `${percent}%` }} /></span><span>characters</span></div>
    <ContextList title="Candidate evidence used" items={draft.evidence.map((item) => ({ kind: "candidate_evidence", field: item.locator || item.source, excerpt: item.excerpt }))} tone="positive" /><ContextList title="Target job context used" items={draft.target_context} tone="accent" /><ContextList title="Recipient or relationship context used" items={draft.relationship_context} tone="edited" />
    {draft.call_to_action && <p className="mt-3 text-xs text-ink-muted">CTA: {draft.call_to_action}</p>}
    <div className="mt-4 flex flex-wrap gap-2"><Button size="sm" variant="primary" onClick={() => void copy()}><Copy aria-hidden="true" className="size-4" />Copy</Button>{editor.editing ? <><Button size="sm" onClick={apply}>Apply local edits</Button><Button size="sm" variant="ghost" onClick={() => editor.dirty ? setDiscardOpen(true) : editor.exit()}>Exit edit</Button></> : <><Button size="sm" variant="secondary" onClick={editor.beginEdit}><PencilLine aria-hidden="true" className="size-4" />Edit</Button>{editor.edited && <Button size="sm" variant="ghost" onClick={() => setCompare((open) => !open)}>Compare</Button>}{editor.edited && <Button size="sm" variant="ghost" onClick={() => setResetOpen(true)}><RotateCcw aria-hidden="true" className="size-4" />Reset</Button>}</>}</div>
    {compare && editor.edited && <CompareView generated={draft.text} edited={editor.applied} />}
    <Dialog open={discardOpen} onClose={() => setDiscardOpen(false)} title="Discard unsaved changes?" actions={<><Button variant="ghost" onClick={() => setDiscardOpen(false)}>Keep editing</Button><Button variant="destructive" onClick={() => { editor.discard(); setDiscardOpen(false); }}>Discard changes</Button></>}>These local changes have not been applied. Discarding restores the last local version.</Dialog>
    <Dialog open={resetOpen} onClose={() => setResetOpen(false)} title="Reset to generated draft?" actions={<><Button variant="ghost" onClick={() => setResetOpen(false)}>Cancel</Button><Button variant="destructive" onClick={() => { editor.reset(); setResetOpen(false); }}>Reset to generated</Button></>}>This replaces the local edited draft with the original generated draft.</Dialog>
  </Card>;
}

function ContextList({ title, items, tone }: { title: string; items: OutreachContextRef[]; tone: "positive" | "accent" | "edited" }) { if (!items.length) return null; const classes = tone === "positive" ? "border-positive-border bg-positive-bg text-positive" : tone === "edited" ? "border-edited-border bg-edited-bg text-edited" : "border-accent-border bg-accent-subtle text-positive"; return <div className="mt-3"><p className="text-xs font-semibold text-ink-muted">{title}</p><ul className="mt-1 flex flex-wrap gap-1.5 text-xs">{items.map((item, index) => <li key={`${item.kind}-${item.field}-${index}`} className={`rounded-sm border px-2 py-1 ${classes}`}><span className="font-mono">{item.field || item.kind}</span>{item.excerpt ? `: ${item.excerpt}` : ""}</li>)}</ul></div>; }
function outreachText(artifact: LinkedInOutreachArtifact): string { return ["LINKEDIN OUTREACH DRAFTS — NOT SENT", "", artifact.strategy_summary, ...artifact.drafts.flatMap((draft) => ["", `${draft.audience} · ${draft.intent} · ${draft.format}`, draft.text, `${draft.character_count}/${draft.character_limit} characters`, `CTA: ${draft.call_to_action}`])].join("\n"); }
