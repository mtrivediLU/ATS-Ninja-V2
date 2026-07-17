import type { DocumentPage } from "@/components/product/templates/document-model";

export function ResumeClassic({ page }: { page: Extract<DocumentPage, { kind: "structured" }> }) {
  return <div className="t1-resume t1-classic"><ResumePage page={page} /></div>;
}

export function ResumePage({ page }: { page: Extract<DocumentPage, { kind: "structured" }> }) {
  return <>
    {page.headerLines.length > 0 && <header className="t1-doc-header"><p className="t1-doc-name">{page.headerLines[0]}</p>{page.headerLines.slice(1).map((line, index) => <p key={`${line}-${index}`} className="t1-doc-contact">{line || "\u00a0"}</p>)}</header>}
    {page.sections.map((section, sectionIndex) => <section key={`${section.heading}-${sectionIndex}`} className="t1-section"><h2>{section.heading}</h2><div className={section.kind === "skills" ? "t1-section-body t1-skills" : "t1-section-body"}>{section.lines.map((line, lineIndex) => line === "" ? <div key={`${sectionIndex}-${lineIndex}`} className="t1-blank" aria-hidden="true" /> : <p key={`${sectionIndex}-${lineIndex}`} className={/^[\-•*]\s+/.test(line) ? "t1-source-bullet" : undefined}>{line}</p>)}</div></section>)}
  </>;
}
