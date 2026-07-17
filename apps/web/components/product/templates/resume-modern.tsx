import type { DocumentPage } from "@/components/product/templates/document-model";
import { ResumePage } from "@/components/product/templates/resume-classic";

export function ResumeModern({ page }: { page: Extract<DocumentPage, { kind: "structured" }> }) {
  return <div className="t1-resume t1-modern"><ResumePage page={page} /></div>;
}
