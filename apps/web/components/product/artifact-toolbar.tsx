"use client";

import { Copy, Download, FileCode2, RefreshCw, RotateCcw } from "lucide-react";
import { useFeedback } from "@/components/product/feedback";
import { Badge, Button, Tooltip } from "@/components/ui/primitives";
import type { ArtifactValidation, Claim } from "@/lib/api-types";
import { copyText, downloadText } from "@/lib/product";

export function ArtifactToolbar({ title, validation, claims, text, latex, filename, editing, editable = false, dirty = false, onEditingChange, onReset }: { title: string; validation: ArtifactValidation; claims: Claim[]; text: string; latex?: string; filename: string; editing?: boolean; editable?: boolean; dirty?: boolean; onEditingChange?: (editing: boolean) => void; onReset?: () => void }) {
  const { notify } = useFeedback();
  const supported = claims.filter((claim) => claim.status === "supported").length;

  async function copy() {
    try { await copyText(text); notify(`${title} copied.`); } catch { notify("Copy failed. Your browser may have blocked clipboard access.", "error"); }
  }
  function download(content: string, suffix: string, mime?: string) {
    try { downloadText(content, `${filename}.${suffix}`, mime); notify(`${title} downloaded.`); } catch { notify("Download failed because this artifact has no available content.", "error"); }
  }

  return <div className="-mx-4 -mt-6 mb-5 flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface px-4 py-3 sm:-mx-6 sm:px-6">
    <h2 className="mr-1 font-semibold">{title}</h2>
    <div className="flex flex-wrap gap-1"><Badge tone="positive">✓ {supported} supported</Badge>{validation.repaired_claims > 0 && <Badge tone="warning">⚠ {validation.repaired_claims} repaired</Badge>}{validation.rejected_claims > 0 && <Badge tone="danger">⊘ {validation.rejected_claims} rejected</Badge>}</div>
    <span className="flex-1" />
    {editable && <div className="inline-flex rounded-control border border-border bg-surface-subtle p-0.5"><button type="button" aria-pressed={!editing} onClick={() => onEditingChange?.(false)} className="min-h-9 rounded-sm px-3 text-sm aria-pressed:bg-surface aria-pressed:font-semibold aria-pressed:shadow-xs">Read</button><button type="button" aria-pressed={editing} onClick={() => onEditingChange?.(true)} className="min-h-9 rounded-sm px-3 text-sm aria-pressed:bg-surface aria-pressed:font-semibold aria-pressed:shadow-xs">Edit</button></div>}
    {dirty && onReset && <Button size="sm" variant="ghost" onClick={onReset}><RotateCcw aria-hidden="true" className="size-4" />Reset</Button>}
    <Button size="sm" onClick={() => void copy()}><Copy aria-hidden="true" className="size-4" />Copy</Button>
    <Button size="sm" onClick={() => download(text, "txt")}><Download aria-hidden="true" className="size-4" />Text</Button>
    {latex && <Button size="sm" onClick={() => download(latex, "tex", "application/x-tex;charset=utf-8")}><FileCode2 aria-hidden="true" className="size-4" />LaTeX</Button>}
    <Tooltip label="No per-artifact regeneration endpoint exists"><Button size="sm" disabled aria-disabled="true"><RefreshCw aria-hidden="true" className="size-4" />Regenerate</Button></Tooltip>
  </div>;
}
