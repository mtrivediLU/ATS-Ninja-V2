"use client";

import { LoaderCircle, Download } from "lucide-react";
import { useState } from "react";
import { useFeedback } from "@/components/product/feedback";
import { Button, type ButtonProps } from "@/components/ui/primitives";
import { ApiError, exportDocumentDocx, exportDocumentPdf, type DocumentExportPayload } from "@/lib/api-client";
import { downloadBlob } from "@/lib/product";
import type { TemplateId } from "@/components/product/templates/template-definitions";

export type DocumentFormat = "pdf" | "word";

type QuickPdfDownloadProps = Omit<ButtonProps, "onClick" | "children"> & {
  kitId: string;
  artifact: "resume" | "cover-letter";
  template: TemplateId;
  text: string;
  edited?: boolean;
  label?: string;
  format?: DocumentFormat;
};

/** The single browser control for the existing server-generated PDF/Word export. */
export function QuickPdfDownload({
  kitId,
  artifact,
  template,
  text,
  edited = false,
  label,
  format = "pdf",
  disabled,
  ...buttonProps
}: QuickPdfDownloadProps) {
  const { notify } = useFeedback();
  const [exporting, setExporting] = useState(false);
  const source = edited ? "local edit — not revalidated" : "generated version";
  const formatLabel = format === "word" ? "Word" : "PDF";
  const resolvedLabel = label ?? `Download ${formatLabel}`;

  async function download() {
    if (exporting || !text.trim()) return;
    setExporting(true);
    try {
      const payload: DocumentExportPayload = {
        kit_id: kitId,
        artifact_type: artifact === "resume" ? "resume" : "cover_letter",
        template_id: template,
        content_source: edited ? "local_edit" : "generated",
        ...(edited ? { local_edit_text: text } : {}),
      };
      const { blob, filename } = format === "word" ? await exportDocumentDocx(payload) : await exportDocumentPdf(payload);
      downloadBlob(blob, filename);
      notify(`${artifact === "resume" ? "Resume" : "Cover letter"} ${formatLabel} downloaded from the ${source} using the ${template} template.`);
    } catch (error) {
      notify(
        error instanceof ApiError ? error.message : `${formatLabel} export failed. Try Print / Save as PDF instead.`,
        "error",
      );
    } finally {
      setExporting(false);
    }
  }

  return <Button {...buttonProps} disabled={disabled || exporting || !text.trim()} aria-busy={exporting} onClick={() => void download()}>
    {exporting ? <LoaderCircle aria-hidden="true" className="size-4 motion-safe:animate-spin" /> : <Download aria-hidden="true" className="size-4" />}
    {exporting ? "Preparing…" : resolvedLabel}
  </Button>;
}
