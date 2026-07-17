"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { ChevronLeft, ChevronRight, Download, FileCode2, FileText, Printer, ShieldCheck, ZoomIn, ZoomOut } from "lucide-react";
import { useFeedback } from "@/components/product/feedback";
import { Banner, Button, Card } from "@/components/ui/primitives";
import { downloadText, templateFilename } from "@/lib/product";
import { buildDocumentModel, paginateDocument } from "@/components/product/templates/document-model";
import { DocumentPage } from "@/components/product/templates/document-page";
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
  onReturnToArtifact: () => void;
};

export function TemplatePreview({ artifact, text, latex = "", company, role, edited, onReturnToArtifact }: TemplatePreviewProps) {
  const { notify } = useFeedback();
  const templates = templatesForArtifact(artifact);
  const [selected, setSelected] = useState<TemplateId>("classic");
  const [zoom, setZoom] = useState(0.82);
  const [activePage, setActivePage] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [printOpen, setPrintOpen] = useState(false);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Array<HTMLElement | null>>([]);
  const model = useMemo(() => buildDocumentModel(artifact, text), [artifact, text]);
  const definition = templateById(selected);
  const pages = useMemo(() => paginateDocument(model, definition.density), [definition.density, model]);
  const filename = templateFilename(company, role, artifact, selected);
  const hasText = Boolean(text.trim());
  const source = edited ? "local edit — not revalidated" : "generated version";

  useEffect(() => { setActivePage(0); }, [selected, text]);
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

  function goToPage(index: number) {
    const next = Math.max(0, Math.min(index, pages.length - 1));
    setActivePage(next);
    pageRefs.current[next]?.scrollIntoView({ behavior: "smooth", block: "start" });
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

  const documentPages = pages.map((page, index) => <DocumentPage key={`${selected}-${index}-${model.sourceText.length}`} artifact={artifact} template={selected} page={page} model={model} pageNumber={index + 1} pageCount={pages.length} edited={edited} />);
  const zoomStyle = { "--t1-preview-zoom": zoom } as CSSProperties;

  return <section className="t1-template-preview" aria-labelledby="template-heading">
    <header className="t1-template-header"><div><h2 id="template-heading">Choose a template</h2><p>Formatting only. Your wording, order, evidence, and validation never change.</p></div><span className={`t1-source-pill ${edited ? "t1-source-edited" : ""}`}><ShieldCheck aria-hidden="true" className="size-4" />{edited ? "Locally edited · not revalidated" : "Generated version"}</span><Button variant="ghost" onClick={onReturnToArtifact}>Return to artifact</Button></header>
    {edited && <Banner tone="warning" className="mt-4" title="Edited, not revalidated.">This preview and its exports use your local edit. Templates change formatting only; the edited text has not been checked against evidence.</Banner>}
    {model.tier === 4 && <Banner tone="info" className="mt-4" title="Plain-text fallback.">{model.reason}</Banner>}
    {!hasText ? <Card className="mt-5 text-center"><h3 className="font-semibold">Template preview unavailable</h3><p className="mt-2 text-sm text-ink-secondary">This artifact has no usable text, so nothing is formatted or exported.</p></Card> : <div className="t1-template-layout mt-5">
      <aside className="t1-template-picker"><h3>Templates</h3><div role="radiogroup" aria-label={`Choose a ${artifact} template`} onKeyDown={onTemplateKeys} className="t1-template-cards">{templates.map((template) => <TemplateCard key={template.id} template={template} selected={template.id === selected} onSelect={() => chooseTemplate(template.id)} />)}</div></aside>
      <div className="t1-preview-column"><div className="t1-preview-bar"><span className="t1-page-count">Letter · 8.5 × 11 in · Page {activePage + 1} of {pages.length}</span><span className="flex-1" /><Button size="sm" variant="ghost" aria-label="Zoom out" onClick={() => setZoom((value) => Math.max(0.65, Number((value - 0.1).toFixed(2))))}><ZoomOut aria-hidden="true" className="size-4" />Zoom out</Button><Button size="sm" variant="ghost" aria-label="Zoom in" onClick={() => setZoom((value) => Math.min(1, Number((value + 0.1).toFixed(2))))}><ZoomIn aria-hidden="true" className="size-4" />Zoom in</Button><Button size="sm" variant="ghost" onClick={() => setZoom(0.82)}>Fit to width</Button><Button size="sm" variant="ghost" onClick={() => setZoom(0.72)}>Fit to page</Button><Button size="sm" variant="secondary" disabled={!hasText} onClick={() => setPrintOpen(true)}><Printer aria-hidden="true" className="size-4" />Print preview</Button><div className="t1-export-wrap"><Button ref={menuTriggerRef} size="sm" variant="primary" disabled={!hasText} aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}><Download aria-hidden="true" className="size-4" />Download / Print</Button>{menuOpen && <div ref={menuRef} role="menu" aria-label="Download or print" onKeyDown={onMenuKeys} className="t1-export-menu"><p>Saves the {source}. Nothing is uploaded.</p><button type="button" role="menuitem" data-template-menuitem onClick={() => { setMenuOpen(false); setPrintOpen(true); }}><Printer aria-hidden="true" className="size-4" /><span><strong>Print / Save as PDF</strong><small>Opens the browser print workflow.</small></span></button><button type="button" role="menuitem" data-template-menuitem onClick={() => download("txt")}><FileText aria-hidden="true" className="size-4" /><span><strong>Plain text (.txt)</strong><small>Exact current visible text.</small></span></button><button type="button" role="menuitem" data-template-menuitem disabled={!latex.trim()} onClick={() => download("tex")}><FileCode2 aria-hidden="true" className="size-4" /><span><strong>LaTeX (.tex)</strong><small>{latex.trim() ? edited ? "Engine source; local edits are not included." : "Engine-provided source, unchanged." : "Not available for this artifact."}</small></span></button><code>{filename}.pdf</code></div>}</div></div>
        <div className="t1-page-viewport"><div className="t1-page-deck" style={zoomStyle}>{documentPages.map((page, index) => <div key={index} ref={(element) => { pageRefs.current[index] = element; }} className={`t1-page-slot ${index === activePage ? "t1-page-active" : ""}`}>{page}<span>Page {index + 1} of {pages.length}</span></div>)}</div></div>
        {pages.length > 1 && <nav className="t1-page-nav" aria-label="Document pages"><Button size="sm" variant="ghost" disabled={activePage === 0} onClick={() => goToPage(activePage - 1)}><ChevronLeft aria-hidden="true" className="size-4" />Previous page</Button><span>Page {activePage + 1} of {pages.length}</span><Button size="sm" variant="ghost" disabled={activePage === pages.length - 1} onClick={() => goToPage(activePage + 1)}>Next page<ChevronRight aria-hidden="true" className="size-4" /></Button></nav>}
      </div>
    </div>}
    <PrintPreview open={printOpen} title={`Print preview — ${definition.name} ${artifact}`} filename={filename} onClose={() => setPrintOpen(false)} onPrint={() => notify(`Opening the print dialog for the ${source}. Choose Save as PDF for a Letter-size copy.`)}><div className="t1-print-pages">{documentPages}</div></PrintPreview>
  </section>;
}
