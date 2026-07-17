import { Check, ShieldCheck } from "lucide-react";
import type { TemplateDefinition } from "@/components/product/templates/template-definitions";

export function TemplateCard({ template, selected, onSelect }: { template: TemplateDefinition; selected: boolean; onSelect: () => void }) {
  return <button type="button" role="radio" data-template={template.id} aria-checked={selected} tabIndex={selected ? 0 : -1} onClick={onSelect} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(); } }} className={`t1-template-card ${selected ? "t1-template-card-selected" : ""}`}>
    <span aria-hidden="true" className={`t1-template-thumbnail t1-template-thumbnail-${template.id}`}><i /><i /><i /><i /><i /></span>
    <span className="t1-template-card-title">{template.name}{selected && <span className="t1-template-selected"><Check aria-hidden="true" className="size-3.5" />Selected</span>}</span>
    <span className="t1-template-card-description">{template.description}</span>
    <span className="t1-template-ats"><ShieldCheck aria-hidden="true" className="size-3.5" />ATS-friendly</span>
  </button>;
}
