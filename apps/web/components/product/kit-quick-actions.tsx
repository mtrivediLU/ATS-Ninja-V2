"use client";

import { Copy, Ellipsis, ShieldAlert } from "lucide-react";
import { useFeedback } from "@/components/product/feedback";
import { QuickPdfDownload } from "@/components/product/quick-pdf-download";
import { useTemplateSelection } from "@/components/product/template-selection";
import { Button, Card } from "@/components/ui/primitives";
import { copyText } from "@/lib/product";
import type { ApplicationKit, KitRead } from "@/lib/api-types";
import { formatAnswersText } from "@/lib/artifact-content";

type KitQuickActionsProps = { kit: KitRead; result: ApplicationKit; onReviewWarnings: () => void; onOpenAnswers: () => void };

export function KitQuickActions({ kit, result, onReviewWarnings, onOpenAnswers }: KitQuickActionsProps) {
  const { notify } = useFeedback();
  const { templateFor } = useTemplateSelection();
  async function copyAnswers() {
    if (!result.answers) return;
    try { await copyText(formatAnswersText(result.answers)); notify("All application answers copied from the generated version."); }
    catch { notify("Couldn't access the clipboard. Open Application answers to copy manually.", "error"); }
  }
  return <section aria-label="Kit quick actions" className="k1-quick-actions"><Card className="flex min-h-[var(--quickbar-h)] flex-wrap items-center gap-2 py-2 shadow-sm">
    {kit.include_resume && result.resume && !result.resume.validation.fatal && <QuickPdfDownload size="sm" variant="primary" kitId={kit.id} artifact="resume" template={templateFor("resume")} text={result.resume.text} label="Download Resume PDF" />}
    {kit.include_cover_letter && result.cover_letter && !result.cover_letter.validation.fatal && <QuickPdfDownload size="sm" variant="primary" kitId={kit.id} artifact="cover-letter" template={templateFor("cover-letter")} text={result.cover_letter.text} label="Download Cover Letter PDF" />}
    {kit.include_application_answers && result.answers && <Button size="sm" variant="secondary" onClick={() => void copyAnswers()}><Copy aria-hidden="true" className="size-4" />Copy all answers</Button>}
    {result.validation.warning_count > 0 && <Button size="sm" variant="secondary" onClick={onReviewWarnings}><ShieldAlert aria-hidden="true" className="size-4" />Review warnings</Button>}
    {result.answers && <Button size="sm" variant="ghost" onClick={onOpenAnswers}><Ellipsis aria-hidden="true" className="size-4" />More actions</Button>}
  </Card></section>;
}
