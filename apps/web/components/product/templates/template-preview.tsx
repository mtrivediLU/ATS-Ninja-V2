"use client";

import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Download, FileCode2, FileText, LoaderCircle, MoreHorizontal, Printer, ShieldCheck, ZoomIn, ZoomOut } from "lucide-react";
import { ApiError, exportDocumentPdf } from "@/lib/api-client";
import { useFeedback } from "@/components/product/feedback";
import { Banner, Button, Card } from "@/components/ui/primitives";
import { downloadBlob, downloadText, templateFilename } from "@/lib/product";
import type { CoverLetterDocument, ResumeDocument } from "@/lib/api-types";
import { DocumentFlow } from "@/components/product/templates/document-flow";
import { PrintPreview } from "@/components/product/templates/print-preview";
import { TemplateCard } from "@/components/product/templates/template-card";
import { templateById, templatesForArtifact, type TemplateArtifact, type TemplateId } from "@/components/product/templates/template-definitions";

type TemplatePreviewProps = {
  artifact: TemplateArtifact;
  text: string;
  latex?: string;
  company: string;
  role: string;
  edited: boolean;
  resumeDocument?: ResumeDocument | null;
  coverLetterDocument?: CoverLetterDocument | null;
  onReturnToArtifact: () => void;
  kitId: string;
};

export function TemplatePreview({ artifact, text, latex = "", company, role, edited, resumeDocument, coverLetterDocument, onReturnToArtifact, kitId }: TemplatePreviewProps) {
  const { notify } = useFeedback();
  const templates = templatesForArtifact(artifact);
  const [selected, setSelected] = useState<TemplateId>("classic");
  const [zoom, setZoom] = useState(0.82);
  const [menuOpen, setMenuOpen] = useState(false);
  const [printOpen, setPrintOpen] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const filename = templateFilename(company, role, artifact, selected);
  const hasText = Boolean(text.trim());
  const source = edited ? "local edit — not revalidated" : "generated version";

  async function downloadPdf() {
    if (exportingPdf || !hasText) return;
    setExportingPdf(true);
    try {
      const { blob, filename: serverFilename } = await exportDocumentPdf({
        kit_id: kitId,
        artifact_type: artifact === "resume" ? "resume" : "cover_letter",
        template_id: selected,
        content_source: edited ? "local_edit" : "generated",
        ...(edited ? { local_edit_text: text } : {}),
      });
      downloadBlob(blob, serverFilename);
      notify(`PDF downloaded from the ${source}.`);
    } catch (error) {
      notify(error instanceof ApiError ? error.message : "PDF export failed. Try Print / Save as PDF instead.", "error");
    } finally {
      setExportingPdf(false);
    }
  }

  useEffect(() => {
    if (!menuOpen) return;
    const frame = window.requestAnimationFrame(() => document.querySelector<HTMLElement>("[data-template-menuitem]")?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setMenuOpen(false); window.requestAnimationFrame(() => menuTriggerRef.current?.focus()); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { window.cancelAnimationFrame(frame); document.removeEventListener("keydown", onKeyDown); };
  }, [menuOpen]);

  function chooseTemplate(id: TemplateId, focus = false) {
    setSelected(id);
    setMenuOpen(false);
    notify(`${artifact === "resume" ? "Resume" : "Cover letter"} switched to ${templateById(id).name}. Wording is unchanged.`);
    if (focus) window.requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-template="${id}"]`)?.focus());
  }

  function onTemplateKeys(event: ReactKeyboardEvent<HTMLDivElement>) {
    const direction = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!direction) return;
    event.preventDefault();
    const current = templates.findIndex((template) => template.id === selected);
    chooseTemplate(templates[(current + direction + templates.length) % templates.length].id, true);
  }

  function onMenuKeys(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!event.key.startsWith("Arrow")) return;
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("[role='menuitem']:not(:disabled)") ?? []);
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const direction = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
    event.preventDefault();
    items[(Math.max(0, current) + direction + items.length) % items.length]?.focus();
  }

  function download(kind: "txt" | "tex") {
    try {
      if (kind === "txt") downloadText(text, `${filename}.txt`);
      else downloadText(latex, `${filename}.tex`, "application/x-tex;charset=utf-8");
      notify(kind === "tex" && edited ? "Engine-provided LaTeX downloaded. It does not contain the local edit." : `${kind === "txt" ? "Plain text" : "LaTeX"} downloaded from the ${source}.`);
      setMenuOpen(false);
      window.requestAnimationFrame(() => menuTriggerRef.current?.focus());
    } catch {
      notify("Export failed — nothing was uploaded. Try Print / Save as PDF instead.", "error");
    }
  }

  const zoomStyle = { "--t1-preview-zoom": zoom } as CSSProperties;

  return <section className="t1-template-preview" aria-labelledby="template-heading">
    <header className="t1-template-header"><div><h2 id="template-heading">Choose a template</h2><p>Formatting only. Your wording, order, evidence, and validation never change.</p></div><span className={`t1-source-pill ${edited ? "t1-source-edited" : ""}`}><ShieldCheck aria-hidden="true" className="size-4" />{edited ? "Locally edited · not revalidated" : "Generated version"}</span><Button variant="ghost" onClick={onReturnToArtifact}>Return to artifact</Button></header>
    {edited && <Banner tone="warning" className="mt-4" title="Edited, not revalidated.">This preview and its exports use your local edit. Templates change formatting only; the edited text has not been checked against evidence.</Banner>}
    {!resumeDocument && !coverLetterDocument && <Banner tone="info" className="mt-4" title="Plain-text fallback.">This older Kit has no structured document fields. Its original text is preserved for display and export.</Banner>}
    {!hasText ? <Card className="mt-5 text-center"><h3 className="font-semibold">Template preview unavailable</h3><p className="mt-2 text-sm text-ink-secondary">This artifact has no usable text, so nothing is formatted or exported.</p></Card> : <div className="t1-template-layout mt-5">
      <aside className="t1-template-picker"><h3>Templates</h3><div role="radiogroup" aria-label={`Choose a ${artifact} template`} onKeyDown={onTemplateKeys} className="t1-template-cards">{templates.map((template) => <TemplateCard key={template.id} template={template} selected={template.id === selected} onSelect={() => chooseTemplate(template.id)} />)}</div></aside>
      <div className="t1-preview-column"><div className="t1-preview-bar"><span className="t1-page-count">Letter · 8.5 × 11 in</span><span className="flex-1" /><Button size="sm" variant="ghost" aria-label="Zoom out" onClick={() => setZoom((value) => Math.max(0.65, Number((value - 0.1).toFixed(2))))}><ZoomOut aria-hidden="true" className="size-4" />Zoom out</Button><Button size="sm" variant="ghost" aria-label="Zoom in" onClick={() => setZoom((value) => Math.min(1, Number((value + 0.1).toFixed(2))))}><ZoomIn aria-hidden="true" className="size-4" />Zoom in</Button><Button size="sm" variant="ghost" onClick={() => setZoom(0.82)}>Fit to width</Button><Button size="sm" variant="ghost" onClick={() => setZoom(0.72)}>Fit to page</Button><Button size="sm" variant="primary" disabled={!hasText || exportingPdf} aria-busy={exportingPdf} onClick={() => void downloadPdf()}>{exportingPdf ? <LoaderCircle aria-hidden="true" className="size-4 motion-safe:animate-spin" /> : <Download aria-hidden="true" className="size-4" />}{exportingPdf ? "Downloading…" : "Download PDF"}</Button><div className="t1-export-wrap"><Button ref={menuTriggerRef} size="sm" variant="secondary" disabled={!hasText} aria-haspopup="menu" aria-expanded={menuOpen} aria-label="More export options" onClick={() => setMenuOpen((open) => !open)}><MoreHorizontal aria-hidden="true" className="size-4" /></Button>{menuOpen && <div ref={menuRef} role="menu" aria-label="More export options" onKeyDown={onMenuKeys} className="t1-export-menu"><p>Saves the {source}. Nothing is uploaded.</p><button type="button" role="menuitem" data-template-menuitem onClick={() => { setMenuOpen(false); setPrintOpen(true); }}><Printer aria-hidden="true" className="size-4" /><span><strong>Print / Save as PDF</strong><small>Opens the browser print workflow.</small></span></button><button type="button" role="menuitem" data-template-menuitem onClick={() => download("txt")}><FileText aria-hidden="true" className="size-4" /><span><strong>Plain text (.txt)</strong><small>Exact current visible text.</small></span></button><button type="button" role="menuitem" data-template-menuitem disabled={!latex.trim()} onClick={() => download("tex")}><FileCode2 aria-hidden="true" className="size-4" /><span><strong>LaTeX (.tex)</strong><small>{latex.trim() ? edited ? "Engine source; local edits are not included." : "Engine-provided source, unchanged." : "Not available for this artifact."}</small></span></button></div>}</div></div>
        <div className="t1-page-viewport"><div className="t1-page-deck" style={zoomStyle}><DocumentFlow artifact={artifact} template={selected} text={text} resumeDocument={resumeDocument} coverLetterDocument={coverLetterDocument} /></div></div>
      </div>
    </div>}
    <PrintPreview open={printOpen} title={`Print preview — ${templateById(selected).name} ${artifact}`} filename={filename} onClose={() => setPrintOpen(false)} onPrint={() => notify(`Opening the print dialog for the ${source}. Choose Save as PDF for a Letter-size copy.`)}><DocumentFlow artifact={artifact} template={selected} text={text} resumeDocument={resumeDocument} coverLetterDocument={coverLetterDocument} printable /></PrintPreview>
  </section>;
}
