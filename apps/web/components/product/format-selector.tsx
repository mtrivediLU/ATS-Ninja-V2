"use client";

import type { DocumentFormat } from "@/components/product/quick-pdf-download";

const OPTIONS: { value: DocumentFormat; label: string }[] = [
  { value: "pdf", label: "PDF" },
  { value: "word", label: "Word" },
];

/**
 * One PDF/Word segmented selector shared by both the résumé and cover-letter
 * download buttons. Selecting a format relabels both buttons at once; PDF is
 * the default and always enabled.
 */
export function FormatSelector({ format, onChange }: { format: DocumentFormat; onChange: (format: DocumentFormat) => void }) {
  return (
    <div role="radiogroup" aria-label="Download format" className="inline-flex rounded-control border border-border-strong bg-surface p-0.5">
      {OPTIONS.map((option) => {
        const selected = option.value === format;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className={`min-h-10 rounded-[calc(var(--radius-control)-2px)] px-3.5 text-sm font-semibold transition-colors ${
              selected ? "bg-accent text-on-accent" : "text-ink-secondary hover:bg-surface-subtle"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
