import { X } from "lucide-react";
import { claimStatusPresentation } from "@/lib/status";
import { demoEvidence, type DemoEvidenceRecord } from "@/lib/demo-data";
import { IconButton, StatusLabel } from "@/components/ui/primitives";

export function EvidenceCard({ record }: { record: DemoEvidenceRecord }) {
  return (
    <article className="rounded-md border border-border-subtle bg-surface p-3">
      <StatusLabel presentation={claimStatusPresentation[record.status]} />
      <p className="mt-2 text-sm text-ink">{record.claim}</p>
      <p className="mt-2 font-mono text-xs font-medium text-ink-muted">{record.source} · {record.locator}</p>
      <blockquote className="mt-2 border-l-2 border-border-strong pl-3 text-pretty text-sm italic text-ink-secondary">
        “{record.excerpt}”
      </blockquote>
    </article>
  );
}

export function EvidencePanel({ onClose, compact = false }: { onClose?: () => void; compact?: boolean }) {
  return (
    <aside aria-label="Evidence panel" className={compact ? "flex h-full flex-col" : "flex h-full w-[360px] flex-col border-l border-border bg-surface"}>
      {!compact && (
        <header className="flex min-h-[60px] items-center justify-between gap-3 border-b border-border-subtle px-4">
          <div>
            <h2 className="text-md font-semibold leading-tight">Evidence</h2>
            <p className="text-xs text-ink-muted">Synthetic D0 records</p>
          </div>
          {onClose && <IconButton aria-label="Close evidence panel" onClick={onClose}><X aria-hidden="true" className="size-5" /></IconButton>}
        </header>
      )}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <p className="text-pretty text-sm text-ink-secondary">Why was ATS-Ninja allowed to say this? The panel presents bounded API fields and performs no grounding.</p>
        {demoEvidence.map((record) => <EvidenceCard key={record.id} record={record} />)}
      </div>
    </aside>
  );
}
