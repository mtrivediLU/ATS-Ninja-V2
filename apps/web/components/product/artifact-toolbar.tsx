"use client";

import { useState } from "react";
import { Copy, Download, FileCode2, RefreshCw, RotateCcw } from "lucide-react";
import { useFeedback } from "@/components/product/feedback";
import type { ArtifactView } from "@/components/product/use-artifact-view";
import { Dialog } from "@/components/ui/dialog";
import { Button, StatusLabel, Tooltip } from "@/components/ui/primitives";
import type { ArtifactValidation, Claim } from "@/lib/api-types";
import { trustCounts } from "@/lib/artifact-presentation";
import { copyText, downloadText } from "@/lib/product";
import { editedPresentation } from "@/lib/status";

type ArtifactToolbarProps = {
  title: string;
  validation: ArtifactValidation;
  claims: Claim[];
  text: string;
  latex?: string;
  filename: string;
  downloadExtension?: "txt" | "md";
  view: ArtifactView;
  onViewChange: (view: ArtifactView) => void;
  editing?: boolean;
  editable?: boolean;
  dirty?: boolean;
  edited?: boolean;
  onBeginEdit?: () => void;
  onApplyLocalEdits?: () => void;
  onExitEdit?: () => void;
  onDiscardChanges?: () => void;
  onReset?: () => void;
  onCompare?: () => void;
  templates?: boolean;
};

export function ArtifactToolbar({
  title,
  validation,
  claims,
  text,
  latex,
  filename,
  downloadExtension = "txt",
  view,
  onViewChange,
  editing = false,
  editable = false,
  dirty = false,
  edited = false,
  onBeginEdit,
  onApplyLocalEdits,
  onExitEdit,
  onDiscardChanges,
  onReset,
  onCompare,
  templates = false,
}: ArtifactToolbarProps) {
  const { notify } = useFeedback();
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [includeLatex, setIncludeLatex] = useState(false);
  const counts = trustCounts(claims, validation);
  const source = editing ? "unsaved local edit" : edited ? "local edit — not revalidated" : "generated version";

  async function copy() {
    try {
      await copyText(text);
      notify(`${title} copied from the ${source}.`);
    } catch {
      notify("Couldn't access the clipboard. Select and copy the text manually.", "error");
    }
  }

  function download() {
    try {
      downloadText(text, `${filename}.${downloadExtension}`, downloadExtension === "md" ? "text/markdown;charset=utf-8" : undefined);
      if (includeLatex && latex) downloadText(latex, `${filename}.tex`, "application/x-tex;charset=utf-8");
      notify(`${title} downloaded from the ${source}.`);
      setDownloadOpen(false);
    } catch {
      notify("Download failed because no usable local content is available.", "error");
    }
  }

  return <>
    <div className="-mx-4 -mt-6 mb-5 flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface px-4 py-3 sm:-mx-6 sm:px-6">
      <div className="min-w-0"><h2 className="font-semibold">{title}</h2><p className="text-xs text-ink-muted">{editing ? "Editing locally — not revalidated" : edited ? "Edited since generation — not revalidated" : "Generated server version"}</p></div>
      <div className="flex flex-wrap gap-1"><span className="rounded-pill border border-positive-border bg-positive-bg px-2.5 py-1 text-xs font-semibold text-positive">{counts.supported} supported</span>{counts.adjusted > 0 && <span className="rounded-pill border border-warning-border bg-warning-bg px-2.5 py-1 text-xs font-semibold text-warning">{counts.adjusted} adjusted</span>}{counts.removed > 0 && <span className="rounded-pill border border-danger-border bg-danger-bg px-2.5 py-1 text-xs font-semibold text-danger">{counts.removed} removed</span>}{counts.withheld > 0 && <span className="rounded-pill border border-danger-border bg-danger-bg px-2.5 py-1 text-xs font-semibold text-danger">{counts.withheld} withheld</span>}</div>
      {edited && <StatusLabel presentation={editedPresentation} />}
      {dirty && <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-warning"><span aria-hidden="true" className="size-2 rounded-pill bg-warning" />Unsaved local changes</span>}
      <span className="flex-1" />
      <div className="inline-flex rounded-control border border-border bg-surface-subtle p-0.5" role="group" aria-label="Artifact view">
        <button type="button" aria-pressed={view === "trust"} onClick={() => onViewChange("trust")} className="min-h-9 rounded-sm px-3 text-sm aria-pressed:bg-surface aria-pressed:font-semibold aria-pressed:shadow-xs">Trust</button>
        <button type="button" aria-pressed={view === "content"} onClick={() => onViewChange("content")} className="min-h-9 rounded-sm px-3 text-sm aria-pressed:bg-surface aria-pressed:font-semibold aria-pressed:shadow-xs">Content</button>
        {templates && <button type="button" aria-pressed={view === "template"} onClick={() => onViewChange("template")} className="min-h-9 rounded-sm px-3 text-sm aria-pressed:bg-surface aria-pressed:font-semibold aria-pressed:shadow-xs">Template</button>}
      </div>
      {editable && !editing && <Button size="sm" variant="secondary" onClick={onBeginEdit}>Edit</Button>}
      {editing && <><Button size="sm" variant="primary" onClick={onApplyLocalEdits}>Apply local edits</Button><Button size="sm" variant="ghost" onClick={() => dirty ? setDiscardOpen(true) : onExitEdit?.()}>Exit edit mode</Button></>}
      {edited && !editing && onCompare && <Button size="sm" variant="ghost" onClick={onCompare}>Compare</Button>}
      {edited && !editing && onReset && <Button size="sm" variant="ghost" onClick={() => setResetOpen(true)}><RotateCcw aria-hidden="true" className="size-4" />Reset to generated</Button>}
      <Button size="sm" onClick={() => void copy()} disabled={!text.trim()}><Copy aria-hidden="true" className="size-4" />Copy</Button>
      <Button size="sm" onClick={() => setDownloadOpen(true)} disabled={!text.trim()}><Download aria-hidden="true" className="size-4" />Download</Button>
      <Tooltip label="No per-artifact regeneration endpoint exists"><Button size="sm" disabled aria-disabled="true"><RefreshCw aria-hidden="true" className="size-4" />Regenerate</Button></Tooltip>
    </div>
    <Dialog open={downloadOpen} onClose={() => setDownloadOpen(false)} title={`Download ${title}`} actions={<><Button variant="ghost" onClick={() => setDownloadOpen(false)}>Cancel</Button><Button variant="primary" onClick={download}>Download</Button></>}>
      <p>Saves the {source} locally. Nothing is uploaded.</p>
      <p className="mt-3 font-mono text-xs text-ink-muted">Filename preview: {filename}.{downloadExtension}</p>
      {latex && <label className="mt-3 flex min-h-11 items-center gap-2"><input type="checkbox" checked={includeLatex} onChange={(event) => setIncludeLatex(event.target.checked)} className="size-4 accent-accent" /><FileCode2 aria-hidden="true" className="size-4" />Also download the engine-provided LaTeX (.tex)</label>}
    </Dialog>
    <Dialog open={discardOpen} onClose={() => setDiscardOpen(false)} title="Discard unsaved changes?" actions={<><Button variant="ghost" onClick={() => setDiscardOpen(false)}>Keep editing</Button><Button variant="destructive" onClick={() => { onDiscardChanges?.(); setDiscardOpen(false); }}>Discard changes</Button></>}>
      These edits have not been applied locally. Discarding restores the last local version and exits edit mode.
    </Dialog>
    <Dialog open={resetOpen} onClose={() => setResetOpen(false)} title="Reset to generated version?" actions={<><Button variant="ghost" onClick={() => setResetOpen(false)}>Cancel</Button><Button variant="destructive" onClick={() => { onReset?.(); setResetOpen(false); }}>Reset to generated</Button></>}>
      This replaces the local edited version with the original grounded, generated content. This action cannot be undone.
    </Dialog>
  </>;
}
