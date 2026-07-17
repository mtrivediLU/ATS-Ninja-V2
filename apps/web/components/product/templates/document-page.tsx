import type { DocumentPage as Page, DocumentModel } from "@/components/product/templates/document-model";
import type { TemplateArtifact, TemplateId } from "@/components/product/templates/template-definitions";
import { DocumentFallback } from "@/components/product/templates/document-fallback";
import { ResumeClassic } from "@/components/product/templates/resume-classic";
import { ResumeModern } from "@/components/product/templates/resume-modern";
import { CoverClassic } from "@/components/product/templates/cover-classic";
import { CoverModern } from "@/components/product/templates/cover-modern";

export function DocumentPage({ artifact, template, page, model, pageNumber, pageCount, edited }: { artifact: TemplateArtifact; template: TemplateId; page: Page; model: DocumentModel; pageNumber: number; pageCount: number; edited: boolean }) {
  const fallback = page.kind === "verbatim";
  return <article className={`t1-page t1-page-${template}`} aria-label={`${template === "classic" ? "Classic ATS" : "Modern ATS"} ${artifact}, page ${pageNumber} of ${pageCount}`}>
    {edited && <span className="t1-edited-stamp">Edited · not revalidated</span>}
    {fallback ? artifact === "cover-letter" ? template === "classic" ? <CoverClassic text={page.text} reason={model.tier === 4 ? model.reason : "Exact wording is preserved verbatim."} /> : <CoverModern text={page.text} reason={model.tier === 4 ? model.reason : "Exact wording is preserved verbatim."} /> : <div className={template === "classic" ? "t1-classic" : "t1-modern"}><DocumentFallback text={page.text} reason={model.tier === 4 ? model.reason : "Exact wording is preserved verbatim."} /></div> : artifact === "resume" ? template === "classic" ? <ResumeClassic page={page} /> : <ResumeModern page={page} /> : template === "classic" ? <CoverClassic text={model.sourceText} reason={model.tier === 4 ? model.reason : "Exact wording is preserved verbatim."} /> : <CoverModern text={model.sourceText} reason={model.tier === 4 ? model.reason : "Exact wording is preserved verbatim."} />}
  </article>;
}
