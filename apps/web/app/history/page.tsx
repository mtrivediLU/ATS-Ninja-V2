import type { Metadata } from "next";
import Link from "next/link";
import { History } from "lucide-react";
import { Banner, EmptyState, StatusLabel } from "@/components/ui/primitives";
import { demoHistory } from "@/lib/demo-data";
import { kitStatusPresentation } from "@/lib/status";

export const metadata: Metadata = { title: "Kit history" };

export default function HistoryPage() {
  return (
    <div className="space-y-6">
      <Banner tone="neutral" title="Synthetic history.">These rows exercise lifecycle presentation and navigation only; they were not loaded from the API.</Banner>
      <section aria-labelledby="history-list-title">
        <h2 id="history-list-title" className="mb-3 text-md font-semibold">Recent demonstration kits</h2>
        <div className="space-y-2">
          {demoHistory.map((kit) => (
            <Link key={kit.id} href={kit.status === "completed" ? "/kits/demo/resume" : kit.status === "processing" ? "/states/processing" : "/states/error"} className="flex min-h-16 items-center gap-4 rounded-md border border-border bg-surface p-4 text-ink transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-xs">
              <div className="min-w-0 flex-1"><h3 className="truncate font-semibold">{kit.role} — {kit.company}</h3><p className="truncate font-mono text-xs text-ink-muted">{kit.id} · application-kit/v4</p></div>
              <span className="hidden text-sm text-ink-muted sm:inline">{kit.when}</span>
              <StatusLabel presentation={kitStatusPresentation[kit.status]} />
            </Link>
          ))}
        </div>
      </section>
      <section aria-labelledby="empty-history-title" className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-5">
        <span id="empty-history-title" className="sr-only">Empty history demonstration</span>
        <EmptyState icon={History} title="No saved kits yet" description="This compact synthetic state is used when the API returns an empty history collection." />
      </section>
    </div>
  );
}
