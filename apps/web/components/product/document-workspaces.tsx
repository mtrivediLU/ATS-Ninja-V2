"use client";

import { useEffect, useState } from "react";
import { Copy, RotateCcw } from "lucide-react";
import { ArtifactToolbar } from "@/components/product/artifact-toolbar";
import { GroundedText } from "@/components/product/grounded-text";
import { useFeedback } from "@/components/product/feedback";
import { Banner, Button, Card, Field, Textarea } from "@/components/ui/primitives";
import type { AnswerArtifact, CoverLetterArtifact, ResumeArtifact } from "@/lib/api-types";
import { copyText, downloadText, safeFilename } from "@/lib/product";

export function DocumentWorkspace({ kind, artifact, company, role }: { kind: "resume" | "cover-letter"; artifact: ResumeArtifact | CoverLetterArtifact; company: string; role: string }) {
  const [editing, setEditing] = useState(false);
  const [localText, setLocalText] = useState(artifact.text);
  useEffect(() => setLocalText(artifact.text), [artifact.text]);
  const dirty = localText !== artifact.text;
  const title = kind === "resume" ? "Tailored resume" : "Cover letter";
  const filename = safeFilename(company, role, kind);
  return <div>
    <ArtifactToolbar title={title} validation={artifact.validation} claims={artifact.claims} text={localText} latex={artifact.latex} filename={filename} editing={editing} editable dirty={dirty} onEditingChange={setEditing} onReset={() => setLocalText(artifact.text)} />
    {artifact.validation.repaired_claims > 0 && <Banner tone="warning" title={`${artifact.validation.repaired_claims} claim${artifact.validation.repaired_claims === 1 ? " was" : "s were"} repaired.`}>Unsupported content was removed or adjusted by the grounding gate. Open Evidence for the server-provided disposition.</Banner>}
    {editing ? <div className="mx-auto mt-5 max-w-[820px]"><Banner tone="warning" title="Local unsaved edit.">Changes exist only in this tab, have not been revalidated, and are never sent back to the API. Copy and download use the edited text.</Banner><Field label={`${title} text`} htmlFor={`${kind}-editor`} hint={dirty ? "Edited since generation · not revalidated" : "Generated text unchanged"} className="mt-4"><Textarea id={`${kind}-editor`} value={localText} onChange={(event) => setLocalText(event.target.value)} className="min-h-[520px] font-mono text-sm" /></Field></div> : <article className="mx-auto mt-5 max-w-[820px] rounded-lg border border-border bg-surface p-5 shadow-sm sm:p-8"><GroundedText text={localText} claims={artifact.claims} className="text-base" /></article>}
  </div>;
}

export function AnswersWorkspace({ artifact, company, role }: { artifact: AnswerArtifact; company: string; role: string }) {
  const { notify } = useFeedback();
  const [editing, setEditing] = useState(false);
  const [answers, setAnswers] = useState(() => artifact.items.map((item) => item.answer));
  useEffect(() => setAnswers(artifact.items.map((item) => item.answer)), [artifact.items]);
  const generatedText = artifact.items.map((item, index) => `${item.question}\n${answers[index] ?? item.answer}`).join("\n\n");
  const originalText = artifact.items.map((item) => `${item.question}\n${item.answer}`).join("\n\n") || artifact.text;
  const dirty = generatedText !== originalText;
  const filename = safeFilename(company, role, "application-answers");

  async function copyAnswer(text: string, index: number) {
    try { await copyText(text); notify(`Answer ${index + 1} copied.`); } catch { notify("Copy failed. Your browser may have blocked clipboard access.", "error"); }
  }

  return <div>
    <ArtifactToolbar title="Application answers" validation={artifact.validation} claims={artifact.claims} text={generatedText || artifact.text} filename={filename} editing={editing} editable dirty={dirty} onEditingChange={setEditing} onReset={() => setAnswers(artifact.items.map((item) => item.answer))} />
    {dirty && <Banner tone="warning" title="Edited since generation.">Local changes have not been grounded or revalidated and disappear when this page is reloaded.</Banner>}
    {(artifact.placeholders.length > 0 || artifact.validation.rejected_claims > 0) && <Banner tone="warning" title="Some answers could not be completed safely.">Missing evidence remains visible as a placeholder or rejected claim rather than being fabricated.</Banner>}
    {!artifact.items.length ? <Card className="mt-5 text-center"><h2 className="text-lg font-semibold">No application questions</h2><p className="mt-2 text-sm text-ink-secondary">The backend returned a valid empty answers artifact.</p></Card> : <div className="mt-5 space-y-4">{artifact.items.map((item, index) => <Card key={`${item.question}-${index}`} className="shadow-none"><div className="flex flex-wrap items-start justify-between gap-3"><h2 className="max-w-[780px] font-semibold">{item.question}</h2><Button size="sm" onClick={() => void copyAnswer(answers[index] ?? item.answer, index)}><Copy aria-hidden="true" className="size-4" />Copy answer</Button></div>{editing ? <Field label={`Local answer ${index + 1}`} htmlFor={`answer-${index}`} hint="Not revalidated" className="mt-4"><Textarea id={`answer-${index}`} value={answers[index] ?? ""} onChange={(event) => setAnswers((current) => current.map((answer, answerIndex) => answerIndex === index ? event.target.value : answer))} className="min-h-36" /></Field> : <GroundedText text={answers[index] ?? item.answer} claims={artifact.claims} className="mt-4 text-base" />}</Card>)}</div>}
    {artifact.placeholders.length > 0 && <Card className="mt-4 border-warning-border bg-warning-bg shadow-none"><h2 className="font-semibold text-warning">Withheld or incomplete answer guidance</h2><ul className="mt-3 space-y-2 text-sm text-ink-secondary">{artifact.placeholders.map((placeholder) => <li key={placeholder}>{placeholder}</li>)}</ul></Card>}
    {dirty && <div className="mt-4 flex flex-wrap gap-3"><Button variant="ghost" onClick={() => setAnswers(artifact.items.map((item) => item.answer))}><RotateCcw aria-hidden="true" className="size-4" />Reset generated answers</Button><Button onClick={() => { try { downloadText(generatedText, `${filename}.txt`); notify("Edited answers downloaded."); } catch { notify("Download failed.", "error"); } }}>Download local edit</Button></div>}
  </div>;
}
