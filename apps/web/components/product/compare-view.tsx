import { Check, PencilLine } from "lucide-react";

export function CompareView({ generated, edited }: { generated: string; edited: string }) {
  return (
    <section aria-labelledby="comparison-heading" className="mt-5">
      <h2 id="comparison-heading" className="mb-3 text-md font-semibold">Generated versus edited</h2>
      <p className="mb-3 text-sm text-ink-secondary">The generated version is read-only and validated by the engine. The edited version is local and not revalidated. Copy and download never include this comparison markup.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <ComparisonColumn heading="Generated — validated" icon={Check} tone="positive" text={generated} />
        <ComparisonColumn heading="Edited — not revalidated" icon={PencilLine} tone="edited" text={edited} />
      </div>
    </section>
  );
}

function ComparisonColumn({ heading, icon: Icon, tone, text }: { heading: string; icon: typeof Check; tone: "positive" | "edited"; text: string }) {
  const classes = tone === "positive" ? "border-positive-border bg-positive-bg text-positive" : "border-edited-border bg-edited-bg text-edited";
  return <div className="overflow-hidden rounded-md border border-border"><header className={`flex items-center gap-2 border-b px-4 py-3 text-sm font-semibold ${classes}`}><Icon aria-hidden="true" className="size-4" />{heading}</header><pre className="max-h-[420px] overflow-auto whitespace-pre-wrap p-4 font-sans text-sm leading-relaxed text-ink">{text || "No content"}</pre></div>;
}
