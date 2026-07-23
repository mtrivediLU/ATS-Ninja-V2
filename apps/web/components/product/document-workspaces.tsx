"use client";

import { useState } from "react";
import { Copy } from "lucide-react";
import { ArtifactToolbar } from "@/components/product/artifact-toolbar";
import { CompareView } from "@/components/product/compare-view";
import { GroundedText } from "@/components/product/grounded-text";
import { useFeedback } from "@/components/product/feedback";
import { TrustSummary } from "@/components/product/trust-summary";
import { TemplatePreview } from "@/components/product/templates/template-preview";
import { StickyActionBar } from "@/components/product/sticky-action-bar";
import { useArtifactView } from "@/components/product/use-artifact-view";
import { useLocalTextEditor, useUnsavedChangeProtection } from "@/components/product/use-local-text-editor";
import { Banner, Button, Card, Field, Textarea } from "@/components/ui/primitives";
import type { AnswerArtifact, CoverLetterArtifact, ResumeArtifact } from "@/lib/api-types";
import { formatAnswersText } from "@/lib/artifact-content";
import { copyText, safeFilename } from "@/lib/product";

export function DocumentWorkspace({ kind, artifact, company, role, kitId }: { kind: "resume" | "cover-letter"; artifact: ResumeArtifact | CoverLetterArtifact; company: string; role: string; kitId: string }) {
  const { notify } = useFeedback();
  const [view, setView] = useArtifactView();
  const editor = useLocalTextEditor(artifact.text);
  const [compare, setCompare] = useState(false);
  useUnsavedChangeProtection(editor.dirty);
  const title = kind === "resume" ? "Tailored resume" : "Cover letter";
  const filename = safeFilename(company, role, kind);
  const visibleText = editor.editing ? editor.draft : editor.applied;
  // A local edit is the active source and must never be overwritten by the
  // generated structured view. It follows the conservative text fallback.
  const resumeDocument = !editor.editing && !editor.edited && kind === "resume" ? (artifact as ResumeArtifact).document : undefined;
  const coverLetterDocument = !editor.editing && !editor.edited && kind === "cover-letter" ? (artifact as CoverLetterArtifact).document : undefined;

  function apply() {
    if (!editor.apply()) { notify("Can't apply empty local content. Reset to generated content or enter text first.", "error"); return; }
    notify("Applied locally — manual edits have not been revalidated.", "warning");
  }

  return <div>
    <ArtifactToolbar title={title} validation={artifact.validation} claims={artifact.claims} text={visibleText} latex={artifact.latex} filename={filename} view={view} onViewChange={setView} editing={editor.editing} editable dirty={editor.dirty} edited={editor.edited} templates onBeginEdit={() => { setView("content"); editor.beginEdit(); }} onApplyLocalEdits={apply} onExitEdit={() => editor.exit()} onDiscardChanges={editor.discard} onReset={editor.reset} onCompare={() => setCompare((open) => !open)} />
    {view === "trust" ? <TrustSummary title={title} claims={artifact.claims} validation={artifact.validation} text={editor.applied} manuallyEdited={editor.edited} onOpenContent={() => setView("content")} /> : view === "template" ? <TemplatePreview artifact={kind} text={visibleText} latex={artifact.latex} company={company} role={role} edited={editor.editing || editor.edited} resumeDocument={resumeDocument} coverLetterDocument={coverLetterDocument} onReturnToArtifact={() => setView("content")} kitId={kitId} /> : <div className="mx-auto mt-5 max-w-[820px]">
      {artifact.validation.repaired_claims > 0 && <Banner tone="warning" title={`${artifact.validation.repaired_claims} claim${artifact.validation.repaired_claims === 1 ? " was" : "s were"} repaired.`}>The engine removed unsupported content. Open Evidence to review the persisted reason; no removed wording is restored here.</Banner>}
      {editor.editing ? <><Editor title={title} value={editor.draft} onChange={editor.setDraft} dirty={editor.dirty} /><StickyActionBar><Button className="flex-1" onClick={apply}>Apply local edits</Button><Button className="flex-1" variant="secondary" onClick={() => { if (!editor.dirty || window.confirm("Discard unsaved changes and exit edit mode?")) editor.discard(); }}>Exit edit mode</Button></StickyActionBar></> : <>
        {editor.edited && <Banner tone="warning" className="mt-4" title="Edited since generation.">This local version is not revalidated and will be lost on reload. Copy and download are explicitly labelled as local edits.</Banner>}
        <article className="mt-5 rounded-lg border border-border bg-surface p-5 shadow-sm sm:p-8"><GroundedText text={editor.applied} claims={editor.edited ? [] : artifact.claims} className="text-base" /></article>
        {compare && editor.edited && <CompareView generated={artifact.text} edited={editor.applied} />}
      </>}
    </div>}
  </div>;
}

export function AnswersWorkspace({ artifact, company, role }: { artifact: AnswerArtifact; company: string; role: string }) {
  const { notify } = useFeedback();
  const [view, setView] = useArtifactView();
  const generated = formatAnswersText(artifact);
  const editor = useLocalTextEditor(generated);
  const [compare, setCompare] = useState(false);
  useUnsavedChangeProtection(editor.dirty);
  const filename = safeFilename(company, role, "application-answers");
  const visibleText = editor.editing ? editor.draft : editor.applied;
  const malformed = editor.editing && artifact.items.length > 0 && artifact.items.some((item) => !editor.draft.includes(item.question));

  async function copyAnswer(text: string, index: number) {
    try { await copyText(text); notify(`Answer ${index + 1} copied from the generated version.`); } catch { notify("Couldn't access the clipboard. Select and copy the answer manually.", "error"); }
  }
  function apply() {
    if (!editor.apply()) { notify("Can't apply empty local content. Reset to generated answers or enter text first.", "error"); return; }
    notify("Applied locally — answers have not been revalidated.", "warning");
  }

  return <div>
    <ArtifactToolbar title="Application answers" validation={artifact.validation} claims={artifact.claims} text={visibleText} filename={filename} view={view} onViewChange={setView} editing={editor.editing} editable dirty={editor.dirty} edited={editor.edited} onBeginEdit={() => { setView("content"); editor.beginEdit(); }} onApplyLocalEdits={apply} onExitEdit={() => editor.exit()} onDiscardChanges={editor.discard} onReset={editor.reset} onCompare={() => setCompare((open) => !open)} />
    {view === "trust" ? <TrustSummary title="Application answers" claims={artifact.claims} validation={artifact.validation} text={editor.applied} manuallyEdited={editor.edited} onOpenContent={() => setView("content")} /> : <div className="mx-auto mt-5 max-w-[860px]">
      {(artifact.placeholders.length > 0 || artifact.validation.rejected_claims > 0) && <Banner tone="warning" title="Some answers could not be completed safely.">Missing evidence remains visible as a placeholder or withheld state rather than being fabricated.</Banner>}
      {editor.editing ? <><Editor title="Application answers" value={editor.draft} onChange={editor.setDraft} dirty={editor.dirty} />{malformed && <Banner tone="warning" className="mt-4" title="Edited answer structure changed.">Question headings are missing from this local text. It can still be copied or downloaded as local content, but it will be shown as freeform text until you reset to generated answers.</Banner>}<StickyActionBar><Button className="flex-1" onClick={apply}>Apply local edits</Button><Button className="flex-1" variant="secondary" onClick={() => { if (!editor.dirty || window.confirm("Discard unsaved changes and exit edit mode?")) editor.discard(); }}>Exit edit mode</Button></StickyActionBar></> : editor.edited ? <><Banner tone="warning" title="Edited since generation.">This local answer set is not revalidated and will be lost on reload.</Banner><pre className="mt-5 whitespace-pre-wrap rounded-lg border border-border bg-surface p-5 font-sans text-base leading-relaxed shadow-sm">{editor.applied}</pre>{compare && <CompareView generated={generated} edited={editor.applied} />}</> : !artifact.items.length ? <Card className="mt-5 text-center"><h2 className="text-lg font-semibold">No application questions</h2><p className="mt-2 text-sm text-ink-secondary">The backend returned a valid empty answers artifact.</p></Card> : <div className="mt-5 space-y-4">{artifact.items.map((item, index) => <Card key={`${item.question}-${index}`} className="shadow-none"><div className="flex flex-wrap items-start justify-between gap-3"><h2 className="max-w-[780px] font-semibold">{item.question}</h2><Button size="sm" onClick={() => void copyAnswer(item.answer, index)}><Copy aria-hidden="true" className="size-4" />Copy answer</Button></div><GroundedText text={item.answer} claims={artifact.claims} className="mt-4 text-base" /></Card>)}</div>}
      {artifact.placeholders.length > 0 && <Card className="mt-4 border-warning-border bg-warning-bg shadow-none"><h2 className="font-semibold text-warning">Withheld or incomplete answer guidance</h2><ul className="mt-3 space-y-2 text-sm text-ink-secondary">{artifact.placeholders.map((placeholder) => <li key={placeholder}>{placeholder}</li>)}</ul></Card>}
    </div>}
  </div>;
}

function Editor({ title, value, onChange, dirty }: { title: string; value: string; onChange: (value: string) => void; dirty: boolean }) {
  return <div className="mt-4"><Banner tone="warning" title="Editing locally.">Manual edits are not revalidated against evidence, are never sent to the API, and disappear on reload.</Banner><Field label={`${title} local text`} htmlFor={`${title.toLowerCase().replaceAll(" ", "-")}-editor`} hint={dirty ? "Unsaved local changes" : "No unsaved local changes"} className="mt-4"><Textarea id={`${title.toLowerCase().replaceAll(" ", "-")}-editor`} value={value} onChange={(event) => onChange(event.target.value)} className="min-h-[520px] font-mono text-sm" /></Field></div>;
}
